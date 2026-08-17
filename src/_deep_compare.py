# -*- coding: utf-8 -*-
"""彻底对比：传统 test_Track1.wav vs AI out.wav
对比 f0 轨迹、频谱包络、谐波结构、mel 值域"""
import numpy as np
import soundfile as sf
import sys
sys.path.insert(0, r'E:\bc\Easy2Sound\src')

def load(path):
    w, sr = sf.read(path)
    if w.ndim > 1:
        w = w.mean(axis=1)
    return w, sr

w1, sr = load(r'E:\bc\Easy2Sound\src\tmp\test_Track1.wav')
w2, _ = load(r'E:\bc\Easy2Sound\src\tmp\out.wav')
print(f'traditional: {len(w1)/sr:.2f}s   AI: {len(w2)/sr:.2f}s')

n_fft, hop = 2048, 512

# ── 1. f0 轨迹对比（pyin）──
def extract_f0(w):
    import librosa
    f0, voiced, _ = librosa.pyin(w, sr=sr, fmin=60, fmax=800,
                                 frame_length=2048, hop_length=hop)
    f0[np.isnan(f0)] = 0
    return f0

f1 = extract_f0(w1)
f2 = extract_f0(w2)
def to_midi(f):
    f = f[f > 0]
    return 69 + 12*np.log2(f/440.0) if len(f) else []

m1, m2 = np.array(to_midi(f1)), np.array(to_midi(f2))
print(f'\n[1. f0] 传统: voiced={len(m1)}帧 midi mean={m1.mean():.1f} std={m1.std():.1f} range=[{m1.min():.0f},{m1.max():.0f}]')
print(f'[1. f0] AI:   voiced={len(m2)}帧 midi mean={m2.mean():.1f} std={m2.std():.1f} range=[{m2.min():.0f},{m2.max():.0f}]')
# f0 帧间跳变（音符边界的音高跳）
d1 = np.abs(np.diff(m1)); d2 = np.abs(np.diff(m2))
print(f'[1. f0] 传统 midi 跳变: mean={d1.mean():.2f} max={d1.max():.1f}')
print(f'[1. f0] AI   midi 跳变: mean={d2.mean():.2f} max={d2.max():.1f}')

# ── 2. 频谱包络对比 ──
def spectrogram(w):
    frames = 1 + (len(w) - n_fft) // hop
    s = np.zeros((n_fft//2+1, frames))
    for i in range(frames):
        seg = w[i*hop:i*hop+n_fft]
        if len(seg) < n_fft:
            seg = np.pad(seg, (0, n_fft-len(seg)))
        s[:, i] = np.abs(np.fft.rfft(seg * np.hanning(n_fft)))
    return s

S1, S2 = spectrogram(w1), spectrogram(w2)
freqs = np.fft.rfftfreq(n_fft, 1/sr)

# 平均谱（log 域）对比
avg1 = np.log(S1.mean(axis=1) + 1e-9)
avg2 = np.log(S2.mean(axis=1) + 1e-9)
# 谐波峰检测（前 10 个峰的位置）
def peaks(avg):
    pk = []
    for i in range(1, len(avg)-1):
        if avg[i] > avg[i-1] and avg[i] > avg[i+1] and avg[i] > avg.mean() + 1:
            pk.append(freqs[i])
    return pk[:10]
p1, p2 = peaks(avg1), peaks(avg2)
print(f'\n[2. 频谱峰] 传统: {[f"{p/1000:.1f}k" for p in p1]}')
print(f'[2. 频谱峰] AI:   {[f"{p/1000:.1f}k" for p in p2]}')

# ── 3. 频带能量 + 平坦度 ──
def feats(S, label):
    flat = np.exp(np.log(S+1e-9).mean(axis=0)) / (S.mean(axis=0)+1e-9)
    bands = {'<1k': freqs<1000, '1-4k': (freqs>=1000)&(freqs<4000),
             '4-8k': (freqs>=4000)&(freqs<8000), '>8k': freqs>=8000}
    e = {k: S[m].sum()/S.sum()*100 for k, m in bands.items()}
    print(f'[{label}] 平坦度={flat.mean():.3f}  频带: ' +
          ' '.join(f'{k}={v:.1f}%' for k, v in e.items()))
feats(S1, '3.传统')
feats(S2, '3.AI')
