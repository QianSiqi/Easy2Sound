# -*- coding: utf-8 -*-
"""诊断 teto_hira 模型输出：mel 值域 + f0 正确性"""
import sys
sys.path.insert(0, r'E:\bc\Easy2Sound\src\ai')
from render.renderer import Renderer
from models.f0 import gen_f0
import numpy as np

r = Renderer(mode='neural', device='cuda', singer=r'E:\bc\Easy2Sound\src\teto_hira')

# 渲染 ka (C4=60, 178ms)
notes = [{'pitch': 60, 'start_ms': 0, 'length_ms': 178, 'phoneme': 'ka'}]
segs = r._plan_segments(notes, 135)
print('segments:', [(s['phoneme'], round(s['dur_ms'],1), s['pitch']) for s in segs])

mel = r._build_mel(segs)
print(f'\nmel shape: {mel.shape}')
print(f'mel value range: [{mel.min():.2f}, {mel.max():.2f}]  (正常 log mel 应为 [-20, 5])')
print(f'mel mean: {mel.mean():.2f}')

# f0
T = mel.shape[1]
frame_segs = [{'start_frame': 0, 'end_frame': T, 'pitch': segs[0]['pitch'],
               'transpose': 0, 'pitchbend': None, 'vib': None,
               'start_ms': 0, 'dur_ms': segs[0]['dur_ms']}]
f0 = gen_f0(frame_segs, T, r.sr, r.hop)
print(f'\nf0 shape: {f0.shape}, nonzero: {(f0>0).sum()}/{T}')
print(f'f0 value: {f0[f0>0][:5]} ... (C4=60 应≈261.6Hz)')

# 模板对比（该音素模板值域）
if 'ka' in r.templates:
    tpl = r.templates['ka']
    print(f'\ntemplate ka range: [{tpl.min():.2f}, {tpl.max():.2f}] mean {tpl.mean():.2f}')
else:
    print(f'\nno template for ka; phonemes has ka: {"ka" in r.phonemes}')
