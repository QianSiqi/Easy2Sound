# -*- coding: utf-8 -*-
"""对比：传统渲染 wav 的 log-mel 分布 vs 我们模型输出的 mel 分布"""
import sys
sys.path.insert(0, r'E:\bc\Easy2Sound\src\ai')
sys.path.insert(0, r'E:\bc\Easy2Sound\src')
import numpy as np
import soundfile as sf
from util.wav2mel_numpy import PitchAdjustableMelSpectrogramNumpy

mel_spec = PitchAdjustableMelSpectrogramNumpy(
    sample_rate=44100, n_fft=2048, win_length=2048, hop_length=512,
    f_min=40, f_max=16000, n_mels=128)

def dist(m, label):
    print(f'{label}: min={m.min():.2f} max={m.max():.2f} mean={m.mean():.2f} '
          f'p1={np.percentile(m,1):.2f} p10={np.percentile(m,10):.2f} '
          f'p50={np.percentile(m,50):.2f} p90={np.percentile(m,90):.2f}')

# 1. 传统渲染 wav → log-mel
w, sr = sf.read(r'E:\bc\Easy2Sound\src\tmp\test_Track1.wav', dtype='float32')
if w.ndim > 1: w = w.mean(axis=1)
m1 = mel_spec.dynamic_range_compression(mel_spec(w))
dist(m1, '传统渲染 log-mel')

# 2. AI 渲染 wav → log-mel（同一个 vocoder 输出，但输入是我们模型）
w2, _ = sf.read(r'E:\bc\Easy2Sound\src\tmp\out.wav', dtype='float32')
if w2.ndim > 1: w2 = w2.mean(axis=1)
m2 = mel_spec.dynamic_range_compression(mel_spec(w2))
dist(m2, 'AI 渲染 wav 回提 log-mel')

# 3. 训练数据（teto_hira 样本）log-mel
d = np.load(r'E:\bc\Easy2Sound\src\ai\data_cache\teto_hira\samples\00000.npz')
dist(d['mel'], 'teto_hira 样本 mel')
