# -*- coding: utf-8 -*-
"""
preprocess_hira.py — teto_hira 单音素数据预处理
=================================================
文件名即音素（假名），通过 hira2roma_list.txt 映射为罗马音。
无 TextGrid → 整个 wav 为一个音素样本（prev/next 用 '#')。

输出格式与 preprocess_cont 一致（兼容 SequenceDataset/GRU 训练）：
  samples/*.npz: mel, phoneme, prev, next, duration, cons_mask, sub_phones

用法:
    python ai/data/preprocess_hira.py --singer teto_hira
"""

import json
import sys
from pathlib import Path

import numpy as np

AI_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AI_DIR))
sys.path.insert(0, str(AI_DIR.parent))

import yaml
from util.wav2mel_numpy import PitchAdjustableMelSpectrogramNumpy
from preprocess import read_wav


def load_hira2roma():
    """hira2roma_list.txt: '假名,罗马音_' → {假名: 罗马音}"""
    table = {}
    p = AI_DIR.parent / 'hira2roma_list.txt'
    if p.exists():
        for line in p.read_text(encoding='utf-8').splitlines():
            if ',' in line:
                h, r = line.strip().split(',', 1)
                table[h] = r.rstrip('_')
    return table


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--singer', default='teto_hira')
    ap.add_argument('--source', default='../teto_hira')
    args = ap.parse_args()
    singer = args.singer

    cfg = yaml.safe_load((AI_DIR / 'config.yaml').read_text(encoding='utf-8'))
    src_dir = (AI_DIR / args.source).resolve()
    cache_dir = (AI_DIR / cfg['data']['cache_dir'] / singer).resolve()
    samples_dir = cache_dir / 'samples'
    templates_dir = cache_dir / 'templates'
    for d in (samples_dir, templates_dir):
        d.mkdir(parents=True, exist_ok=True)

    sr = cfg['data']['sample_rate']
    mel_cfg = cfg['mel']
    mel_spec = PitchAdjustableMelSpectrogramNumpy(
        sample_rate=sr, n_fft=mel_cfg['n_fft'], win_length=mel_cfg['win_size'],
        hop_length=mel_cfg['hop_size'], f_min=mel_cfg['f_min'],
        f_max=mel_cfg['f_max'], n_mels=mel_cfg['n_mels'])

    hira2roma = load_hira2roma()
    wav_files = sorted([p for p in src_dir.glob('*.wav')])
    print(f'[INFO] singer={singer}, found {len(wav_files)} wav (hira)')

    phonemes = {'#': 0}
    durations = {}
    templates = {}
    sample_i = 0
    unmapped = []

    for wav_path in wav_files:
        stem = wav_path.stem.lstrip('_')  # 'きゃ' 等
        phoneme = hira2roma.get(stem, stem)
        if phoneme not in hira2roma.values() and stem not in hira2roma:
            unmapped.append(stem)
        if phoneme not in phonemes:
            phonemes[phoneme] = len(phonemes)

        y = read_wav(wav_path, sr)
        mel = mel_spec(y)
        mel = mel_spec.dynamic_range_compression(mel)
        T = mel.shape[1]
        if T < 2:
            continue
        dur_s = len(y) / sr

        # f0 提取（pyin），对齐到 mel 帧数
        try:
            import librosa
            f0, voiced, _ = librosa.pyin(y, sr=sr, fmin=60, fmax=800,
                                         frame_length=mel_cfg['win_size'],
                                         hop_length=mel_cfg['hop_size'],
                                         n_thresholds=40)
            f0 = np.nan_to_num(f0, nan=0.0).astype(np.float32)
            if len(f0) != T:
                f0 = np.interp(np.linspace(0, 1, T), np.linspace(0, 1, len(f0)), f0)
            rms = librosa.feature.rms(y=y, frame_length=mel_cfg['win_size'],
                                      hop_length=mel_cfg['hop_size'])[0]
            energy = np.log1p(rms).astype(np.float32)
            if len(energy) != T:
                energy = np.interp(np.linspace(0, 1, T), np.linspace(0, 1, len(energy)), energy)
        except Exception:
            f0 = np.zeros(T, dtype=np.float32)
            energy = np.zeros(T, dtype=np.float32)

        durations.setdefault(phoneme, []).append(dur_s)
        templates.setdefault(phoneme, []).append(mel)

        # 单音素孤立样本：prev/next 用 '#'，无辅音标记
        np.savez_compressed(
            samples_dir / f'{sample_i:05d}.npz',
            mel=mel.astype(np.float32),
            phoneme=phoneme, prev='#', next='#',
            duration=dur_s,
            cons_mask=np.zeros(T, dtype=np.float32),
            sub_phones=np.empty((0, 3), dtype=object),
            f0=f0.astype(np.float32),
            energy=energy.astype(np.float32),
        )
        sample_i += 1

    if unmapped:
        print(f'[WARN] unmapped hiragana: {unmapped[:10]}')

    (cache_dir / 'phonemes.json').write_text(
        json.dumps(phonemes, ensure_ascii=False, indent=2), encoding='utf-8')
    dur_table = {w: {'mean': round(float(np.mean(ds)), 4),
                     'std': round(float(np.std(ds)), 4), 'count': len(ds)}
                 for w, ds in durations.items()}
    (cache_dir / 'duration_table.json').write_text(
        json.dumps(dur_table, ensure_ascii=False, indent=2), encoding='utf-8')

    from scipy.interpolate import interp1d
    median_frames = int(np.median([m.shape[1] for lst in templates.values() for m in lst
                                   if m.shape[1] >= 2]))
    for w, lst in templates.items():
        rs = []
        for m in lst:
            if m.shape[1] < 2:
                continue
            rs.append(interp1d(np.linspace(0, 1, m.shape[1]), m, axis=1,
                               kind='linear')(np.linspace(0, 1, median_frames)))
        if not rs:
            continue
        avg = np.mean(rs, axis=0).astype(np.float32)
        np.savez_compressed(templates_dir / f'{phonemes[w]}.npz', mel=avg, phoneme=w)

    print(f'[DONE] samples: {sample_i}, phonemes: {len(phonemes)} (incl #)')
    print(f'       phoneme table: {sorted(phonemes.keys())}')


if __name__ == '__main__':
    main()
