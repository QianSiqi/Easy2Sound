# -*- coding: utf-8 -*-
"""
f0.py — 音高曲线（f0）生成
============================
输入：乐谱音符 + 音高控制点（pt_x/pt_y 或 pitch_string）+ 颤音参数 + 移调
输出：逐帧 f0（Hz），与 mel 帧对齐（帧率 = sample_rate / hop_size）

音高曲线来源（优先级）：
  1. pt_x/pt_y 控制点（tick, cents）——webui 手绘音高曲线
  2. pitch_string（UTAU Base64 RLE pitchbend）
  3. 无 → 平直音高（乐谱音高）

颤音参数（webui 音符字段）：
  vib_start / vib_end（音符内起止毫秒）
  vib_hz（频率）、vib_hard（深度，半音；0 或缺失时关闭）
"""

import numpy as np


def midi_to_hz(midi) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12.0)


def ticks_to_ms(ticks: float, bpm: float) -> float:
    """125 * ticks / bpm（utaupy 同款，与 webui 一致）"""
    return 125.0 * ticks / bpm


def _decode_pitch_string(ps: str):
    """UTAU pitchbend（Base64 RLE）→ 半音偏移列表（每 5 ticks 一个采样）"""
    if not ps or len(ps) < 2:
        return []
    def u6(c):
        o = ord(c)
        if 97 <= o <= 122: return o - 71
        if 65 <= o <= 90: return o - 65
        if 48 <= o <= 57: return o + 4
        if o == 43: return 62
        if o == 47: return 63
        return 0
    pts = []
    i = 0
    while i < len(ps):
        if ps[i] == '#':
            j = ps.find('#', i + 1)
            if j == -1: break
            cnt = int(ps[i + 1:j]) if ps[i + 1:j] else 1
            last = pts[-1] if pts else 0
            pts.extend([last] * cnt)
            i = j + 1
        else:
            if i + 1 >= len(ps): break
            v = u6(ps[i]) * 64 + u6(ps[i + 1])
            if v >= 2048: v -= 4096
            pts.append(v)
            i += 2
    return pts


def build_pitchbend_curve(note, bpm: float):
    """把音符的音高曲线信息转成 (ms, 半音) 控制点列表。
    返回 None 表示无曲线。
    """
    pts = None
    # 1. pt_x/pt_y 控制点（优先）
    pt_x = note.get('pt_x', '') or ''
    pt_y = note.get('pt_y', '') or ''
    if pt_x and pt_y:
        try:
            xs = [float(v) for v in pt_x.split(',')]
            ys = [float(v) for v in pt_y.split(',')]
        except ValueError:
            xs, ys = [], []
        if len(xs) == len(ys) and len(xs) >= 2:
            pts = [(ticks_to_ms(x, bpm), y / 100.0) for x, y in zip(xs, ys)]  # cents→半音
    # 2. pitch_string（Base64 RLE，每 5 ticks 一采样）
    if pts is None:
        ps = note.get('pitch_string', '') or ''
        arr = _decode_pitch_string(ps)
        if len(arr) >= 2:
            pts = [(ticks_to_ms(i * 5, bpm), v / 100.0) for i, v in enumerate(arr)]
    return pts


def gen_f0(segments, total_frames: int, sr: int = 44100, hop: int = 512):
    """生成逐帧 f0（Hz）。

    segments: list[dict]，每段含
        - start_frame / end_frame
        - pitch: MIDI 音高
        - transpose: 移调半音（可选，默认 0）
        - pitchbend: [(ms, 半音), ...] 音高曲线控制点（可选）
        - vib: dict{vib_start_ms, vib_end_ms, vib_hz, vib_depth_semi}（可选）
    """
    f0 = np.zeros(total_frames, dtype=np.float32)
    frame_rate = sr / hop
    frame_ms = 1000.0 / frame_rate

    for seg in segments:
        s = max(0, int(seg['start_frame']))
        e = min(total_frames, int(seg['end_frame']))
        if e <= s:
            continue
        n = e - s
        base_semi = seg.get('pitch', 60) + seg.get('transpose', 0.0)
        base_hz = midi_to_hz(base_semi)
        frames = np.arange(n)
        t_ms = (frames + s) * frame_ms  # 绝对时间（ms）

        # 音高曲线（半音偏移，线性插值）
        bend = seg.get('pitchbend')
        cents = np.zeros(n, dtype=np.float32)
        if bend and len(bend) >= 2:
            ms = np.array([p[0] for p in bend])
            sem = np.array([p[1] for p in bend])
            # 控制点时间是相对音符起点的 ms → 转绝对 ms
            rel_ms = t_ms - seg.get('start_ms', 0.0)
            cents = np.interp(rel_ms, ms, sem)
        elif bend and len(bend) == 1:
            cents[:] = bend[0][1]

        # 颤音
        vib = seg.get('vib') or {}
        depth = float(vib.get('vib_depth_semi', 0) or 0)
        if depth > 0:
            vhz = float(vib.get('vib_hz', 5) or 5)
            v_start = float(vib.get('vib_start_ms', 0) or 0)
            v_end = float(vib.get('vib_end_ms', 0) or 0)
            if v_end <= 0 or v_end > seg.get('dur_ms', 1e9):
                v_end = seg.get('dur_ms', 1e9)
            mask = (t_ms >= v_start) & (t_ms <= v_end)
            # 淡入淡出（前后各 15% 渐变，避免颤音突然出现）
            ramp = np.ones(n, dtype=np.float32)
            ramp[mask] = np.sin(2 * np.pi * vhz * (t_ms[mask] - v_start) / 1000.0) * depth
            fade_len = max(1, int(0.15 * n))
            if fade_len < n:
                ramp[:fade_len] *= np.linspace(0, 1, fade_len)
                ramp[-fade_len:] *= np.linspace(1, 0, fade_len)
            cents += ramp * mask.astype(np.float32)

        f0[s:e] = base_hz * (2 ** (cents / 12.0))

    # 音符边界 f0 平滑（滑音过渡）：NSF-HiFiGAN 对 f0 硬跳变敏感（产生爆音/伪影）
    # 只在跳变处做短过渡，平台保持
    try:
        from scipy.ndimage import uniform_filter1d
        f0_s = uniform_filter1d(f0, size=5, mode='nearest')
        # 仅当局部变化显著时用平滑值（保留自然微颤）
        diff = np.abs(f0 - f0_s)
        mask = diff > 0.15 * np.maximum(f0, 1)  # >15% 跳变处用平滑
        f0[mask] = f0_s[mask]
    except Exception:
        pass

    return f0
