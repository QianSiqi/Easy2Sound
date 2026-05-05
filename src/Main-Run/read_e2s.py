"""
read_e2s.py — E2S 文件渲染器
按字段名解析 e2s（参照 utaupy 的 dict 方式），调用 resampler + wavtool。
"""

import sys, os
import librosa
import numpy as np
import soundfile as sf


# ── 工具函数 ───────────────────────────────────────────────────────────

def ticks_to_ms(ticks: float, bpm: float) -> float:
    """125 * ticks / bpm  (utaupy 同款公式)"""
    return 125.0 * ticks / bpm


def get_audio_duration(path: str) -> float:
    try:
        y, sr = librosa.load(path)
        return librosa.get_duration(y=y, sr=sr)
    except Exception as e:
        print(f"[WARN] Can't load {path}: {e}")
        return 0.0


def create_silence(duration_s: float, sr=44100):
    n = int(duration_s * sr)
    return np.zeros(n, dtype=np.float32), sr


# ── E2S 解析（dict 方式） ──────────────────────────────────────────────

def read_e2s(path: str) -> list[dict]:
    """
    解析 e2s 文件。
    每个音符返回一个 dict，字段名为 key。
    """
    global resampler, wavtool, singer, phonemer, tempo
    resampler = wavtool = singer = phonemer = ""
    tempo = "120"
    notes: list[dict] = []
    header_done = False

    with open(path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 头部字段
        if not header_done:
            if line.endswith(':'):
                header_done = True
                notes.append({})
                continue
            key, _, val = line.partition('=')
            k = key.strip()
            v = val.strip()
            if k == 'resampler':
                resampler = v
            elif k == 'wavtool':
                wavtool = v
            elif k == 'singer':
                singer = os.path.abspath(v) if not os.path.isabs(v) else v
            elif k == 'phonemer':
                phonemer = v
                print(f'{phonemer} {path}')
                os.system(f'{phonemer} {path}')
            elif k == 'tempo':
                tempo = v
            continue

        # 音符块
        if line.endswith(':'):
            notes.append({})
            continue

        key, _, val = line.partition('=')
        notes[-1][key.strip()] = val.strip()

    return notes


# ── 重采样 ─────────────────────────────────────────────────────────────

def call_resampler(notes: list[dict]):
    global singer, resampler
    print("----------------------------")
    cnt = 0
    for note in notes:
        phoneme = note.get('phoneme', note.get('lyric', ''))
        is_sil = phoneme.lower() in ('r', 'sil', 'pau')

        if is_sil:
            length_ticks = int(float(note.get('length', '480')))
            n_tempo = int(float(note.get('tempo', tempo)))
            dur_ms = ticks_to_ms(length_ticks, n_tempo)
            sil, sr = create_silence(dur_ms / 1000.0)
            out = f"tmp/sil_{cnt}.wav"
            sf.write(out, sil, sr)
            print(f'Silence: {out} ({dur_ms:.0f}ms)')
        else:
            # 从 meta.txt 读取 overlap (fixed_length)
            cons = '0'  # 默认值
            meta_path = f'{singer}/meta.txt'
            if os.path.exists(meta_path):
                with open(meta_path, 'r', encoding='utf-8') as f:
                    for ml in f:
                        if ml.startswith(phoneme):
                            parts = ml.strip().split(',')
                            if len(parts) >= 3:
                                cons = parts[2].strip()
                            break

            length_ticks = int(float(note.get('length', '480')))
            n_tempo = int(float(note.get('tempo', tempo)))
            ms_total = int(ticks_to_ms(length_ticks, n_tempo))  # 期望总时长
            # server 的 length_require 是 stretchable 部分，总输出 = length_require + cons
            ms_stretch = max(0, ms_total - int(cons or 0))
            cutoff = 0

            pitch = note.get('pitch', 'C4')
            velocity = note.get('velocity', '100')
            flags = note.get('flags', '')
            volume = note.get('volume', '100')
            modulation = note.get('modulation', '0')
            tempo_str = note.get('tempo', tempo)
            pitch_str = note.get('pitch_string', 'AA')

            print(f'  [DEBUG] {phoneme}: len_ticks={length_ticks} tempo={n_tempo} -> total_ms={ms_total} stretch_ms={ms_stretch} cons={cons}')

            cmd = (f'{resampler}'
                   f' {singer}/{phoneme}.wav'
                   f' tmp/{phoneme}_{cnt}.wav'
                   f' {pitch} {velocity} {flags}'
                   f' 0 {ms_stretch} {cons} {cutoff}'
                   f' {volume} {modulation} !{tempo_str} {pitch_str}')
            print(cmd)
            os.system(cmd)

        cnt += 1


# ── 拼接 ───────────────────────────────────────────────────────────────

def call_wavtool(notes: list[dict]):
    global wavtool
    wavs = []
    for i, note in enumerate(notes):
        phoneme = note.get('phoneme', note.get('lyric', ''))
        is_sil = phoneme.lower() in ('r', 'sil', 'pau')
        name = 'sil' if is_sil else phoneme
        wavs.append(f'tmp/{name}_{i}.wav')
    wavs.append('tmp/out.wav')

    crossfade_vals = []
    for note in notes[:-1]:
        length_ticks = int(float(note.get('length', '480')))
        n_tempo = int(float(note.get('tempo', '120')))
        note_ms = ticks_to_ms(length_ticks, n_tempo)
        cf = min(50, max(5, int(note_ms * 0.15)))
        crossfade_vals.append(str(cf))

    wavs.extend(crossfade_vals)
    cmd = f"{wavtool} {' '.join(wavs)}"
    print(cmd)
    os.system(cmd)


# ── 入口 ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: read_e2s <filename>")
        sys.exit(1)

    path = sys.argv[1]
    print("----------------------------")
    print(f"Reading e2s: {path}")

    notes = read_e2s(path)

    # phonemer 可能已修改了文件，重新读一遍以获取更新后的值
    notes = read_e2s(path)

    os.system('mkdir tmp 2>nul')

    call_resampler(notes)
    call_wavtool(notes)
