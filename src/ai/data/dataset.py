# -*- coding: utf-8 -*-
"""
dataset.py — 上下文 GRU 声学模型训练数据集
============================================
整段样本：每个音素段一个样本，返回
  (prev, curr, next, pos[T], mel[T,128], cons_mask[T])

时长增强范围 0.15×~1.5×（覆盖渲染短音符），保持过渡结构整体缩放。
"""

import json
import sys
from pathlib import Path

import numpy as np

AI_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AI_DIR))

import yaml


def _interp_time(mel, T2):
    """mel [C, T] → [C, T2]，numpy 线性插值（比 scipy interp1d 快 10 倍）"""
    T = mel.shape[1]
    if T == T2:
        return mel
    x_old = np.linspace(0, 1, T)
    x_new = np.linspace(0, 1, T2)
    return np.array([np.interp(x_new, x_old, mel[i]) for i in range(mel.shape[0])],
                    dtype=np.float32)


class SequenceDataset:
    def __init__(self, cache_dir: Path = None, augment: bool = True,
                 noise_std: float = 0.01, time_aug: bool = True,
                 time_range=(0.15, 1.5)):
        cfg = yaml.safe_load((AI_DIR / 'config.yaml').read_text(encoding='utf-8'))
        cache_dir = (cache_dir or (AI_DIR / cfg['data']['cache_dir'])).resolve()
        self.phonemes = json.loads((cache_dir / 'phonemes.json').read_text(encoding='utf-8'))
        self.augment = augment
        self.noise_std = noise_std
        self.time_aug = time_aug
        self.time_range = time_range

        # (prev_idx, curr_idx, next_idx, mel [128,T], cons_mask [T], f0 [T], energy [T])
        self.samples = []
        for npz in sorted((cache_dir / 'samples').glob('*.npz')):
            d = np.load(npz, allow_pickle=True)
            ph, pv, nx = str(d['phoneme']), str(d['prev']), str(d['next'])
            if ph not in self.phonemes or pv not in self.phonemes or nx not in self.phonemes:
                continue
            mel = d['mel'].astype(np.float32)
            if mel.shape[1] < 2:
                continue
            cm = d['cons_mask'].astype(np.float32) if 'cons_mask' in d.files else None
            if cm is not None and cm.shape[0] != mel.shape[1]:
                cm = None
            if cm is None:
                cm = np.zeros(mel.shape[1], dtype=np.float32)
            f0 = d['f0'].astype(np.float32) if 'f0' in d.files else np.zeros(mel.shape[1], dtype=np.float32)
            if f0.shape[0] != mel.shape[1]:
                f0 = np.zeros(mel.shape[1], dtype=np.float32)
            en = d['energy'].astype(np.float32) if 'energy' in d.files else np.zeros(mel.shape[1], dtype=np.float32)
            if en.shape[0] != mel.shape[1]:
                en = np.zeros(mel.shape[1], dtype=np.float32)
            self.samples.append((self.phonemes[pv], self.phonemes[ph],
                                 self.phonemes[nx], mel, cm, f0, en))

        print(f'[dataset] samples: {len(self.samples)} (sequences)')

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        pv, ph, nx, mel, cm, f0, en = self.samples[idx]
        T = mel.shape[1]

        # 时长增强：0.15×~1.5×（覆盖渲染短音符）
        if self.augment and self.time_aug and T > 2:
            lo, hi = self.time_range
            scale = float(np.random.uniform(lo, hi))
            T2 = max(2, int(T * scale))
            if T2 != T:
                mel = _interp_time(mel, T2)
                cm = np.round(_interp_time(cm[None, :], T2)[0])
                f0 = _interp_time(f0[None, :], T2)[0]
                en = _interp_time(en[None, :], T2)[0]
                T = T2

        pos = np.linspace(0, 1, T).astype(np.float32)
        mel_t = mel.T.copy()  # [T, 128]
        if self.augment and self.noise_std > 0:
            mel_t = mel_t + np.random.normal(0, self.noise_std, mel_t.shape)
        return (np.int64(pv), np.int64(ph), np.int64(nx),
                pos, mel_t.astype(np.float32), cm.astype(np.float32),
                f0.astype(np.float32), en.astype(np.float32))


def collate_frames(batch):
    """动态 pad 到 batch 最大长度，返回 (pv, ph, nx, pos, mel, cm, f0, energy, mask)"""
    import torch
    maxT = max(b[3].shape[0] for b in batch)
    n = len(batch)
    pv = torch.zeros((n, maxT), dtype=torch.long)
    ph = torch.zeros((n, maxT), dtype=torch.long)
    nx = torch.zeros((n, maxT), dtype=torch.long)
    pos = torch.zeros((n, maxT), dtype=torch.float32)
    mel = torch.zeros((n, maxT, batch[0][4].shape[1]), dtype=torch.float32)
    cm = torch.zeros((n, maxT), dtype=torch.float32)
    f0 = torch.zeros((n, maxT), dtype=torch.float32)
    en = torch.zeros((n, maxT), dtype=torch.float32)
    mask = torch.zeros((n, maxT), dtype=torch.bool)
    for i, b in enumerate(batch):
        T = b[3].shape[0]
        pv[i, :T] = b[0]; ph[i, :T] = b[1]; nx[i, :T] = b[2]
        pos[i, :T] = torch.from_numpy(b[3])
        mel[i, :T] = torch.from_numpy(b[4])
        cm[i, :T] = torch.from_numpy(b[5])
        f0[i, :T] = torch.from_numpy(b[6])
        en[i, :T] = torch.from_numpy(b[7])
        mask[i, :T] = True
    return pv, ph, nx, pos, mel, cm, f0, en, mask
