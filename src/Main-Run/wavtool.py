"""
wavtool — 音频拼接器
====================
将多个重采样后的 wav 以交叉淡化（恒功率）拼接成完整音频。
"""

import os
import sys
import yaml
import numpy as np
import librosa
import soundfile as sf


def _load_config(config_path=None):
    if config_path is None:
        config_path = os.path.join(os.path.dirname(__file__), 'config.yaml')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f) or {}
        return cfg.get('audio', {})
    except Exception:
        return {}

SAMPLE_RATE = _load_config().get('sample_rate', 44100)


def crossfade(audio1, audio2, fade_ms=50, sr=SAMPLE_RATE):
    fade = min(int(fade_ms / 1000 * sr), len(audio1), len(audio2))
    if fade <= 0:
        return np.concatenate([audio1, audio2])
    tail = audio1[-fade:]
    head = audio2[:fade]
    fo = np.sqrt(np.linspace(1, 0, fade))
    fi = np.sqrt(np.linspace(0, 1, fade))
    return np.concatenate([
        audio1[:-fade] if len(audio1) > fade else np.array([], dtype=audio1.dtype),
        tail * fo + head * fi,
        audio2[fade:],
    ])


def _normalize(audio, peak=0.95):
    mx = np.max(np.abs(audio))
    if mx > 0:
        return audio * min(1.0, peak / mx)
    return audio


def wavtool(wavs, output='', crossfade_durations_ms=None):
    n = len(wavs)
    if n == 0:
        print('[wavtool] No input files.')
        return None, None

    if crossfade_durations_ms is None:
        crossfade_durations_ms = [50] * (n - 1)
    else:
        need = n - 1
        if len(crossfade_durations_ms) < need:
            crossfade_durations_ms += [50] * (need - len(crossfade_durations_ms))
        else:
            crossfade_durations_ms = crossfade_durations_ms[:need]

    try:
        final, sr = librosa.load(wavs[0], sr=SAMPLE_RATE)
    except Exception:
        print(f'[wavtool] Cannot load {wavs[0]}, using silence')
        sr = SAMPLE_RATE
        final = np.zeros(int(0.1 * sr))

    for i in range(1, n):
        try:
            cur, _ = librosa.load(wavs[i], sr=SAMPLE_RATE)
        except Exception:
            print(f'[wavtool] Cannot load {wavs[i]}, using silence')
            cur = np.zeros(int(0.1 * sr))
        final = crossfade(final, cur, crossfade_durations_ms[i - 1], sr)

    final = _normalize(final, 0.95)

    if output and len(final) > 0:
        sf.write(output, final, sr)
        print(f'[wavtool] Saved -> {output}  ({len(final)/sr:.2f}s)')

    return final, sr


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print('Usage: python wavtool.py <in1.wav> ... <out.wav> [crossfade_ms ...]')
        sys.exit(1)

    args = sys.argv[1:]
    cfs = []
    while len(args) > 2:
        try:
            cfs.insert(0, float(args[-1]))
            args = args[:-1]
        except ValueError:
            break

    if len(args) < 2:
        print('[wavtool] Error: need inputs + output.')
        sys.exit(1)

    inputs, output = args[:-1], args[-1]
    missing = [f for f in inputs if not os.path.exists(f)]
    if missing:
        print(f'[wavtool] Missing: {missing}')
        sys.exit(1)

    print(f'[wavtool] {len(inputs)} files -> {output}')
    if cfs:
        print(f'[wavtool] Crossfade: {cfs}ms')
    wavtool(inputs, output, cfs)
