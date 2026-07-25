"""
server_onnx.py — ONNX 推理版本的 HifiSampler 服务器
完全移除 PyTorch 依赖，使用 onnxruntime + numpy/scipy/librosa。
"""

import logging
import os
import re
from pathlib import Path
import dataclasses
import sys
import tempfile
import traceback
import yaml

import numpy as np
import soundfile as sf
import scipy.interpolate as interp
import resampy
from http.server import BaseHTTPRequestHandler, HTTPServer
from concurrent.futures import ThreadPoolExecutor
from filelock import FileLock, Timeout

from util.load_config_from_yaml import load_config_from_yaml
from util.wav2mel_numpy import PitchAdjustableMelSpectrogramNumpy
from util.hnsep_onnx_infer import HnsepOnnxDemo, pre_emphasis_base_tension

logging.basicConfig(format='%(message)s', level=logging.INFO)

version = '0.0.1 onnx'
help_string = '''usage: resampler in_file out_file pitch velocity [flags] [offset] [length] [consonant] [cutoff] [volume] [modulation] [tempo] [pitch_string]

Resamples using the PC-NSF-HIFIGAN Vocoder (ONNX).

arguments:
\tin_file\t\tPath to input file.
\tout_file\tPath to output file.
\tpitch\t\tThe pitch to render on.
\tvelocity\tThe consonant velocity of the render.

optional arguments:
\tflags\t\tThe flags of the render. But now, it's not implemented yet.
\toffset\t\tThe offset from the start of the render area of the sample. (default: 0)
\tlength\t\tThe length of the stretched area in milliseconds. (default: 1000)
\tconsonant\tThe unstretched area of the render in milliseconds. (default: 0)
\tcutoff\t\tThe cutoff from the end or from the offset for the render area of the sample. (default: 0)
\tvolume\t\tThe volume of the render in percentage. (default: 100)
\tmodulation\tThe pitch modulation of the render in percentage. (default: 0)
\ttempo\t\tThe tempo of the render. Needs to have a ! at the start. (default: !100)
\tpitch_string\tThe UTAU pitchbend parameter written in Base64 with RLE encoding. (default: AA)'''

notes = {'C': 0, 'C#': 1, 'D': 2, 'D#': 3, 'E': 4, 'F': 5, 'F#': 6,
         'G': 7, 'G#': 8, 'A': 9, 'A#': 10, 'B': 11}
note_re = re.compile(r'([A-G]#?)(-?\d+)')
cache_ext = '.hifi.npz'

# Flags
flags = ['fe', 'fl', 'fo', 'fv', 'fp', 've', 'vo', 'g', 't',
         'A', 'B', 'G', 'P', 'S', 'p', 'R', 'D', 'C', 'Z', 'Hv', 'Hb', 'Ht', 'He']
flag_re = '|'.join(flags)
flag_re = f'({flag_re})([+-]?\\d+)?'
flag_re = re.compile(flag_re)

server_ready = False


@load_config_from_yaml(script_path=Path(__file__))
@dataclasses.dataclass
class Config:
    sample_rate: int = 44100
    win_size: int = 2048
    hop_size: int = 512
    origin_hop_size: int = 128
    n_mels: int = 128
    n_fft: int = 2048
    mel_fmin: float = 40
    mel_fmax: float = 16000
    fill: int = 6
    vocoder_path: str = r"pc_nsf_hifigan_44.1k_hop512_128bin_2025.02.onnx"
    model_type: str = 'onnx'
    hnsep_model_path: str = r"hnsep\vr\model.onnx"
    wave_norm: bool = False
    loop_mode: bool = False
    peak_limit: float = 1.0
    max_workers: int = 1


# ── ONNX 模式覆盖 config.yaml 中的 ckpt/pt 路径 ──
Config.model_type = 'onnx'
Config.max_workers = 1
if Config.vocoder_path.endswith('.ckpt'):
    Config.vocoder_path = Config.vocoder_path.replace('.ckpt', '.onnx')
if Config.hnsep_model_path.endswith('.pt'):
    Config.hnsep_model_path = Config.hnsep_model_path.replace('.pt', '.onnx')


class DotDict(dict):
    def __getattr__(*args):
        val = dict.get(*args)
        return DotDict(val) if type(val) is dict else val

    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__


