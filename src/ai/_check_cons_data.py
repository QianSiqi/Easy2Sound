import numpy as np
from pathlib import Path

samples_dir = Path(r'E:\bc\Easy2Sound\src\ai\data_cache\teto_roma_vcv\samples')
all_npz = sorted(samples_dir.glob('*.npz'))
sr, hop = 44100, 512
frames_per_s = sr / hop

shown = 0
cons_hi_list, cons_lo_list, vow_hi_list, vow_lo_list = [], [], [], []
for p in all_npz:
    d = np.load(p, allow_pickle=True)
    sp = d['sub_phones']
    ph = str(d['phoneme'])
    if len(sp) < 1:
        continue
    mel = d['mel']
    T = mel.shape[1]
    cs, ce = float(sp[0][0]), float(sp[0][1])
    cf0 = int(round(cs * frames_per_s)); cf1 = int(round(ce * frames_per_s))
    cf1 = min(cf1, T)
    cons = mel[:, cf0:cf1]
    vowel = mel[:, cf1:]
    if cons.shape[1] < 1 or vowel.shape[1] < 1:
        continue
    cons_hi_list.append(cons[85:].mean())
    cons_lo_list.append(cons[:40].mean())
    vow_hi_list.append(vowel[85:].mean())
    vow_lo_list.append(vowel[:40].mean())
    if shown < 8:
        print(f'{ph:4s} melT={T:3d} cons[{cf0}:{cf1}]len={cf1-cf0:2d} '
              f'辅音(hi={cons[85:].mean():.1f}, lo={cons[:40].mean():.1f}) '
              f'元音(hi={vowel[85:].mean():.1f}, lo={vowel[:40].mean():.1f})')
        shown += 1

import numpy as np
a = np.array(cons_hi_list); b = np.array(vow_hi_list)
c = np.array(cons_lo_list); dd = np.array(vow_lo_list)
print(f'\n=== 统计（{len(a)} 样本）===')
print(f'辅音段 高频均值: {a.mean():.2f}  元音段 高频均值: {b.mean():.2f}  差: {a.mean()-b.mean():+.2f}')
print(f'辅音段 低频均值: {c.mean():.2f}  元音段 低频均值: {dd.mean():.2f}')
print(f'→ 辅音段高频比元音 {a.mean()/b.mean():.2f} 倍' if b.mean() > 0 else '')
