# -*- coding: utf-8 -*-
"""
preprocess.py — M1 数据管线
================================
把 teto_roma 音素采样（wav + TextGrid）转换为 AI 合成训练/渲染数据：

  1. 解析 TextGrid（words 层 = 音素标签，phones 层 = 子音素边界）
  2. 提取 mel 谱（复用 util/wav2mel_numpy.py，参数与 NSF-HiFiGAN 严格一致）
  3. 统计音素时长表（供时长模型/模板拼接使用）
  4. 输出：
     - data_cache/phonemes.json        音素 → 索引 表
     - data_cache/duration_table.json  音素时长统计（均值/标准差）
     - data_cache/templates/*.npz      每音素平均 mel 模板（M2 模板拼接用）
     - data_cache/samples/*.npz        每音素完整样本（训练用）

用法:
    python ai/data/preprocess.py
"""

import json
import re
import sys
import os
from pathlib import Path

import numpy as np

# 允许从 ai/ 目录直接运行（python ai/data/preprocess.py 或 cd ai 后运行）
AI_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AI_DIR))
sys.path.insert(0, str(AI_DIR.parent))  # src/，以便 import util.wav2mel_numpy

import yaml
from util.wav2mel_numpy import PitchAdjustableMelSpectrogramNumpy


# ── TextGrid 解析（ooTextFile 格式，纯标准库） ────────────────────────

def parse_textgrid(path: Path):
    """解析 TextGrid，返回 {tier_name: [(xmin, xmax, text), ...]}
    Praat 的 item/intervals 是缩进格式（无 {} 大括号），按行切分。
    """
    text = path.read_text(encoding='utf-8', errors='replace')
    tiers = {}
    # 按 item [N]: 切分（去掉开头的 "File type..." 等头）
    items = re.split(r'\n\s*item \[\d+\]:', text)[1:]
    for item in items:
        name_m = re.search(r'name = "([^"]*)"', item)
        if not name_m:
            continue
        tier_name = name_m.group(1)
        intervals = []
        # 按 intervals [N]: 切分
        int_blocks = re.split(r'\n\s*intervals \[\d+\]:', item)[1:]
        for iv in int_blocks:
            xmin_m = re.search(r'xmin = ([\d.eE+-]+)', iv)
            xmax_m = re.search(r'xmax = ([\d.eE+-]+)', iv)
            text_m = re.search(r'text = "([^"]*)"', iv)
            if xmin_m and xmax_m:
                intervals.append((
                    float(xmin_m.group(1)),
                    float(xmax_m.group(1)),
                    text_m.group(1) if text_m else '',
                ))
        tiers[tier_name] = intervals
    return tiers


# ── 音频读取 ──────────────────────────────────────────────────────────

def read_wav(path: Path, target_sr: int = 44100) -> np.ndarray:
    """读取 wav → float32 mono，重采样到 target_sr。返回 [T]"""
    try:
        import soundfile as sf
        y, sr = sf.read(str(path), dtype='float32')
    except ImportError:
        import librosa
        y, sr = librosa.load(str(path), sr=None, mono=True)
    if y.ndim > 1:
        y = y.mean(axis=1)
    if sr != target_sr:
        import resampy
        y = resampy.resample(y, sr, target_sr).astype(np.float32)
    return y


# ── 主流程 ────────────────────────────────────────────────────────────

