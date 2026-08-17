# -*- coding: utf-8 -*-
"""
acoustic.py — 声学模型：上下文 GRU 序列生成器（f0 条件）
==========================================================
参考 DiffSinger：声学模型以 f0 为输入生成 mel，保证 mel 谐波结构与
vocoder 的 f0 激励匹配（否则 vocoder 输出"纯正弦+电音"）。

输入:  (前音素, 当前音素, 后音素, 帧位置, 帧 f0)  →  整段 mel [T, n_mels]
"""

import numpy as np
import torch
import torch.nn as nn


def f0_to_norm(f0_hz):
    """f0 (Hz) → 归一化输入值（半音相对 A4）。静音 f0<=0 → 低值标记。"""
    f0 = np.clip(np.asarray(f0_hz, dtype=np.float32), 1.0, 4000.0)
    return np.log2(f0 / 440.0)  # 约 [-8.8, 3.2]


class SequenceAcousticModel(nn.Module):
    def __init__(self, n_phonemes: int, phoneme_dim: int = 64,
                 hidden_dim: int = 256, n_mels: int = 128, layers: int = 2):
        super().__init__()
        self.phoneme_dim = phoneme_dim
        self.n_mels = n_mels
        self.emb = nn.Embedding(n_phonemes, phoneme_dim)
        in_dim = phoneme_dim * 3 + 3  # prev + curr + next + pos + f0 + energy
        self.gru = nn.GRU(in_dim, hidden_dim, num_layers=layers, batch_first=True,
                          dropout=0.1 if layers > 1 else 0.0)
        self.proj = nn.Linear(hidden_dim, n_mels)

    def forward(self, prev_idx, curr_idx, next_idx, pos_norm, f0_norm, energy_norm):
        """
        prev/curr/next_idx: [B, T] long
        pos_norm: [B, T] float（帧位置 0..1）
        f0_norm: [B, T] float（帧 f0 归一化）
        energy_norm: [B, T] float（帧能量包络）
        Returns: [B, T, n_mels]
        """
        e = torch.cat([self.emb(prev_idx), self.emb(curr_idx),
                       self.emb(next_idx), pos_norm.unsqueeze(-1),
                       f0_norm.unsqueeze(-1), energy_norm.unsqueeze(-1)], dim=-1)
        out, _ = self.gru(e)
        return self.proj(out)

    def generate_mel(self, prev_idx: int, curr_idx: int, next_idx: int,
                     n_frames: int, f0_hz: np.ndarray, device='cpu',
                     energy: np.ndarray = None):
        """推理：给定上下文音素、目标帧数、f0 曲线和能量包络，整段生成 mel [n_mels, T]"""
        self.eval()
        B, T = 1, n_frames
        pv = torch.full((B, T), prev_idx, dtype=torch.long, device=device)
        cu = torch.full((B, T), curr_idx, dtype=torch.long, device=device)
        nx = torch.full((B, T), next_idx, dtype=torch.long, device=device)
        pos = torch.linspace(0, 1, T, device=device).unsqueeze(0)
        f0 = torch.from_numpy(f0_to_norm(f0_hz)).to(device).unsqueeze(0)  # [1, T]
        if f0.shape[1] != T:
            f0 = torch.nn.functional.interpolate(
                f0.view(1, 1, -1), size=T, mode='linear').view(1, T)
        if energy is None:
            energy = np.ones(T, dtype=np.float32)
        en = torch.from_numpy(np.asarray(energy, dtype=np.float32)).to(device).unsqueeze(0)
        if en.shape[1] != T:
            en = torch.nn.functional.interpolate(
                en.view(1, 1, -1), size=T, mode='linear').view(1, T)
        with torch.no_grad():
            mel = self.forward(pv, cu, nx, pos, f0, en)   # [1, T, 128]
        return mel[0].T.cpu().numpy()                     # [128, T]
