# -*- coding: utf-8 -*-
"""
vocoder.py — NSF-HiFiGAN 声码器封装
====================================
复用 server_onnx.py 的推理逻辑：
  输入 mel [1, T, n_mels] + f0 [1, T]  →  输出 wav [1, samples]
模型: pc_nsf_hifigan_44.1k_hop512_128bin_2025.02/model.onnx
"""

import sys
from pathlib import Path

import numpy as np

AI_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AI_DIR))

import yaml


class Vocoder:
    def __init__(self, model_path: Path = None):
        import onnxruntime as ort
        if model_path is None:
            cfg = yaml.safe_load((AI_DIR / 'config.yaml').read_text(encoding='utf-8'))
            model_path = (AI_DIR / cfg['vocoder']['path']).resolve()
        if not model_path.exists():
            raise FileNotFoundError(f'vocoder model not found: {model_path}')
        providers = ['DmlExecutionProvider', 'CPUExecutionProvider']
        try:
            self.session = ort.InferenceSession(str(model_path), providers=providers)
        except Exception:
            # DirectML 不可用则纯 CPU
            self.session = ort.InferenceSession(str(model_path), providers=['CPUExecutionProvider'])
        self.sample_rate = 44100

    def synth(self, mel: np.ndarray, f0: np.ndarray) -> np.ndarray:
        """mel: [n_mels, T]（未压缩或已压缩均可由调用方决定），f0: [T] Hz
        返回: wav [N] float32
        """
        mel_in = np.expand_dims(mel.astype(np.float32), axis=0).transpose(0, 2, 1)  # [1,T,128]
        f0_in = np.expand_dims(f0.astype(np.float32), axis=0)                        # [1,T]
        out = self.session.run(['waveform'], {'mel': mel_in, 'f0': f0_in})[0]
        return out[0].astype(np.float32)
