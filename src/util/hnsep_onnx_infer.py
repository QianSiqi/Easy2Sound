"""
hnsep_onnx_infer.py — ONNX 版 HN-SEP 推理 + pre_emphasis_base_tension
完全不依赖 PyTorch，用 scipy.signal.stft/istft + onnxruntime 实现。
"""

import os
import logging
import numpy as np
from scipy import signal

try:
    import onnxruntime
except ImportError:
    onnxruntime = None


class HnsepOnnxDemo:
    """ONNX 版 HN-SEP 推理，接口与 torch CascadedNet.predict_fromaudio 一致。"""

    def __init__(self, onnx_path, config_path=None):
        if onnxruntime is None:
            raise ImportError("onnxruntime is required for HnsepOnnxDemo")

        # 先加载配置（predict_fromaudio 需要 n_fft 等参数）
        if config_path is None:
            config_path = os.path.join(os.path.dirname(onnx_path), 'config.yaml')
        self._load_config(config_path)

        # 选择 provider：尝试 DML > CUDA > CPU，DML 失败则回退
        available = onnxruntime.get_available_providers()
        provider_candidates = []
        if 'DmlExecutionProvider' in available:
            provider_candidates.append(['DmlExecutionProvider', 'CPUExecutionProvider'])
        if 'CUDAExecutionProvider' in available:
            provider_candidates.append(['CUDAExecutionProvider', 'CPUExecutionProvider'])
        provider_candidates.append(['CPUExecutionProvider'])

        self.session = None
        for prov_list in provider_candidates:
            try:
                self.session = onnxruntime.InferenceSession(onnx_path, providers=prov_list)
                # 验证：用 1 秒音频跑 dummy 推理
                import numpy as np
                dummy = np.random.randn(1, 1, 44100).astype(np.float32)
                self.predict_fromaudio(dummy)
                logging.info(f'Loaded hnsep ONNX: {onnx_path} using {self.session.get_providers()}')
                break
            except Exception as e:
                logging.warning(f'Provider {prov_list[0]} failed for hnsep: {e}, trying next...')
                self.session = None
                continue

        if self.session is None:
            raise RuntimeError(f'Failed to load hnsep ONNX with any provider: {onnx_path}')

    def _load_config(self, config_path):
        try:
            import yaml
            with open(config_path, 'r', encoding='utf-8') as f:
                cfg = yaml.safe_load(f) or {}
        except Exception:
            cfg = {}

        self.n_fft = cfg.get('n_fft', 2048)
        self.hop_length = cfg.get('hop_length', 512)
        self.sr = cfg.get('sr', 44100)
        self.seg_length = 32 * self.hop_length
        self.window = signal.windows.hann(self.n_fft, sym=False).astype(np.float32)
        self.offset = 64

    def _stft(self, x):
        """
        numpy STFT，与 torch.stft(n_fft, hop_length, center=True, return_complex=True) 对齐。
        使用原始 FFT（不做归一化），匹配 torch 的默认行为。
        torch center=True 会在信号两端各 pad n_fft//2 的 reflect padding。
        x: [T] 1D numpy array
        返回: [n_fft//2+1, n_frames] complex
        """
        n = self.n_fft
        hop = self.hop_length
        win = self.window

        # 模拟 torch center=True 的 reflect padding
        pad_size = n // 2
        x_padded = np.pad(x, (pad_size, pad_size), mode='reflect')

        # 手动 STFT：逐帧加窗 + FFT（与 torch 行为一致，不做额外归一化）
        n_frames = 1 + (len(x_padded) - n) // hop
        spec = np.zeros((n // 2 + 1, n_frames), dtype=np.complex64)
        for i in range(n_frames):
            start = i * hop
            frame = x_padded[start:start + n] * win
            spec[:, i] = np.fft.rfft(frame, n=n)
        return spec

    def _istft(self, spec):
        """
        numpy ISTFT，与 torch.istft(n_fft, hop_length, center=True) 对齐。
        使用原始 IFFT（不做归一化），匹配 torch 的默认行为。
        torch center=True 会在输出两端各 trim n_fft//2。
        spec: [n_fft//2+1, n_frames] complex
        返回: [T] 1D numpy array
        """
        n = self.n_fft
        hop = self.hop_length
        win = self.window
        n_frames = spec.shape[1]

        # 重建信号长度
        output_len = n + (n_frames - 1) * hop
        output = np.zeros(output_len, dtype=np.float64)
        win_sum = np.zeros(output_len, dtype=np.float64)

        for i in range(n_frames):
            start = i * hop
            frame = np.fft.irfft(spec[:, i], n=n)
            output[start:start + n] += frame * win
            win_sum[start:start + n] += win ** 2

        # 归一化（overlap-add 标准做法）
        win_sum = np.maximum(win_sum, 1e-8)
        output = output / win_sum

        # 模拟 torch center=True 的 trim
        pad_size = n // 2
        if len(output) > 2 * pad_size:
            output = output[pad_size:-pad_size]
        return output.astype(np.float32)

    def predict_fromaudio(self, wave):
        """
        与 CascadedNet.predict_fromaudio 接口一致。
        wave: np.ndarray, shape [1, 1, T]
        返回: np.ndarray, shape [1, 1, T]
        """
        B, C, T = wave.shape
        x = wave.reshape(B * C, T)  # [B*C, T]

        # padding to seg_length 的整数倍
        T1 = T + self.hop_length
        T_pad = self.seg_length * ((T1 - 1) // self.seg_length + 1) - T1
        nl_pad = T_pad // 2 // self.hop_length
        Tl_pad = nl_pad * self.hop_length
        Tr_pad = T_pad - Tl_pad
        x_padded = np.pad(x[0], (Tl_pad, Tr_pad), mode='constant')  # [T+T_pad]

        # STFT → [n_fft//2+1, n_frames] complex
        spec = self._stft(x_padded)
        n_bins, n_frames = spec.shape

        # reshape 为 ONNX 输入: [1, 2, n_bins, n_frames]（real/imag 拼接）
        real = spec.real.astype(np.float32)
        imag = spec.imag.astype(np.float32)
        onnx_input = np.stack([real, imag], axis=0)[np.newaxis, ...]  # [1, 2, n_bins, n_frames]

        # ONNX 推理 → mask [1, 2, n_bins, n_frames]
        mask_onnx = self.session.run(None, {'input': onnx_input})[0]

        # mask complex 化
        mask_real = mask_onnx[0, 0]  # [n_bins, n_frames]
        mask_imag = mask_onnx[0, 1]
        mask = mask_real + 1j * mask_imag  # complex mask

        # 应用 mask
        spec_pred = spec * mask

        # ISTFT → [T_padded]
        x_pred = self._istft(spec_pred)

        # 裁剪回原始长度
        x_pred = x_pred[Tl_pad: Tl_pad + T]

        return x_pred.reshape(B, C, T).astype(np.float32)


def pre_emphasis_base_tension(wave, b, config=None):
    """
    频域张力/呼吸滤波（numpy/scipy 版本）。
    与 torch 版 pre_emphasis_base_tension 接口一致。

    Args:
        wave: np.ndarray, shape [1, 1, T]
        b: float, 张力参数（-tension/50）
        config: 配置 dict，需包含 n_fft, hop_size, win_size, sample_rate
    Returns:
        np.ndarray, shape [1, 1, T]
    """
    if config is None:
        config = {}

    n_fft = config.get('n_fft', 2048)
    hop_size = config.get('hop_size', 512)
    win_size = config.get('win_size', 2048)
    sample_rate = config.get('sample_rate', 44100)

    original_length = wave.shape[-1]
    window = signal.windows.hann(win_size, sym=False).astype(np.float32)

    # pad 到 hop_size 整数倍
    pad_length = (hop_size - (original_length % hop_size)) % hop_size
    wave_padded = np.pad(wave[0, 0], (0, pad_length), mode='constant')

    # 模拟 torch center=True 的 reflect padding
    center_pad = n_fft // 2
    wave_centered = np.pad(wave_padded, (center_pad, center_pad), mode='reflect')

    # 手动 STFT（与 torch 行为一致）
    n = n_fft
    hop = hop_size
    n_frames = 1 + (len(wave_centered) - n) // hop
    spec_complex = np.zeros((n // 2 + 1, n_frames), dtype=np.complex64)
    for i in range(n_frames):
        start = i * hop
        frame = wave_centered[start:start + n] * window
        spec_complex[:, i] = np.fft.rfft(frame, n=n)

    spec_amp = np.abs(spec_complex)
    spec_phase = np.angle(spec_complex)

    # log 幅度
    spec_amp_db = np.log(np.clip(spec_amp, a_min=1e-9, a_max=None))

    # 频域线性增益
    fft_bin = n_fft // 2 + 1
    x0 = fft_bin / ((sample_rate / 2) / 1500)
    freq_filter = (-b / x0) * np.arange(0, fft_bin) + b
    freq_filter = np.clip(freq_filter, -2, 2)

    spec_amp_db = spec_amp_db + freq_filter[:, np.newaxis]

    # 还原幅度
    spec_amp = np.exp(spec_amp_db)

    # 重建复数谱
    spec_filtered = spec_amp * np.exp(1j * spec_phase)

    # 手动 ISTFT（overlap-add）
    output_len = n + (n_frames - 1) * hop
    output = np.zeros(output_len, dtype=np.float64)
    win_sum = np.zeros(output_len, dtype=np.float64)
    for i in range(n_frames):
        start = i * hop
        frame = np.fft.irfft(spec_filtered[:, i], n=n)
        output[start:start + n] += frame * window
        win_sum[start:start + n] += window ** 2
    win_sum = np.maximum(win_sum, 1e-8)
    filtered_wave = output / win_sum

    # trim center padding (torch center=True)
    if len(filtered_wave) > 2 * center_pad:
        filtered_wave = filtered_wave[center_pad:-center_pad]

    # 缩放匹配原始峰值
    original_max = np.max(np.abs(wave[0, 0]))
    filtered_max = np.max(np.abs(filtered_wave))
    if filtered_max > 0:
        filtered_wave = filtered_wave * (original_max / filtered_max) * (np.clip(b / (-15), 0, 0.33) + 1)

    # 裁剪回原始长度
    filtered_wave = filtered_wave[:original_length]

    return filtered_wave.reshape(1, 1, -1).astype(np.float32)
