# -*- coding: utf-8 -*-
"""
train_acoustic.py — 训练上下文 GRU 声学模型
============================================
整段训练：每样本 = 一个音素段的帧序列，masked 加权 L1（辅音帧权重高）。

用法:
    cd src/ai
    python train/train_acoustic.py --singer teto_roma_vcv --epochs 150
"""

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader

AI_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AI_DIR))

import yaml
from data.dataset import SequenceDataset, collate_frames
from models.acoustic import SequenceAcousticModel


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--epochs', type=int, default=150)
    ap.add_argument('--batch', type=int, default=64)
    ap.add_argument('--lr', type=float, default=1e-3)
    ap.add_argument('--cons', type=float, default=5.0, help='辅音帧 loss 权重')
    ap.add_argument('--device', default='cuda' if torch.cuda.is_available() else 'cpu')
    ap.add_argument('--singer', default='teto_roma_vcv')
    args = ap.parse_args()

    cfg = yaml.safe_load((AI_DIR / 'config.yaml').read_text(encoding='utf-8'))
    cache_dir = (AI_DIR / cfg['data']['cache_dir'] / args.singer).resolve()
    ckpt_dir = (AI_DIR / 'checkpoints' / args.singer).resolve()
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    phonemes = json.loads((cache_dir / 'phonemes.json').read_text(encoding='utf-8'))
    n_phonemes = len(phonemes)
    print(f'[INFO] singer={args.singer}, phonemes: {n_phonemes}, device: {args.device}')

    ds = SequenceDataset(cache_dir)
    dl = DataLoader(ds, batch_size=args.batch, shuffle=True, collate_fn=collate_frames,
                    num_workers=4, prefetch_factor=4)

    model = SequenceAcousticModel(
        n_phonemes=n_phonemes,
        phoneme_dim=cfg['model']['phoneme_dim'],
        hidden_dim=cfg['model']['hidden_dim'],
        n_mels=cfg['mel']['n_mels'],
    ).to(args.device)
    opt = torch.optim.Adam(model.parameters(), lr=args.lr)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=args.epochs)

    best_loss = float('inf')
    for epoch in range(args.epochs):
        model.train()
        t0 = time.time()
        tot, cnt = 0.0, 0
        for pv, ph, nx, pos, mel, cm, f0, en, mask in dl:
            pv, ph, nx, pos, mel, cm, f0, en, mask = (pv.to(args.device), ph.to(args.device),
                                                      nx.to(args.device), pos.to(args.device),
                                                      mel.to(args.device), cm.to(args.device),
                                                      f0.to(args.device), en.to(args.device),
                                                      mask.to(args.device))
            from models.acoustic import f0_to_norm
            f0_n = torch.from_numpy(f0_to_norm(f0.cpu().numpy())).to(args.device)
            pred = model(pv, ph, nx, pos, f0_n, en)      # [B, T, 128]
            # 加权 L1：辅音帧权重更高，迫使模型学好辅音
            w = 1.0 + (args.cons - 1.0) * cm
            diff = (pred - mel).abs().mean(dim=-1)        # [B, T]
            loss = (w * diff * mask).sum() / mask.sum()
            # 时间连续性损失（鼓励 mel 帧间平滑，抑制"忽大忽小"）
            if pred.shape[1] > 1:
                pred_d = (pred[:, 1:] - pred[:, :-1]).abs().mean(dim=-1)
                mel_d = (mel[:, 1:] - mel[:, :-1]).abs().mean(dim=-1)
                diff_d = (pred_d - mel_d).abs()
                m2 = mask[:, 1:] * mask[:, :-1]
                loss = loss + 0.2 * (diff_d * m2).sum() / m2.sum()
            opt.zero_grad()
            loss.backward()
            opt.step()
            tot += loss.item() * mask.sum().item()
            cnt += mask.sum().item()
        sched.step()
        avg = tot / max(1, cnt)
        if (epoch + 1) % 5 == 0 or avg < best_loss:
            print(f'[epoch {epoch:3d}] loss {avg:.4f}  ({time.time() - t0:.1f}s)')
        if avg < best_loss:
            best_loss = avg
            torch.save({'epoch': epoch, 'model': model.state_dict(),
                        'opt': opt.state_dict()}, ckpt_dir / 'acoustic.pt')

    print(f'[DONE] best loss {best_loss:.4f}, checkpoint: {ckpt_dir / "acoustic.pt"}')


if __name__ == '__main__':
    main()