def loudness_norm(
    audio: np.ndarray, rate: int, peak=-1.0, loudness=-23.0, block_size=0.400, strength=100
) -> np.ndarray:
    original_length = len(audio)
    if original_length < int(rate * block_size):
        padding_length = int(rate * block_size) - original_length
        audio = np.pad(audio, (0, padding_length), mode='reflect')

    meter = pyln.Meter(rate, block_size=block_size)
    _loudness = meter.integrated_loudness(audio)
    final_loudness = _loudness + (loudness - _loudness) * strength / 100
    audio = pyln.normalize.loudness(audio, _loudness, final_loudness)

    if original_length < int(rate * block_size):
        audio = audio[:original_length]

    return audio


# ── Pitch string interpreter ──────────────────────────────────────────


def to_uint6(b64):
    c = ord(b64)
    if c >= 97:
        return c - 71
    elif c >= 65:
        return c - 65
    elif c >= 48:
        return c + 4
    elif c == 43:
        return 62
    elif c == 47:
        return 63
    else:
        raise Exception


def to_int12(b64):
    uint12 = to_uint6(b64[0]) << 6 | to_uint6(b64[1])
    if uint12 >> 11 & 1 == 1:
        return uint12 - 4096
    else:
        return uint12


def to_int12_stream(b64):
    res = []
    for i in range(0, len(b64), 2):
        res.append(to_int12(b64[i:i+2]))
    return res


def pitch_string_to_cents(x):
    pitch = x.split('#')
    res = []
    for i in range(0, len(pitch), 2):
        p = pitch[i:i+2]
        if len(p) == 2:
            pitch_str, rle = p
            res.extend(to_int12_stream(pitch_str))
            res.extend([res[-1]] * int(rle))
        else:
            res.extend(to_int12_stream(p[0]))
    res = np.array(res, dtype=np.int32)
    if np.all(res == res[0]):
        return np.zeros(res.shape)
    else:
        return np.concatenate([res, np.zeros(1)])


# ── Pitch conversion ──────────────────────────────────────────────────


def note_to_midi(x):
    note, octave = note_re.match(x).group(1, 2)
    octave = int(octave) + 1
    return octave * 12 + notes[note]


def midi_to_hz(x):
    return 440 * np.exp2((x - 69) / 12)


# ── WAV read/write ────────────────────────────────────────────────────


def read_wav(loc):
    if type(loc) == str:
        loc = Path(loc)

    exists = loc.exists()
    if not exists:
        for ext in sf.available_formats().keys():
            loc = loc.with_suffix('.' + ext.lower())
            exists = loc.exists()
            if exists:
                break

    if not exists:
        raise FileNotFoundError("No supported audio file was found.")

    x, fs = sf.read(str(loc))
    if len(x.shape) == 2:
        x = np.mean(x, axis=1)

    if fs != Config.sample_rate:
        x = resampy.resample(x, fs, Config.sample_rate)

    return x


def save_wav(loc, x):
    try:
        sf.write(str(loc), x, Config.sample_rate, 'PCM_16')
    except Exception as e:
        logging.error(f"Error saving WAV file: {e}")


# ── Resampler ─────────────────────────────────────────────────────────


