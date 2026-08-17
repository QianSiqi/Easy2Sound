import numpy as np
import soundfile as sf

# 直接分析原始 VCV wav：辅音段 vs 元音段的波形特征
w, sr = sf.read(r'E:\bc\Easy2Sound\src\teto_roma_vcv\a_bi_bu_be_bo_.wav', dtype='float32')
print(f'wav: {len(w)/sr:.2f}s sr={sr}')

# phones 层：a | b | i | b | u | b | e | b | o | SP
# 辅音段（b 在 0.669-0.727, 1.308-1.368...）vs 元音段
def stats(t0, t1, label):
    seg = w[int(t0*sr):int(t1*sr)]
    if len(seg) < 2:
        return
    rms = np.sqrt((seg**2).mean())
    # 过零率（噪声/摩擦特征）
    zcr = np.mean(np.abs(np.diff(np.sign(seg)))) / 2
    # 高频占比（>5kHz 能量）
    spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
    freqs = np.fft.rfftfreq(len(seg), 1/sr)
    hi = spec[freqs > 5000].sum() / (spec.sum() + 1e-9)
    print(f'{label:12s} rms={rms:.4f}  zcr={zcr:.3f}  高频占比={hi*100:.1f}%')

stats(0.60, 0.669, '元音a(前)')
stats(0.669, 0.727, '辅音b(1)')
stats(0.727, 1.308, '元音i')
stats(1.308, 1.368, '辅音b(2)')
stats(1.368, 1.956, '元音u')
stats(2.0, 2.6, '元音e区')
