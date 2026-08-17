# -*- coding: utf-8 -*-
"""实验 A：从传统渲染 wav 提取 log-mel → 喂我们的 vocoder → 输出
验证：vocoder 调用方式是否正确（应该有人声）"""
import sys
sys.path.insert(0, r'E:\bc\Easy2Sound\src\ai')
sys.path.insert(0, r'E:\bc\Easy2Sound\src')
import numpy as np
import soundfile as sf
from util.wav2mel_numpy import PitchAdjustableMelSpectrogramNumpy
from models.vocoder import Vocoder
import librosa

mel_spec = PitchAdjustableMelSpectrogramNumpy(
    sample_rate=44100, n_fft=2048, win_length=2048, hop_length=512,
    f_min=40, f_max=16000, n_mels=128)

# 传统渲染 wav（应含人声）
w, sr = sf.read(r'E:\bc\Easy2Sound\src\tmp\test_Track1.wav', dtype='float32')
if w.ndim > 1:
    w = w.mean(axis=1)
print(f'test_Track1: {len(w)/sr:.2f}s')

# 取中段 5 秒
t0 = int(10 * sr); t1 = int(15 * sr)
seg = w[t0:t1]

# 1. 提取 log-mel
mel = mel_spec(seg)
mel = mel_spec.dynamic_range_compression(mel)
print(f'mel: {mel.shape} range [{mel.min():.2f}, {mel.max():.2f}]')

# 2. 提取 f0（pyin，与 mel 帧对齐）
f0, voiced, _ = librosa.pyin(seg, sr=sr, fmin=60, fmax=800,
                             frame_length=2048, hop_length=512)
f0 = np.nan_to_num(f0, nan=0.0).astype(np.float32)
if len(f0) != mel.shape[1]:
    f0 = np.interp(np.linspace(0, 1, mel.shape[1]), np.linspace(0, 1, len(f0)), f0)
print(f'f0: nonzero {int((f0>0).sum())}/{len(f0)}, mean={f0[f0>0].mean():.0f}Hz')

# 3. vocoder 重合成
v = Vocoder()
out = v.synth(mel, f0)
sf.write(r'E:\bc\Easy2Sound\src\tmp\_expA.wav', out, sr)
print(f'\nexpA.wav written: {len(out)/sr:.2f}s')

# 4. 回提检查
m2 = mel_spec(out)
m2 = mel_spec.dynamic_range_compression(m2)
print(f'expA 回提 mel: range [{m2.min():.2f}, {m2.max():.2f}]')
