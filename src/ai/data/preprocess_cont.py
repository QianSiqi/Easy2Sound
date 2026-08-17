# -*- coding: utf-8 -*-
"""
preprocess_cont.py — 连续音（VCV）数据预处理
============================================
把 teto_roma_vcv 的连续演唱（wav + TextGrid words 层）切成
带上下文的音节样本：

  样本 = (mel 段, 当前音节, 前音节, 后音节, 时长)
  训练时每帧: (prev, curr, next, 位置, 总帧数) → mel 帧

- words 层 = CV 音节（bi/bu/ka...），与渲染音素体系一致
- SP = 静音段（渲染时按 sil 处理）
- 每样本带前后文 → 模型学会音素过渡（旧数据做不到的）

用法:
    python ai/data/preprocess_cont.py --singer teto_roma_vcv
"""

import json
import re
import sys
from pathlib import Path

import numpy as np

AI_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AI_DIR))
sys.path.insert(0, str(AI_DIR.parent))

import yaml
from util.wav2mel_numpy import PitchAdjustableMelSpectrogramNumpy
from preprocess import parse_textgrid, read_wav  # 复用


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--singer', default='teto_roma_vcv')
    ap.add_argument('--source', default=None)
    args = ap.parse_args()
    singer = args.singer

    cfg = yaml.safe_load((AI_DIR / 'config.yaml').read_text(encoding='utf-8'))
    src_dir = (AI_DIR / (args.source or cfg['data']['source_dir'])).resolve()
    if singer == 'teto_roma_vcv':
        src_dir = (AI_DIR / '..' / 'teto_roma_vcv').resolve() if not args.source else src_dir
    cache_dir = (AI_DIR / cfg['data']['cache_dir'] / singer).resolve()
    tg_dir = src_dir / 'TextGrid'

    sr = cfg['data']['sample_rate']
    mel_cfg = cfg['mel']
    mel_spec = PitchAdjustableMelSpectrogramNumpy(
        sample_rate=sr, n_fft=mel_cfg['n_fft'], win_length=mel_cfg['win_size'],
        hop_length=mel_cfg['hop_size'], f_min=mel_cfg['f_min'],
        f_max=mel_cfg['f_max'], n_mels=mel_cfg['n_mels'])

    samples_dir = cache_dir / 'samples'
    templates_dir = cache_dir / 'templates'
    for d in (samples_dir, templates_dir):
        d.mkdir(parents=True, exist_ok=True)

    wav_files = sorted([p for p in src_dir.glob('*.wav')])
    print(f'[INFO] singer={singer}, found {len(wav_files)} continuous wav files')

    phonemes = {'#': 0}          # 音素表（'#' = 序列边界 padding）
    durations = {}
    templates = {}
    samples_meta = []
    sample_i = 0

    for wav_path in wav_files:
        stem = wav_path.stem
        tg_path = tg_dir / f'{stem}.TextGrid'
        if not tg_path.exists():
            print(f'[WARN] no TextGrid: {tg_path.name}, skip')
            continue
        tiers = parse_textgrid(tg_path)
        if 'words' not in tiers:
            print(f'[WARN] no words tier: {tg_path.name}, skip')
            continue
        words = [(s, e, t.strip()) for s, e, t in tiers['words'] if t.strip()]

        # phones 层：辅音区间（非元音 a/i/u/e/o），用于训练加权
        cons_intervals = []
        if 'phones' in tiers:
            for ps, pe, pt in tiers['phones']:
                pt = pt.strip()
                if pt and pt.lower() not in 'aiueo':
                    cons_intervals.append((ps, pe))

        y = read_wav(wav_path, sr)
        mel = mel_spec(y)
        mel = mel_spec.dynamic_range_compression(mel)
        frames_per_s = sr / mel_cfg['hop_size']

        # 整段 f0（pyin），用于 words 切片的 f0 对齐
        try:
            import librosa
            f0_full, voiced, _ = librosa.pyin(y, sr=sr, fmin=60, fmax=800,
                                              frame_length=mel_cfg['win_size'],
                                              hop_length=mel_cfg['hop_size'],
                                              n_thresholds=40)
            f0_full = np.nan_to_num(f0_full, nan=0.0).astype(np.float32)
            if len(f0_full) != mel.shape[1]:
                f0_full = np.interp(np.linspace(0, 1, mel.shape[1]),
                                    np.linspace(0, 1, len(f0_full)), f0_full)
            # energy 包络（rms，log 域），对齐 mel 帧
            rms = librosa.feature.rms(y=y, frame_length=mel_cfg['win_size'],
                                      hop_length=mel_cfg['hop_size'])[0]
            energy_full = np.log1p(rms).astype(np.float32)
            if len(energy_full) != mel.shape[1]:
                energy_full = np.interp(np.linspace(0, 1, mel.shape[1]),
                                        np.linspace(0, 1, len(energy_full)), energy_full)
        except Exception:
            f0_full = np.zeros(mel.shape[1], dtype=np.float32)
            energy_full = np.zeros(mel.shape[1], dtype=np.float32)

        for i, (ws, we, word) in enumerate(words):
            if word in ('SP', 'sp', 'sil', ''):
                continue  # 静音段不建样本（渲染时按 sil 处理）
            if word not in phonemes:
                phonemes[word] = len(phonemes)
            # 上下文（序列边界用 '#')
            prev_word = words[i - 1][2] if i > 0 else '#'
            next_word = words[i + 1][2] if i < len(words) - 1 else '#'
            prev_word = prev_word if prev_word not in ('SP', 'sp', 'sil') else '#'
            next_word = next_word if next_word not in ('SP', 'sp', 'sil') else '#'

            # 切 mel 段（对应 words 边界）
            fs = int(round(ws * frames_per_s))
            fe = int(round(we * frames_per_s))
            fs, fe = max(0, fs), min(mel.shape[1], fe)
            if fe - fs < 1:
                continue
            seg_mel = mel[:, fs:fe]
            dur_s = (we - ws)

            # 每帧辅音标记（1=辅音帧，训练时加权）
            cons_mask = np.zeros(fe - fs, dtype=np.float32)
            for cs, ce in cons_intervals:
                cf0 = max(0, int(round((cs - ws) * frames_per_s)))
                cf1 = min(fe - fs, int(round((ce - ws) * frames_per_s)))
                if cf1 > cf0:
                    cons_mask[cf0:cf1] = 1.0

            # 音节内辅音段（渲染时辅音融合用）
            # renderer 的 _cons_frames 取第一段 (start,end)，故只存辅音区间
            sub = []
            for cs, ce in cons_intervals:
                if cs >= we or ce <= ws:
                    continue
                sub.append((max(cs, ws), min(ce, we), b'cons'))
            sub_arr = (np.array(sub, dtype=object) if sub
                       else np.empty((0, 3), dtype=object))

            durations.setdefault(word, []).append(dur_s)
            templates.setdefault(word, []).append(seg_mel)

            np.savez_compressed(
                samples_dir / f'{sample_i:05d}.npz',
                mel=seg_mel.astype(np.float32),
                phoneme=word, prev=prev_word, next=next_word,
                duration=dur_s, cons_mask=cons_mask, sub_phones=sub_arr,
                f0=f0_full[fs:fe].astype(np.float32),
                energy=energy_full[fs:fe].astype(np.float32),
            )
            samples_meta.append({
                'file': wav_path.name, 'word': word,
                'prev': prev_word, 'next': next_word,
                'dur': round(dur_s, 3), 'frames': seg_mel.shape[1],
            })
            sample_i += 1

    if not samples_meta:
        print('[ERROR] no samples extracted')
        sys.exit(1)

    # 输出
    (cache_dir / 'phonemes.json').write_text(
        json.dumps(phonemes, ensure_ascii=False, indent=2), encoding='utf-8')
    dur_table = {w: {'mean': round(float(np.mean(ds)), 4),
                     'std': round(float(np.std(ds)), 4), 'count': len(ds)}
                 for w, ds in durations.items()}
    (cache_dir / 'duration_table.json').write_text(
        json.dumps(dur_table, ensure_ascii=False, indent=2), encoding='utf-8')

    # 模板（每音节平均 mel，供 template 模式/辅音融合）
    from scipy.interpolate import interp1d
    median_frames = int(np.median([m.shape[1] for lst in templates.values() for m in lst
                                   if m.shape[1] >= 2]))
    for w, lst in templates.items():
        resampled = []
        for m in lst:
            if m.shape[1] < 2:
                continue
            resampled.append(interp1d(np.linspace(0, 1, m.shape[1]), m, axis=1,
                                      kind='linear')(np.linspace(0, 1, median_frames)))
        if not resampled:
            continue
        avg = np.mean(resampled, axis=0).astype(np.float32)
        np.savez_compressed(templates_dir / f'{phonemes[w]}.npz', mel=avg, phoneme=w)

    (cache_dir / 'samples_meta.json').write_text(
        json.dumps(samples_meta, ensure_ascii=False, indent=2), encoding='utf-8')

    print(f'[DONE] samples: {sample_i}, phonemes: {len(phonemes)} (incl #), '
          f'template frames: {median_frames}')
    print(f'       words in phoneme table: {sorted(phonemes.keys())[:20]}...')


if __name__ == '__main__':
    main()
