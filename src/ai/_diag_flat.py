# -*- coding: utf-8 -*-
"""诊断：模型输出的 mel 是否有频谱形状（通道间 std）？还是平面 mel？"""
import sys
sys.path.insert(0, r'E:\bc\Easy2Sound\src\ai')
from render.renderer import Renderer
import numpy as np

r = Renderer(mode='neural', device='cuda', singer=r'E:\bc\Easy2Sound\src\teto_roma_vcv')

# 生成 ka 的 mel（经 _build_mel 全流程）
notes = [{'pitch': 60, 'start_ms': 0, 'length_ms': 178, 'phoneme': 'ka'}]
segs = r._plan_segments(notes, 135)
fpm = r.sr / r.hop / 1000.0
ph_frames = [max(1, int(round(s['dur_ms'] * fpm))) for s in segs]
T_ph = sum(ph_frames)
from models.f0 import gen_f0
frame_segs = [{'start_frame': 0, 'end_frame': T_ph, 'pitch': 60, 'transpose': 0,
               'pitchbend': None, 'vib': None, 'start_ms': 0, 'dur_ms': 178}]
f0_ph = gen_f0(frame_segs, T_ph, r.sr, r.hop)
mel, ranges = r._build_mel(segs, f0_ph)
print(f'mel shape: {mel.shape}')

# 1. 通道间 std（频谱形状指标）
ch_std = mel.std(axis=0)  # 每帧的通道 std
print(f'\n[通道 std] mean={ch_std.mean():.3f}  min={ch_std.min():.3f}  max={ch_std.max():.3f}')
print('  → 真实歌声 mel 通道 std 通常 >2（有共振峰结构）；<0.5 = 平面 mel（正弦波来源）')

# 2. 频谱形状（第一帧）
f0_frame = mel[:, 0]
print(f'\n[第0帧频谱] 128通道:')
print('  低频(0-40):', np.round(f0_frame[:40], 1).tolist())
print('  中频(40-80):', np.round(f0_frame[40:80], 1).tolist())
print('  高频(80-127):', np.round(f0_frame[80:], 1).tolist())

# 3. 模板对比
tpl = r.templates.get('ka', r.templates.get('a'))
if tpl is not None:
    t_std = tpl.std(axis=0)
    print(f'\n[模板通道 std] mean={t_std.mean():.3f}')

# 4. 直接模型输出（拉伸前）
if r.acoustic is not None:
    pad = r.phonemes.get('#', 0)
    raw = r.acoustic.generate_mel(pad, r.phonemes['ka'], pad, 15, f0_ph[:15], r.device)
    print(f'\n[模型原始输出] range=[{raw.min():.2f}, {raw.max():.2f}] 通道std mean={raw.std(axis=0).mean():.3f}')
