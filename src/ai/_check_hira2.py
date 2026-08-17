import numpy as np, soundfile as sf
for name in ["_きゃ", "_し", "_た", "_か", "_ぱ"]:
    try:
        w, sr = sf.read(rf"E:\bc\Easy2Sound\src\teto_hira\{name}.wav", dtype="float32")
        if w.ndim > 1: w = w.mean(axis=1)
        n = len(w); q = n//4
        s = w[q:q+int(0.08*sr)]  # 起音后 80ms（辅音区）
        if len(s) < 4: s = w[:int(0.08*sr)]
        rms = np.sqrt((s**2).mean())
        zcr = np.mean(np.abs(np.diff(np.sign(s))))/2
        spec = np.abs(np.fft.rfft(s*np.hanning(len(s))))
        freqs = np.fft.rfftfreq(len(s), 1/sr)
        hi = spec[freqs>5000].sum()/(spec.sum()+1e-9)
        print(f"{name}: dur={len(w)/sr:.2f}s 辅音区 rms={rms:.3f} zcr={zcr:.3f} hi={hi*100:.1f}%")
    except Exception as e:
        print(f"{name}: ERR {e}")
