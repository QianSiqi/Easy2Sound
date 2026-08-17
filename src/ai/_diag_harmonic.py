# -*- coding: utf-8 -*-
"""对比 neural vs template 生成 mel 的谐波结构"""
import sys
sys.path.insert(0, r'E:\bc\Easy2Sound\src\ai')
from render.renderer import Renderer
from models.f0 import gen_f0
import numpy as np

def build(singer, mode):
    r = Renderer(mode=mode, device='cuda', singer=singer)
    notes = [{'pitch': 60, 'start_ms': 0, 'length_ms': 500, 'phoneme': 'ka'},
             {'pitch': 62, 'start_ms': 500, 'length_ms': 500, 'phoneme': 'o'}]
    segs = r._plan_segments(notes, 135)
    fpm = r.sr / r.hop / 1000.0
    ph_frames = [max(1, int(round(s['dur_ms'] * fpm))) for s in segs]
    T = sum(ph_frames)
    frame_segs = []
    acc = 0
    for s, tf in zip(segs, ph_frames):
        frame_segs.append({'start_frame': acc, 'end_frame': acc+tf, 'pitch': s['pitch'],
                           'transpose': 0, 'pitchbend': None, 'vib': None,
                           'start_ms': s['start_ms'], 'dur_ms': s['dur_ms']})
        acc += tf
    f0 = gen_f0(frame_segs, T, r.sr, r.hop)
    mel, _ = r._build_mel(segs, f0)
    mel = r._postprocess_mel(mel)
    return r, mel, f0

for mode in ['template', 'neural']:
    r, mel, f0 = build(r'E:\bc\Easy2Sound\src\teto_roma_vcv', mode)
    # 取第二个音符（o，元音稳定段）中段
    T = mel.shape[1]
    mid = T // 2
    frame = mel[:, mid]
    ch_std = mel.std(axis=0)
    print(f'=== {mode} ===')
    print(f'mel: {mel.shape} 通道std mean={ch_std.mean():.2f} 帧范围[{mel.min():.2f},{mel.max():.2f}]')
    # 谐波峰检测：mel 通道 5-60（对应 100-2000Hz 左右）找峰
    peaks = []
    for i in range(6, 60):
        if frame[i] > frame[i-1] and frame[i] > frame[i+1] and frame[i] > frame.mean():
            peaks.append((i, round(float(frame[i]), 2)))
    print(f'  第{mid}帧 频谱峰(通道,值): {peaks[:12]}')
    print(f'  f0@{mid}帧: {f0[mid]:.0f}Hz')
    # 帧间变化
    d = np.linalg.norm(mel[:, 1:] - mel[:, :-1], axis=0)
    print(f'  帧间L2: mean={d.mean():.2f}')
    print()
