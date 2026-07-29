"""
wavtool — 音频拼接器
====================
将多个重采样后的 wav 以 overlap-add（重叠相加）+ 相位补偿拼接成完整音频。
参考 OpenUtau SharpWavtool 的实现。
"""

import os
import sys
import yaml
import numpy as np
import librosa
import soundfile as sf


def _load_config(config_path=None):
    if config_path is None:
        config_path = os.path.join(os.path.dirname(__file__), 'config.yaml')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f) or {}
        return cfg.get('audio', {})
    except Exception:
        return {}

SAMPLE_RATE = _load_config().get('sample_rate', 44100)


def _calc_phase(samples, sr, f0):
    """计算信号在指定频率处的相位"""
    if len(samples) < 4 or f0 <= 0:
        return None
    # 带通滤波提取基频成分
    try:
        from scipy.signal import butter, sosfilt
        nyq = sr / 2
        low = max(f0 * 0.75, 20) / nyq
        high = min(f0 * 1.5, nyq - 1) / nyq
        if low >= high:
            return None
        sos = butter(2, [low, high], btype='band', output='sos')
        filtered = sosfilt(sos, samples)
    except Exception:
        return None

    if np.max(np.abs(filtered)) > 10:
        return None

    # 找中心附近的两个峰值
    mid = len(filtered) // 2
    left = right = None
    for i in range(mid - 1, 0, -1):
        if filtered[i] >= filtered[i-1] and filtered[i] >= filtered[i+1]:
            left = i
            break
    for i in range(mid, len(filtered) - 1):
        if filtered[i] >= filtered[i-1] and filtered[i] >= filtered[i+1]:
            right = i
            break

    if left is None or right is None or left >= right:
        return None

    actual_f = sr / (right - left)
    if abs(f0 - actual_f) > f0 * 0.25:
        return None

    # 估算相位
    t = (left + right) * 0.5 / sr * f0
    return 2 * np.pi * (np.round(t) - t)


def _get_f0_at_sample(pitches, note_positions, sample_index, sr):
    """根据音高序列估算某个采样点的 F0"""
    if len(pitches) == 0:
        return 440.0
    # 简化：用最近的音高
    note_idx = min(int(sample_index / sr * len(pitches) / max(len(pitches), 1)), len(pitches) - 1)
    note_idx = max(0, note_idx)
    return 440.0 * (2 ** ((pitches[note_idx] - 69) / 12.0))


def overlap_add(final, segment, overlap_samples, sr):
    """OpenUtau 风格的 overlap-add，带相位补偿"""
    if overlap_samples <= 0 or len(segment) == 0:
        return np.concatenate([final, segment]) if len(segment) > 0 else final

    # 相位补偿：找最佳对齐偏移
    correction = 0
    if len(final) >= overlap_samples and len(segment) >= overlap_samples:
        tail = final[-overlap_samples:]
        head = segment[:overlap_samples]
        # 简单相位对齐：找最大互相关
        try:
            corr = np.correlate(head, tail, mode='full')
            offset = np.argmax(corr) - len(tail) + 1
            correction = int(np.clip(offset, -overlap_samples // 4, overlap_samples // 4))
        except Exception:
            pass

    # 计算总长度
    total_len = max(len(final), len(final) - overlap_samples + correction + len(segment))
    result = np.zeros(total_len, dtype=np.float64)

    # 放置 final
    result[:len(final)] = final

    # overlap-add segment
    start = len(final) - overlap_samples + correction
    for i in range(len(segment)):
        pos = start + i
        if 0 <= pos < total_len:
            result[pos] += segment[i]

    return result


def _normalize(audio, peak=0.95):
    mx = np.max(np.abs(audio))
    if mx > 0:
        return audio * min(1.0, peak / mx)
    return audio


def wavtool(wavs, output='', overlap_durations_ms=None):
    n = len(wavs)
    if n == 0:
        print('[wavtool] No input files.')
        return None, None

    if overlap_durations_ms is None:
        overlap_durations_ms = [50] * (n - 1)
    else:
        need = n - 1
        if len(overlap_durations_ms) < need:
            overlap_durations_ms += [50] * (need - len(overlap_durations_ms))
        else:
            overlap_durations_ms = overlap_durations_ms[:need]

    try:
        final, sr = librosa.load(wavs[0], sr=SAMPLE_RATE)
    except Exception:
        print(f'[wavtool] Cannot load {wavs[0]}, using silence')
        sr = SAMPLE_RATE
        final = np.zeros(int(0.1 * sr))

    for i in range(1, n):
        try:
            cur, _ = librosa.load(wavs[i], sr=SAMPLE_RATE)
        except Exception:
            print(f'[wavtool] Cannot load {wavs[i]}, using silence')
            cur = np.zeros(int(0.1 * sr))
        overlap_samples = int(overlap_durations_ms[i - 1] / 1000 * sr)
        final = overlap_add(final, cur, overlap_samples, sr)

    final = _normalize(final, 0.95)

    if output and len(final) > 0:
        sf.write(output, final, sr)
        print(f'[wavtool] Saved -> {output}  ({len(final)/sr:.2f}s)')

    return final, sr


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print('Usage: python wavtool.py <in1.wav> ... <out.wav> [overlap_ms ...]')
        sys.exit(1)

    args = sys.argv[1:]
    ovs = []
    while len(args) > 2:
        try:
            ovs.insert(0, float(args[-1]))
            args = args[:-1]
        except ValueError:
            break

    if len(args) < 2:
        print('[wavtool] Error: need inputs + output.')
        sys.exit(1)

    inputs, output = args[:-1], args[-1]
    missing = [f for f in inputs if not os.path.exists(f)]
    if missing:
        print(f'[wavtool] Missing: {missing}')
        sys.exit(1)

    print(f'[wavtool] {len(inputs)} files -> {output}')
    if ovs:
        print(f'[wavtool] Overlap: {ovs}ms')
    wavtool(inputs, output, ovs)
