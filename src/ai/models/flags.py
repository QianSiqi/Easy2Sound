# -*- coding: utf-8 -*-
"""
flags.py — UTAU 风格 flags 解析与应用
======================================
对齐 server_onnx_rs / server.py 的 flag 体系（fe/fl/fo/fv/fp/ve/vo/g/t/A/B/G/P/S/p/R/D/C/Z/Hv/Hb/Ht/He）。

AI 合成中已实现的 flag：
  t   transpose    整体移调（半音）          → f0 偏移
  g   gender       性别（共振峰偏移，半音）   → mel 频率轴重采样
  A   accent       重音（音高变化速率）       → 增益调制
  Hv/Hb/Ht         呼吸/发声/紧张（需 HN-SEP）→ 暂不支持（忽略）
  其余 flags       暂未映射（忽略，不报错）

用法:
    from models.flags import parse_flags, apply_gender
    flags = parse_flags('B0Y60C30t12g-20')
    transpose_semi = flags.get('t', 0) / 100.0
"""

import numpy as np

FLAG_LIST = ['fe', 'fl', 'fo', 'fv', 'fp', 've', 'vo', 'g', 't',
             'A', 'B', 'G', 'P', 'S', 'p', 'R', 'D', 'C', 'Z',
             'Hv', 'Hb', 'Ht', 'He']


def parse_flags(s: str):
    """解析 flags 字符串 → {flag_name: int}，无值的 flag 记为 0"""
    s = (s or '').replace('/', '')
    flags = {}
    i = 0
    while i < len(s):
        matched = None
        for name in FLAG_LIST:
            if s.startswith(name, i):
                matched = name
                break
        if matched is None:
            i += 1
            continue
        i += len(matched)
        # 解析可选数值（支持 +/- 前缀）
        j = i
        if j < len(s) and (s[j] in '+-' or s[j].isdigit()):
            while j < len(s) and (s[j].isdigit() or (j == i and s[j] in '+-')):
                j += 1
        flags[matched] = int(s[i:j]) if j > i else 0
        i = j
    return flags


def apply_gender(mel: np.ndarray, g_semitones: float) -> np.ndarray:
    """gender flag：按半音偏移重采样 mel 频率轴（共振峰偏移，实现变声）。
    mel: [n_mels, T]（log 域）
    g_semitones: 半音数（UTAU g 值/100），正=偏男性（频率下移），负=偏女性
    """
    if g_semitones == 0:
        return mel
    n_mels, T = mel.shape
    # 频率轴按因子缩放（共振峰位置变化）
    factor = 2 ** (g_semitones / 12.0)
    # 目标 mel 通道对应源通道位置
    src_idx = np.arange(n_mels) / factor
    src_idx = np.clip(src_idx, 0, n_mels - 1)
    # 对每个时间帧做通道插值
    from scipy.interpolate import interp1d
    out = np.empty_like(mel)
    x = np.arange(n_mels)
    for t in range(T):
        out[:, t] = np.interp(src_idx, x, mel[:, t])
    return out
