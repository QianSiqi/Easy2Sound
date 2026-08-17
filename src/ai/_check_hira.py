import numpy as np
import soundfile as sf
from pathlib import Path

d = Path(r'E:\bc\Easy2Sound\src\teto_hira')
wavs = sorted(d.glob('*.wav'))
print(f'teto_hira: {len(wavs)} wav files')

def analyze(path):
    w, sr = sf.read(str(path), dtype='float32')
    if w.ndim > 1:
        w = w.mean(axis=1)
    dur = len(w) / sr
    # 整体统计 + 分段（前半=可能辅音+起音，后半=元音稳定）
    half = len(w) // 3
    def seg_stats(a, b):
        s = w[a:b]
        if len(s) < 4:
            return (0, 0, 0)
        rms = np.sqrt((s**2).mean())
        zcr = np.mean(np.abs(np.diff(np.sign(s)))) / 2
        spec = np.abs(np.fft.rfft(s * np.hanning(len(s))))
        freqs = np.fft.rfftfreq(len(s), 1/sr)
        hi = spec[freqs > 5000].sum() / (spec.sum() + 1e-9)
        return (rms, zcr, hi)
    s0 = seg_stats(0, half)            # 起音段（可能含辅音）
    s1 = seg_stats(half, 2*half)       # 中间
    s2 = seg_stats(2*half, len(w))     # 尾段（元音稳定）
    return dur, s0, s1, s2

print(f'{"file":12s} {"dur":>5s} {"起音rms":>7s} {"起音zcr":>7s} {"起音hi%":>7s} {"尾段rms":>7s} {"尾段hi%":>6s}')
for p in wavs[:20]:
    dur, s0, s1, s2 = analyze(p)
    print(f'{p.stem:12s} {dur:5.2f} {s0[0]:7.3f} {s0[1]:7.3f} {s0[2]*100:6.1f}% {s2[0]:7.3f} {s2[2]*100:5.1f}%')