def main():
    import argparse
    ap = argparse.ArgumentParser(description='M1 数据预处理（按音源分目录输出）')
    ap.add_argument('--singer', default='teto_roma', help='音源名（输出到 data_cache/<singer>/）')
    ap.add_argument('--source', default=None, help='采样数据目录（默认 config.data.source_dir）')
    args = ap.parse_args()
    singer = args.singer

    cfg = yaml.safe_load((AI_DIR / 'config.yaml').read_text(encoding='utf-8'))
    src_dir = (AI_DIR / (args.source or cfg['data']['source_dir'])).resolve()
    cache_dir = (AI_DIR / cfg['data']['cache_dir'] / singer).resolve()
    tg_dir = src_dir / 'TextGrid'

    sr = cfg['data']['sample_rate']
    mel_cfg = cfg['mel']
    mel_spec = PitchAdjustableMelSpectrogramNumpy(
        sample_rate=sr,
        n_fft=mel_cfg['n_fft'],
        win_length=mel_cfg['win_size'],
        hop_length=mel_cfg['hop_size'],
        f_min=mel_cfg['f_min'],
        f_max=mel_cfg['f_max'],
        n_mels=mel_cfg['n_mels'],
    )

    if not src_dir.is_dir():
        print(f'[ERROR] source dir not found: {src_dir}')
        sys.exit(1)

    samples_dir = cache_dir / 'samples'
    templates_dir = cache_dir / 'templates'
    for d in (samples_dir, templates_dir):
        d.mkdir(parents=True, exist_ok=True)

    # 收集 wav 文件（排除 .hifi.npz 等缓存）
    wav_files = sorted([p for p in src_dir.glob('*.wav')])
    print(f'[INFO] singer={singer}, found {len(wav_files)} wav files in {src_dir.name}')

    phonemes = {}          # 音素 → 索引
    durations = {}         # 音素 → [时长列表]
    templates = {}         # 音素 → mel 模板（列表累加，最后平均）
    samples_meta = []      # 每音素样本的 meta

    for i, wav_path in enumerate(wav_files):
        stem = wav_path.stem  # 如 "a_"
        phoneme = stem.rstrip('_')

        # 解析 TextGrid
        tg_path = tg_dir / f'{stem}.TextGrid'
        word_label = phoneme
        sub_phones = []  # [(start_s, end_s, label)]
        if tg_path.exists():
            tiers = parse_textgrid(tg_path)
            if 'phones' in tiers and tiers['phones']:
                sub_phones = [(s, e, t) for s, e, t in tiers['phones'] if t.strip()]
            if 'words' in tiers and tiers['words']:
                wl = tiers['words'][0][2].strip()
                if wl:
                    word_label = wl
        if not sub_phones:
            # 无 phones 层 → 整个 wav 一个单元
            sub_phones = [(0.0, 0.0, phoneme)]

        # 读音频 + mel（log 压缩域，与 vocoder 输入严格一致）
        y = read_wav(wav_path, sr)
        mel = mel_spec(y)  # [n_mels, n_frames] 线性幅度
        mel = mel_spec.dynamic_range_compression(mel)  # → log 域，vocoder 输入
        dur_s = len(y) / sr

        # 音素索引
        if word_label not in phonemes:
            phonemes[word_label] = len(phonemes)
        durations.setdefault(word_label, []).append(dur_s)

        # 保存完整样本
        sp_arr = (np.array([(s, e, t.encode('utf-8')) for s, e, t in sub_phones], dtype=object)
                  if sub_phones else np.empty((0, 3), dtype=object))
        np.savez_compressed(
            samples_dir / f'{i:04d}.npz',
            mel=mel.astype(np.float32),
            phoneme=word_label,
            duration=dur_s,
            sub_phones=sp_arr,
        )
        samples_meta.append({
            'file': wav_path.name,
            'phoneme': word_label,
            'duration': round(dur_s, 4),
            'mel_frames': mel.shape[1],
            'sub_phones': [(round(s, 4), round(e, 4), t) for s, e, t in sub_phones],
        })

        # 累计模板（长度归一化到 mel 帧的平均值，稍后统一插值）
        if word_label not in templates:
            templates[word_label] = []
        templates[word_label].append(mel)

        if (i + 1) % 20 == 0:
            print(f'[INFO] processed {i + 1}/{len(wav_files)}')

    # ── 输出 1: 音素表 ──
    (cache_dir / 'phonemes.json').write_text(
        json.dumps(phonemes, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'[INFO] phonemes: {len(phonemes)}')

    # ── 输出 2: 时长表 ──
    duration_table = {}
    for ph, ds in durations.items():
        arr = np.array(ds)
        duration_table[ph] = {
            'mean': round(float(arr.mean()), 4),
            'std': round(float(arr.std()), 4),
            'count': int(len(arr)),
        }
    (cache_dir / 'duration_table.json').write_text(
        json.dumps(duration_table, ensure_ascii=False, indent=2), encoding='utf-8')

    # ── 输出 3: 平均 mel 模板（按中位帧数统一长度） ──
    median_frames = int(np.median([m.shape[1] for lst in templates.values() for m in lst]))
    from scipy.interpolate import interp1d
    for ph, lst in templates.items():
        # 长度归一化到 median_frames，再平均
        resampled = []
        for m in lst:
            t_old = np.linspace(0, 1, m.shape[1])
            t_new = np.linspace(0, 1, median_frames)
            resampled.append(interp1d(t_old, m, axis=1, kind='linear')(t_new))
        avg = np.mean(resampled, axis=0).astype(np.float32)  # [128, median_frames]
        np.savez_compressed(templates_dir / f'{phonemes[ph]}.npz',
                            mel=avg, phoneme=ph)

    # ── meta ──
    (cache_dir / 'samples_meta.json').write_text(
        json.dumps(samples_meta, ensure_ascii=False, indent=2), encoding='utf-8')

    print(f'[DONE] cache written to {cache_dir}')
    print(f'       singer: {singer}, samples: {len(samples_meta)}, templates: {len(templates)}, '
          f'template frames: {median_frames}')
    print(f'       duration table: {len(duration_table)} phonemes')


if __name__ == '__main__':
    main()
