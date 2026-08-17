# -*- coding: utf-8 -*-
"""诊断 out.wav：有无谐波结构（人声）？电音特征？"""
import numpy as np
import soundfile as sf

w, sr = sf.read(r'E:\bc\Easy2Sound\src\tmp\out.wav')
if w.ndim > 1:
    w = w.mean(axis=1)
print(f'out.wav: {len(w)/sr:.2f}s  rms={np.sqrt((w**2).mean()):.4f}  peak={np.abs(w).max():.3f}')

# 取中段 2 秒分析
seg = w[len(w)//2:len(w)//2 + 2*sr]
n_fft, hop = 2048, 512
frames = 1 + (len(seg)-n_fft)//hop
spec = np.zeros((n_fft//2+1, frames))
for i in range(frames):
    s = seg[i*hop:i*hop+n_fft]
    if len(s) < n_fft: s = np.pad(s, (0, n_fft-len(s)))
    spec[:, i] = np.abs(np.fft.rfft(s * np.hanning(n_fft)))
freqs = np.fft.rfftfreq(n_fft, 1/sr)

avg = spec.mean(axis=1)
# 谐波结构检测：基频附近能量 vs 宽带
# 1. 频谱平坦度（噪声=高，谐波=低）
flat = np.exp(np.log(avg+1e-9).mean()) / (avg.mean()+1e-9)
# 2. 谐波比：总能量中 <1kHz（基频区）占比
lo = avg[freqs<1000].sum() / avg.sum()
# 3. 检测最强谐波峰（人声会有清晰峰）
peaks = []
for i in range(2, len(avg)-1):
    if avg[i] > avg[i-1] and avg[i] > avg[i+1]:
        peaks.append((freqs[i], avg[i]))
peaks.sort(key=lambda x: -x[1])
print(f'\n频谱平坦度: {flat:.3f} (人声<0.2, 噪声>0.5)')
print(f'<1kHz 能量占比: {lo*100:.1f}% (人声通常>40%)')
print(f'最强峰: {[(f"{f/1000:.1f}k", round(e,1)) for f,e in peaks[:8]]}')

# 频带分布
bands = {'<500': freqs<500, '0.5-2k': (freqs>=500)&(freqs<2000),
         '2-5k': (freqs>=2000)&(freqs<5000), '5-10k': (freqs>=5000)&(freqs<10000), '>10k': freqs>=10000}
print('频带能量:', {k: f'{spec[m].sum()/spec.sum()*100:.1f}%' for k,m in bands.items()})
