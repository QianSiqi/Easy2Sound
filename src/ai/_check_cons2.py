import numpy as np
from pathlib import Path

# teto_roma（旧单音素数据）的辅音强度
samples_dir = Path(r'E:\bc\Easy2Sound\src\ai\data_cache\teto_roma\samples')
sr, hop = 44100, 512
frames_per_s = sr / hop

print('=== teto_roma（孤立音素）辅音段特征 ===')
hi_list, lo_list = [], []
shown = 0
for p in sorted(samples_dir.glob('*.npz')):
    d = np.load(p, allow_pickle=True)
    sp = d['sub_phones']
    ph = str(d['phoneme'])
    if len(sp) < 1:
        continue
    mel = d['mel']; T = mel.shape[1]
    cs, ce = float(sp[0][0]), float(sp[0][1])
    cf0 = int(round(cs*frames_per_s)); cf1 = min(T, int(round(ce*frames_per_s)))
    cons = mel[:, cf0:cf1]
    vowel = mel[:, cf1:]
    if cons.shape[1] < 1 or vowel.shape[1] < 1:
        continue
    hi_list.append((cons[85:].mean(), vowel[85:].mean()))
    lo_list.append((cons[:40].mean(), vowel[:40].mean()))
    if shown < 6:
        print(f'{ph:4s} cons[{cf0}:{cf1}]len={cf1-cf0:2d} '
              f'辅音(hi={cons[85:].mean():.1f}) 元音(hi={vowel[85:].mean():.1f})')
        shown += 1

a = np.array(hi_list); c = np.array(lo_list)
print(f'\n=== 统计（{len(a)} 样本）===')
print(f'辅音段高频: {a[:,0].mean():.2f}  元音段高频: {a[:,1].mean():.2f}  差: {a[:,0].mean()-a[:,1].mean():+.2f}')
print(f'辅音段低频: {c[:,0].mean():.2f}  元音段低频: {c[:,1].mean():.2f}')