class Resampler:
    def __init__(self, in_file, out_file, pitch, velocity, flags='', offset=0, length=1000, consonant=0, cutoff=0, volume=100, modulation=0, tempo='!100', pitch_string='AA'):
        self.in_file = Path(in_file)
        self.out_file = out_file
        self.pitch = note_to_midi(pitch)
        self.velocity = float(velocity)
        self.flags = {k: int(v) if v else None for k,
                      v in flag_re.findall(flags.replace('/', ''))}
        self.offset = float(offset)
        self.length = int(length)
        self.consonant = float(consonant)
        self.cutoff = float(cutoff)
        self.volume = float(volume)
        self.modulation = float(modulation)
        self.tempo = float(tempo[1:])
        self.pitchbend = pitch_string_to_cents(pitch_string)

        self.render()

    def render(self):
        features = self.get_features()
        self.resample(features)

    def get_features(self):
        features_path = self.in_file.with_suffix(cache_ext)

        self.flags['Hb'] = self.flags.get('Hb', 100)
        self.flags['Hv'] = self.flags.get('Hv', 100)
        self.flags['Ht'] = self.flags.get('Ht', 0)
        self.flags['g'] = self.flags.get('g', 0)

        flag_suffix = '_'.join(f"{k}{v if v is not None else ''}" for k, v in sorted(
            self.flags.items()) if k in ['Hb', 'Hv', 'Ht', 'g'])
        if flag_suffix:
            features_path = features_path.with_name(
                f'{self.in_file.stem}_{flag_suffix}{cache_ext}')
        else:
            features_path = features_path.with_name(
                f'{self.in_file.stem}{cache_ext}')

        lock_path = str(features_path) + ".lock"

        lock = FileLock(lock_path, timeout=60)
        features = None

        try:
            with lock:
                force_generate = 'G' in self.flags.keys()

                if force_generate:
                    logging.info('G flag exists. Forcing feature generation.')
                    features = self.generate_features(features_path)
                elif features_path.exists():
                    try:
                        features = np.load(str(features_path))
                        logging.info('Cache loaded successfully.')
                    except (EOFError, OSError, ValueError) as e:
                        logging.warning(
                            f'Failed to load cache {features_path} ({type(e).__name__}: {e}). Regenerating...')
                        try:
                            os.remove(features_path)
                        except OSError as rm_err:
                            logging.error(
                                f"Could not remove corrupted cache file {features_path}: {rm_err}")
                        features = self.generate_features(features_path)
                else:
                    logging.info(
                        f'{features_path} not found. Generating features.')
                    features = self.generate_features(features_path)

                logging.info(f'File lock released for {lock_path}')

        except Timeout:
            logging.error(
                f"Could not acquire lock for {lock_path} within 60 seconds!")
            raise RuntimeError(
                f"Failed to acquire cache lock for {features_path}")

        if features is None:
            logging.error(
                f"Logic error: Features could not be loaded or generated for {features_path}")
            raise RuntimeError(f"Could not get features for {features_path}")

        return features

    def generate_features(self, features_path):
        wave = read_wav(self.in_file)
        # wave: [T] numpy array

        breath = self.flags.get("Hb", 100)
        voicing = self.flags.get("Hv", 100)
        tension = self.flags.get("Ht", 0)
        print(f'breath: {breath}, voicing: {voicing}, tension: {tension}')

        if breath != 100 or voicing != 100 or tension != 0:
            logging.info(
                'Hb or Hv or Ht flag exists. Split audio into breath, voicing')
            # hnsep 推理：wave [T] → [1, 1, T]
            wave_tensor = wave[np.newaxis, np.newaxis, :].astype(np.float32)
            seg_output = hnsep_model.predict_fromaudio(wave_tensor)
            # seg_output: [1, 1, T]
            seg_output = seg_output[0, 0]  # [T]

            breath = np.clip(breath, 0, 500)
            voicing = np.clip(voicing, 0, 150)
            if tension != 0:
                tension = np.clip(tension, -100, 100)
                voicing_wave = (voicing / 100) * seg_output
                voicing_wave_3d = voicing_wave[np.newaxis, np.newaxis, :].astype(np.float32)
                tension_wave = pre_emphasis_base_tension(
                    voicing_wave_3d, -tension / 50,
                    config={'n_fft': Config.n_fft, 'hop_size': Config.hop_size,
                            'win_size': Config.win_size, 'sample_rate': Config.sample_rate}
                )
                wave = (breath / 100) * (wave - seg_output) + tension_wave[0, 0]
            else:
                wave = (breath / 100) * (wave - seg_output) + \
                    (voicing / 100) * seg_output

        # wave: [T] numpy array
        wave_2d = wave[np.newaxis, :].astype(np.float32)  # [1, T]
        wave_max = np.max(np.abs(wave_2d))
        if wave_max >= 0.5:
            logging.info('The audio volume is too high. Scaling down to 0.5')
            scale = 0.5 / wave_max
            wave_2d = wave_2d * scale
            scale = float(scale)
        else:
            logging.info('The audio volume is already low enough')
            scale = 1.0

        gender = self.flags.get("g", 0)
        gender = np.clip(gender, -600, 600)
        logging.info(f'gender: {gender}')

        mel_origin = melAnalysis(
            wave_2d,
            gender / 100, 1).squeeze()
        logging.info(f'mel_origin: {mel_origin.shape}')
        mel_origin = melAnalysis.dynamic_range_compression(mel_origin).astype(np.float32)
        logging.info('Saving features.')

        features = {'mel_origin': mel_origin, 'scale': scale}

        # 原子写入
        temp_suffix = ".tmp"
        temp_path = features_path.with_suffix(
            features_path.suffix + temp_suffix)

        try:
            np.savez_compressed(str(temp_path), **features)
            os.replace(str(temp_path) + '.npz', str(features_path))
            logging.info(f'Features saved successfully to {features_path}')
        except Exception as e:
            logging.error(
                f'Error during saving/renaming cache file {features_path}: {e}', exc_info=True)

            if temp_path.exists():
                try:
                    os.remove(str(temp_path))
                    logging.info(
                        f'Removed temporary file {temp_path} after error.')
                except OSError as rm_err:
                    logging.error(
                        f"Could not remove temporary file {temp_path} after error: {rm_err}")
            raise

        return features

    def resample(self, features):
        if self.out_file == 'nul':
            logging.info('Null output file. Skipping...')
            return

        mod = self.modulation / 100
        logging.info(f"mod: {mod}")

        self.out_file = Path(self.out_file)
        wave = read_wav(Path(self.in_file))
        logging.info(f'wave: {wave.shape}')

        scale = features['scale']
        logging.info(f'scale: {scale}')

        mel_origin = features['mel_origin']
        logging.info(f'mel_origin: {mel_origin.shape}')

        thop_origin = Config.origin_hop_size / Config.sample_rate
        thop = Config.hop_size / Config.sample_rate
        logging.info(f'thop_origin: {thop_origin}')
        logging.info(f'thop: {thop}')

        t_area_origin = np.arange(
            mel_origin.shape[1]) * thop_origin + thop_origin / 2
        total_time = t_area_origin[-1] + thop_origin / 2
        logging.info(f"t_area_mel_origin: {t_area_origin.shape}")
        logging.info(f"total_time: {total_time}")

        vel = np.exp2(1 - self.velocity / 100)
        offset = self.offset / 1000
        cutoff = self.cutoff / 1000
        start = offset
        logging.info(f'vel:{vel}')
        logging.info(f'offset:{offset}')
        logging.info(f'cutoff:{cutoff}')

        logging.info('Calculating timing.')
        if self.cutoff < 0:
            end = start - cutoff
        else:
            end = total_time - cutoff
        con = start + self.consonant / 1000
        logging.info(f'start:{start}')
        logging.info(f'end:{end}')
        logging.info(f'con:{con}')

        logging.info('Preparing interpolators.')

        length_req = self.length / 1000
        stretch_length = end - con
        logging.info(f'length_req: {length_req}')
        logging.info(f'stretch_length: {stretch_length}')

        if Config.loop_mode or "He" in self.flags.keys():
            logging.info('Looping.')
            logging.info(
                f'con_mel_frame: {int((con + thop_origin / 2) // thop_origin)}')
            mel_loop = mel_origin[:, int(
                (con + thop_origin / 2) // thop_origin):int((end + thop_origin / 2) // thop_origin)]
            logging.info(f'mel_loop: {mel_loop.shape}')
            pad_loop_size = length_req // thop_origin + 1
            logging.info(f'pad_loop_size: {pad_loop_size}')
            padded_mel = np.pad(mel_loop, pad_width=(
                (0, 0), (0, int(pad_loop_size))), mode='reflect')
            logging.info(f'padded_mel: {padded_mel.shape}')
            mel_origin = np.concatenate(
                (mel_origin[:, :int((con + thop_origin / 2) // thop_origin)], padded_mel), axis=1)
            logging.info(f'mel_origin: {mel_origin.shape}')
            stretch_length = pad_loop_size * thop_origin
            t_area_origin = np.arange(
                mel_origin.shape[1]) * thop_origin + thop_origin / 2
            total_time = t_area_origin[-1] + thop_origin / 2
            logging.info(f'new_total_time: {total_time}')

        # Make interpolators to render new areas
        mel_interp = interp.interp1d(t_area_origin, mel_origin, axis=1)

        if stretch_length < length_req:
            logging.info('stretch_length < length_req')
            scaling_ratio = length_req / stretch_length
        else:
            logging.info('stretch_length >= length_req, no stretching needed.')
            scaling_ratio = 1

        def stretch(t, con, scaling_ratio):
            return np.where(t < vel * con, t / vel, con + (t - vel * con) / scaling_ratio)

        stretched_n_frames = (con * vel + (total_time - con)
                              * scaling_ratio) // thop + 1
        stretched_t_mel = np.arange(stretched_n_frames) * thop + thop / 2
        logging.info(f'stretched_n_frames: {stretched_n_frames}')
        logging.info(f'stretched_t_mel: {stretched_t_mel.shape}')

        start_left_mel_frames = (start * vel + thop / 2) // thop
        if start_left_mel_frames > Config.fill:
            cut_left_mel_frames = start_left_mel_frames - Config.fill
        else:
            cut_left_mel_frames = 0
        logging.info(f'start_left_mel_frames: {start_left_mel_frames}')
        logging.info(f'cut_left_mel_frames: {cut_left_mel_frames}')

        end_right_mel_frames = stretched_n_frames - \
            (length_req + con * vel + thop / 2) // thop
        if end_right_mel_frames > Config.fill:
            cut_right_mel_frames = end_right_mel_frames - Config.fill
        else:
            cut_right_mel_frames = 0
        logging.info(f'end_right_mel_frames: {end_right_mel_frames}')
        logging.info(f'cut_right_mel_frames: {cut_right_mel_frames}')

        logging.info(f'length_req: {length_req}')
        logging.info(f'stretch_length: {stretch_length}')
        logging.info(
            f'(length_req+con*vel + thop/2)//thop: {(length_req + con * vel + thop / 2) // thop}')

        stretched_t_mel = stretched_t_mel[int(cut_left_mel_frames):int(
            stretched_n_frames - cut_right_mel_frames)]
        logging.info(f'stretched_t_mel: {stretched_t_mel.shape}')

        stretch_t_mel = np.clip(
            stretch(stretched_t_mel, con, scaling_ratio), 0, t_area_origin[-1])
        logging.info(f'stretch_t_mel: {stretch_t_mel.shape}')

        new_start = start * vel - cut_left_mel_frames * thop
        new_end = (length_req + con * vel) - cut_left_mel_frames * thop
        logging.info(f'new_start: {new_start}')
        logging.info(f'new_end: {new_end}')
        logging.info(f'stretched_t_mel[0]: {stretched_t_mel[0]}')
        logging.info(f'stretched_t_mel[-1]: {stretched_t_mel[-1]}')

        mel_render = mel_interp(stretch_t_mel)
        logging.info(f'mel_render: {mel_render.shape}')

        t = np.arange(mel_render.shape[1]) * thop
        logging.info(f't: {t.shape}')
        logging.info('Calculating pitch.')
        pitch = self.pitchbend / 100 + self.pitch
        if "t" in self.flags.keys() and self.flags["t"]:
            pitch = pitch + self.flags["t"] / 100
        t_pitch = 60 * np.arange(len(pitch)) / (self.tempo * 96) + new_start
        pitch_interp = interp.Akima1DInterpolator(t_pitch, pitch)
        pitch_render = pitch_interp(np.clip(t, new_start, t_pitch[-1]))
        f0_render = midi_to_hz(pitch_render)
        logging.info(f'f0_render: {f0_render.shape}')

        logging.info('Cutting mel and f0.')

        # ── ONNX vocoder 推理 ──
        logging.info('Rendering audio.')
        f0 = f0_render.astype(np.float32)
        mel = mel_render.astype(np.float32)
        mel = np.expand_dims(mel, axis=0).transpose(0, 2, 1)  # [1, T, n_mels]
        f0 = np.expand_dims(f0, axis=0)  # [1, T]
        input_data = {'mel': mel, 'f0': f0}
        output = ort_session.run(['waveform'], input_data)[0]
        wav_con = output[0]

        render = wav_con[int(new_start * Config.sample_rate)
                         :int(new_end * Config.sample_rate)]
        logging.info(f'cut_l:{int(new_start * Config.sample_rate)}')
        logging.info(
            f'cut_r:{len(wav_con) - int(new_end * Config.sample_rate)}')
        logging.info(
            f'mel_l:{(int(new_start * Config.sample_rate) + 256) // Config.hop_size}')
        logging.info(
            f'mel_r:{(len(wav_con) - int(new_end * Config.sample_rate) + 256) // Config.hop_size}')

        logging.info(f'wav_con: {wav_con.shape}')
        logging.info(f'render: {render.shape}')

        # 添加幅度调制
        A_flag = self.flags.get('A', 0)
        if A_flag != 0:
            logging.info(f'Applying Amplitude Modulation A={A_flag}')
            A_clamped = np.clip(A_flag, -100, 100)

            if len(pitch_render) > 1 and len(t) > 1:
                pitch_derivative = np.gradient(pitch_render, t)
                gain_at_mel_frames = 5 ** ((10 ** -4) *
                                           A_clamped * pitch_derivative)
                num_samples = len(render)
                audio_time_vector = np.linspace(
                    new_start, new_end, num=num_samples, endpoint=False)

                interpolated_gain = np.interp(audio_time_vector,
                                              t,
                                              gain_at_mel_frames,
                                              left=gain_at_mel_frames[0],
                                              right=gain_at_mel_frames[-1])

                render = render * interpolated_gain
                logging.info('Amplitude modulation applied.')
            else:
                logging.warning(
                    "Not enough pitch points (>1) to calculate derivative for Amplitude Modulation.")

        render = render / scale
        new_max = np.max(np.abs(render))

        # normalize using loudness_norm
        if Config.wave_norm:
            if "P" in self.flags.keys():
                p_strength = self.flags['P']
                if p_strength is not None:
                    render = loudness_norm(
                        render, Config.sample_rate, peak=-1, loudness=-16.0, block_size=0.400, strength=p_strength)
                else:
                    render = loudness_norm(
                        render, Config.sample_rate, peak=-1, loudness=-16.0, block_size=0.400)

        if new_max > Config.peak_limit:
            render = render / new_max
        save_wav(self.out_file, render)


# ── HTTP ──────────────────────────────────────────────────────────────


def split_arguments(input_string):
    otherargs = input_string.split(' ')[-11:]
    file_path_strings = ' '.join(input_string.split(' ')[:-11])
    first_file, second_file = file_path_strings.split('.wav ')
    return [first_file + ".wav", second_file] + otherargs


class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if server_ready:
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Server Ready')
        else:
            self.send_response(503)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Server Initializing')
            logging.info(
                "Responded 503 Service Unavailable to readiness check (server not ready).")
        return

    def do_POST(self):
        if not server_ready:
            logging.warning(
                "Received POST request before server was fully ready. Sending 503.")
            self.send_response(503)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Server initializing, please retry.')
            return

        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        post_data_string = post_data.decode('utf-8')
        logging.info(f"post_data_string: {post_data_string}")
        try:
            sliced = split_arguments(post_data_string)
            in_file_path = Path(sliced[0])
            out_file_path = Path(sliced[1])
            note_info_for_log = f"'{in_file_path.stem}' -> '{out_file_path.name}'"
            logging.info(f"Processing {note_info_for_log} begins...")

            Resampler(*sliced)

            logging.info(f"Processing {note_info_for_log} successful.")
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(f"Success: {note_info_for_log}".encode('utf-8'))

        except FileNotFoundError:
            error_msg = f"Error processing {note_info_for_log}: Input file not found."
            logging.error(error_msg, exc_info=True)
            self.send_response(404)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(
                f"{error_msg}\n{traceback.format_exc()}".encode('utf-8'))

        except Exception:
            error_msg = f"[Error processing {note_info_for_log}: An internal error occurred."
            logging.error(error_msg, exc_info=True)
            self.send_response(500)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(
                f"{error_msg}\n{traceback.format_exc()}".encode('utf-8'))


class ThreadPoolHTTPServer(HTTPServer):
    def __init__(self, server_address, RequestHandlerClass, max_workers):
        super().__init__(server_address, RequestHandlerClass)
        self.executor = ThreadPoolExecutor(max_workers=max_workers)

    def process_request(self, request, client_address):
        self.executor.submit(self.process_request_thread,
                             request, client_address)

    def process_request_thread(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)


def run(server_class=ThreadPoolHTTPServer, handler_class=RequestHandler, port=8572, max_workers=1):
    server_address = ('', port)
    httpd = server_class(server_address, handler_class,
                         max_workers=max_workers)
    logging.info(
        f'Listening on port {port} with {max_workers} worker threads...')
    global server_ready
    server_ready = True
    httpd.serve_forever()


# ── Main ──────────────────────────────────────────────────────────────

if __name__ == '__main__':
    lock_file_path = Path(tempfile.gettempdir()) / 'server.lock'

    try:
        with FileLock(str(lock_file_path), timeout=0.5) as server_lock:
            logging.info(
                f"Successfully acquired server lock: {lock_file_path}")
            logging.info("This process will start the Resampler server (ONNX).")

            global hnsep_model, melAnalysis, ort_session

            if Config.wave_norm:
                try:
                    import pyloudnorm as pyln
                    logging.info("pyloudnorm imported for wave normalization.")
                except ImportError:
                    logging.warning(
                        "pyloudnorm not found, wave normalization disabled.")
                    Config.wave_norm = False

            logging.info(f'resampler {version}')

            # ── Load HifiGAN (ONNX only) ──
            vocoder_path = Path(Config.vocoder_path)
            onnx_default_path = Path(
                r"pc_nsf_hifigan_44.1k_hop512_128bin_2025.02.onnx")
            onnx_subdir_path = Path(
                r"pc_nsf_hifigan_44.1k_hop512_128bin_2025.02\model.onnx")

            actual_vocoder_path = None
            if vocoder_path.exists():
                actual_vocoder_path = vocoder_path
            elif onnx_subdir_path.exists():
                actual_vocoder_path = onnx_subdir_path
                logging.info(
                    f"Configured vocoder path not found, using: {onnx_subdir_path}")
            elif onnx_default_path.exists():
                actual_vocoder_path = onnx_default_path
                logging.info(
                    f"Configured vocoder path not found, using default: {onnx_default_path}")
            else:
                raise FileNotFoundError(
                    f"No HifiGAN ONNX model found. Checked '{Config.vocoder_path}' and defaults.")

            if actual_vocoder_path.suffix != '.onnx':
                raise ValueError(
                    f'server_onnx.py only supports .onnx models, got: {actual_vocoder_path}')

            import onnxruntime
            Config.model_type = 'onnx'
            Config.max_workers = 1

            available_providers = onnxruntime.get_available_providers()
            provider_candidates = []
            if 'DmlExecutionProvider' in available_providers:
                provider_candidates.append(['DmlExecutionProvider', 'CPUExecutionProvider'])
            if 'CUDAExecutionProvider' in available_providers:
                provider_candidates.append(['CUDAExecutionProvider', 'CPUExecutionProvider'])
            provider_candidates.append(['CPUExecutionProvider'])

            ort_session = None
            for prov_list in provider_candidates:
                try:
                    ort_session = onnxruntime.InferenceSession(
                        str(actual_vocoder_path), providers=prov_list)
                    # 验证 provider 是否真正可用
                    import numpy as np
                    _ = ort_session.get_providers()
                    logging.info(
                        f'Loaded HifiGAN (onnx): {actual_vocoder_path} using providers {_}')
                    break
                except Exception as e:
                    logging.warning(f'Provider {prov_list[0]} failed for vocoder: {e}, trying next...')
                    ort_session = None
                    continue

            if ort_session is None:
                raise RuntimeError(f'Failed to load vocoder ONNX with any provider')

            # ── Load HN-SEP (ONNX) ──
            hnsep_path = Path(Config.hnsep_model_path)
            if not hnsep_path.exists():
                raise FileNotFoundError(
                    f"HN-SEP ONNX model not found: {hnsep_path}")

            hnsep_model = HnsepOnnxDemo(
                str(hnsep_path),
                config_path=str(hnsep_path.parent / 'config.yaml')
            )
            logging.info(f'Loaded HN-SEP (onnx): {hnsep_path}')

            # ── Initialize Mel Spectrogram (numpy) ──
            melAnalysis = PitchAdjustableMelSpectrogramNumpy(
                sample_rate=Config.sample_rate,
                n_fft=Config.n_fft,
                win_length=Config.win_size,
                hop_length=Config.origin_hop_size,
                f_min=Config.mel_fmin,
                f_max=Config.mel_fmax,
                n_mels=Config.n_mels
            )
            logging.info(
                f'Initialized Mel Analysis (numpy) with hop_size={Config.origin_hop_size}.')

            logging.info("Starting the HTTP server...")
            run(max_workers=Config.max_workers)
            logging.info("Server has stopped.")

    except Timeout:
        logging.info(
            f"Another instance of the server seems to be running (lock file '{lock_file_path}' is held). Exiting.")
        sys.exit(0)

    except Exception as e:
        logging.error(
            f"Failed to initialize or start the server: {e}", exc_info=True)
        sys.exit(1)
