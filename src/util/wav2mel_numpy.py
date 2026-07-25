"""
wav2mel_numpy.py — numpy 版 PitchAdjustableMelSpectrogram
用 numpy FFT 替代 torch.stft，完全不依赖 PyTorch 和 librosa。
使用原始 FFT（不做归一化），匹配 torch 的默认行为。
"""

import numpy as np


class PitchAdjustableMelSpectrogramNumpy:
    """numpy 实现的可变调 mel 频谱图提取器，接口与 torch 版一致。"""

    def __init__(
        self,
        sample_rate=44100,
        n_fft=2048,
        win_length=2048,
        hop_length=512,
        f_min=40,
        f_max=16000,
        n_mels=128,
        center=False,
    ):
        self.sample_rate = sample_rate
        self.n_fft = n_fft
        self.win_size = win_length
        self.hop_length = hop_length
        self.f_min = f_min
        self.f_max = f_max
        self.n_mels = n_mels
        self.center = center

        self.mel_basis = {}
        self.hann_window = {}

    def __call__(self, y, key_shift=0, speed=1.0):
        """
        Args:
            y: np.ndarray, shape [1, T] 或 [T]
            key_shift: 半音偏移量
            speed: 速度缩放
        Returns:
            np.ndarray, shape [n_mels, n_frames]
        """
        if y.ndim == 1:
            y = y[np.newaxis, :]  # [1, T]

        factor = 2 ** (key_shift / 12)
        n_fft_new = int(np.round(self.n_fft * factor))
        win_size_new = int(np.round(self.win_size * factor))
        hop_length = int(np.round(self.hop_length * speed))

        # 缓存 mel 滤波器组
        mel_basis_key = f"{self.f_max}"
        if mel_basis_key not in self.mel_basis:
            mel = _mel_filterbank(
                sr=self.sample_rate,
                n_fft=self.n_fft,
                n_mels=self.n_mels,
                fmin=self.f_min,
                fmax=self.f_max,
            )  # [n_mels, n_fft//2+1]
            self.mel_basis[mel_basis_key] = mel.astype(np.float32)

        # 缓存 hann 窗
        hann_key = f"{key_shift}"
        if hann_key not in self.hann_window:
            # torch 默认 hann_window(sym=True)
            self.hann_window[hann_key] = _hann_window(win_size_new, sym=True).astype(np.float32)

        window = self.hann_window[hann_key]
        mel_basis = self.mel_basis[mel_basis_key]

        # reflect padding（与 torch 版一致）
        pad_left = int((win_size_new - hop_length) // 2)
        pad_right = int((win_size_new - hop_length + 1) // 2)
        y_padded = np.pad(y, ((0, 0), (pad_left, pad_right)), mode='reflect')

        # 手动 STFT：逐帧加窗 + FFT（与 torch 行为一致，不做额外归一化）
        n = win_size_new
        hop = hop_length
        x = y_padded[0]  # [T]
        n_frames = 1 + (len(x) - n) // hop
        spec = np.zeros((n // 2 + 1, n_frames), dtype=np.float32)
        for i in range(n_frames):
            start = i * hop
            frame = x[start:start + n] * window
            spec[:, i] = np.abs(np.fft.rfft(frame, n=n))

        # key_shift 补偿：截断或补齐到标准 n_fft//2+1
        if key_shift != 0:
            size = self.n_fft // 2 + 1
            resize = spec.shape[0]
            if resize < size:
                spec = np.pad(spec, ((0, size - resize), (0, 0)), mode='constant')
            spec = spec[:size, :] * self.win_size / win_size_new

        # mel 滤波: [n_mels, n_fft//2+1] @ [n_fft//2+1, n_frames] → [n_mels, n_frames]
        mel_spec = mel_basis @ spec

        return mel_spec

    def dynamic_range_compression(self, x, C=1, clip_val=1e-5):
        return np.log(np.clip(x, a_min=clip_val, a_max=None) * C)


def _hann_window(window_length, sym=True):
    """生成 Hann 窗，与 torch.hann_window 行为一致。"""
    if sym:
        n = window_length - 1
    else:
        n = window_length
    k = np.arange(window_length)
    return 0.5 * (1 - np.cos(2 * np.pi * k / n))


def _mel_filterbank(sr, n_fft, n_mels=128, fmin=0.0, fmax=None):
    """生成 mel 滤波器组，替代 librosa.filters.mel。纯 numpy 实现。"""
    if fmax is None:
        fmax = sr / 2.0

    # 频率轴 (Hz)
    n_freqs = n_fft // 2 + 1
    fft_freqs = np.linspace(0, sr / 2, n_freqs)

    # mel 刻度转换
    def hz_to_mel(f):
        return 2595.0 * np.log10(1.0 + f / 700.0)

    def mel_to_hz(m):
        return 700.0 * (10.0 ** (m / 2595.0) - 1.0)

    mel_min = hz_to_mel(fmin)
    mel_max = hz_to_mel(fmax)

    # mel 中心频率（线性间隔）
    mel_points = np.linspace(mel_min, mel_max, n_mels + 2)
    hz_points = mel_to_hz(mel_points)

    # 构建三角滤波器
    filterbank = np.zeros((n_mels, n_freqs), dtype=np.float32)
    for i in range(n_mels):
        left = hz_points[i]
        center = hz_points[i + 1]
        right = hz_points[i + 2]

        # 上升沿
        up_mask = (fft_freqs >= left) & (fft_freqs <= center)
        if center > left:
            filterbank[i, up_mask] = (fft_freqs[up_mask] - left) / (center - left)

        # 下降沿
        down_mask = (fft_freqs > center) & (fft_freqs <= right)
        if right > center:
            filterbank[i, down_mask] = (right - fft_freqs[down_mask]) / (right - center)

    # 归一化：使每个滤波器的面积为 1（与 librosa 一致）
    enorm = 2.0 / (hz_points[2:] - hz_points[:-2])
    filterbank *= enorm[:, np.newaxis]

    return filterbank
