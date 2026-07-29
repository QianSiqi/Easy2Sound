"""
read_e2s.py — E2S 文件渲染器
按字段名解析 e2s（参照 utaupy 的 dict 方式），调用 resampler + wavtool。
"""

import sys, os
import math
import subprocess
import librosa
import numpy as np
import soundfile as sf


# ── 工具函数 ───────────────────────────────────────────────────────────

def ticks_to_ms(ticks: float, bpm: float) -> float:
    """125 * ticks / bpm  (utaupy 同款公式)"""
    return 125.0 * ticks / bpm


def get_audio_duration(path: str) -> float:
    try:
        y, sr = librosa.load(path)
        return librosa.get_duration(y=y, sr=sr)
    except Exception as e:
        print(f"[WARN] Can't load {path}: {e}")
        return 0.0


def create_silence(duration_s: float, sr=44100):
    n = int(duration_s * sr)
    return np.zeros(n, dtype=np.float32), sr


# ── Pitch 编码（UTAU pitchbend 格式）────────────────────────────────────

def to_uint6(c: int) -> int:
    """将一个 Base64 字符转换为 6-bit 无符号整数。"""
    if c >= 97:      # a-z
        return c - 71
    elif c >= 65:    # A-Z
        return c - 65
    elif c >= 48:    # 0-9
        return c + 4
    elif c == 43:    # +
        return 62
    elif c == 47:    # /
        return 63
    else:
        raise ValueError(f"Invalid Base64 char: {chr(c)}")


def to_int12(b64: str) -> int:
    """两个 Base64 字符 -> 有符号 12-bit 整数 (-2048 ~ 2047)。"""
    uint12 = to_uint6(ord(b64[0])) << 6 | to_uint6(ord(b64[1]))
    if uint12 >> 11 & 1:
        return uint12 - 4096
    return uint12


def from_int12(val: int) -> str:
    """有符号 12-bit 整数 -> 两个 Base64 字符。"""
    if val < 0:
        val += 4096
    hi = val >> 6
    lo = val & 0x3F
    # Base64 字符表: A-Z(0-25) a-z(26-51) 0-9(52-61) +(62) /(63)
    table = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
    return table[hi] + table[lo]


def encode_pitch_curve(cents: list[int]) -> str:
    """将 cents 值列表编码为 UTAU pitch string（含 RLE 压缩）。

    编码规则:
    - 每 2 个 Base64 字符表示一个 12-bit 有符号整数（cent 值，1 半音 = 100 cents）
    - 连续相同值用 RLE 压缩: AA#N# 表示 AA 重复 N+1 次
    - 示例: AA#5# -> [0,0,0,0,0,0]（6 个 0）
    """
    if not cents:
        return 'AA'

    parts = []
    i = 0
    while i < len(cents):
        val = cents[i]
        # 计算连续相同值的个数
        run_len = 1
        while i + run_len < len(cents) and cents[i + run_len] == val:
            run_len += 1
        encoded = from_int12(val)
        if run_len >= 2:
            # RLE: 值 + '#' + (重复次数-1) + '#'
            parts.append(f"{encoded}#{run_len - 1}#")
        else:
            parts.append(encoded)
        i += run_len
    return ''.join(parts)


def generate_pitch_string(
    length_ticks: int,
    tempo: float,
    pt_x: str = '',
    pt_y: str = '',
    vib_start: str = '',
    vib_end: str = '',
    vib_hz: str = '',
    vib_hard: str = '',
) -> str:
    """根据端口滑音和颤音参数生成 UTAU pitch string。

    参数:
    - length_ticks: 音符长度（ticks）
    - tempo: 曲速 BPM
    - pt_x, pt_y: 端口滑音控制点（逗号分隔的 tick 偏移和 cent 偏移）
    - vib_start, vib_end: 颤音起止位置（ticks）
    - vib_hz: 颤音频率（/10，如 20 = 2.0Hz）
    - vib_hard: 颤音深度（cents）

    返回:
    - UTAU pitch string（Base64 + RLE 编码）
    """
    # 每 5 ticks 一个控制点
    n_points = max(2, length_ticks // 5)
    cents = [0] * n_points

    # --- 端口滑音（Portamento）---
    # pt_x, pt_y: 音高控制点的 x/y 轴
    #   x = tick（相对于音符起点）
    #   y = cent（音高偏移，100 cents = 半音）
    # 控制点之间线性插值，范围外延伸到首尾值
    if pt_x and pt_y:
        try:
            xs = [int(x.strip()) for x in pt_x.split(',') if x.strip()]
            ys = [int(y.strip()) for y in pt_y.split(',') if y.strip()]
            if xs and ys and len(xs) == len(ys):
                for i in range(n_points):
                    t = i * 5  # 当前 tick
                    # 范围外: 延伸到最近的控制点值
                    if t <= xs[0]:
                        cents[i] = ys[0]
                    elif t >= xs[-1]:
                        cents[i] = ys[-1]
                    else:
                        # 线性插值
                        for j in range(len(xs) - 1):
                            if xs[j] <= t <= xs[j + 1]:
                                dx = xs[j + 1] - xs[j]
                                if dx > 0:
                                    ratio = (t - xs[j]) / dx
                                    cents[i] = int(ys[j] + ratio * (ys[j + 1] - ys[j]))
                                else:
                                    cents[i] = ys[j]
                                break
        except (ValueError, IndexError):
            pass  # 解析失败，保持全零

    # --- 颤音（Vibrato）---
    if vib_start and vib_end and vib_hz and vib_hard:
        try:
            v_start = int(vib_start)  # 颤音起始 tick
            v_end = int(vib_end)      # 颤音结束 tick
            v_hz = float(vib_hz) / 10.0  # 实际频率（/10）
            v_depth = int(vib_hard)   # 颤音深度（cents）

            if v_hz > 0 and v_depth > 0 and v_end > v_start:
                ticks_per_beat = 480  # 一拍 = 480 ticks
                ms_per_beat = 60000.0 / tempo  # 一拍的毫秒数
                # 颤音周期 = 1/v_hz 秒
                period_s = 1.0 / v_hz
                period_ticks = period_s * (ticks_per_beat / (ms_per_beat / 1000.0))
                # period_ticks = ticks_per_beat / v_hz * (tempo / 120.0)
                # 简化: 1 秒 = tempo/60 拍 = tempo/60 * 480 ticks
                # 周期 ticks = (1/v_hz) * tempo/60 * 480
                period_ticks = (tempo * 480.0) / (60.0 * v_hz)

                for i in range(n_points):
                    t = i * 5
                    if v_start <= t <= v_end:
                        # 正弦颤音
                        phase = 2.0 * math.pi * (t - v_start) / period_ticks
                        vib_val = v_depth * math.sin(phase)
                        cents[i] += int(vib_val)
        except (ValueError, IndexError):
            pass  # 解析失败，不做颤音

    # 钳位到有效范围
    cents = [max(-2048, min(2047, c)) for c in cents]

    return encode_pitch_curve(cents)


# ── E2S 解析（dict 方式） ──────────────────────────────────────────────

def read_e2s(path: str, execute_phonemer: bool = True) -> list[dict]:
    """
    解析 e2s 文件。
    每个音符返回一个 dict，字段名为 key。
    execute_phonemer=True 时（默认，命令行模式），解析到 phonemer 字段会自动执行；
    execute_phonemer=False 时（web UI 调用），仅解析不执行。
    """
    global resampler, wavtool, singer, phonemer, tempo
    resampler = wavtool = singer = phonemer = ""
    tempo = "120"
    notes: list[dict] = []
    header_done = False

    with open(path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 头部字段
        if not header_done:
            if line.endswith(':'):
                header_done = True
                notes.append({})
                continue
            key, _, val = line.partition('=')
            k = key.strip()
            v = val.strip()
            if k == 'resampler':
                resampler = v
            elif k == 'wavtool':
                wavtool = v
            elif k == 'singer':
                singer = os.path.abspath(v) if not os.path.isabs(v) else v
            elif k == 'phonemer':
                phonemer = v
                if execute_phonemer:
                    print(f'{phonemer} {path}')
                    subprocess.run(phonemer.split() + [path], check=False)
            elif k == 'tempo':
                tempo = v
            continue

        # 音符块
        if line.endswith(':'):
            notes.append({})
            continue

        key, _, val = line.partition('=')
        notes[-1][key.strip()] = val.strip()

    return notes


# ── 重采样 ─────────────────────────────────────────────────────────────

def call_resampler(notes: list[dict]):
    global singer, resampler
    print("----------------------------")
    cnt = 0
    for note in notes:
        phoneme = note.get('phoneme', note.get('lyric', ''))
        is_sil = phoneme.lower() == ('sil')

        if is_sil:
            length_ticks = int(float(note.get('length', '480')))
            n_tempo = int(float(note.get('tempo', tempo)))
            dur_ms = ticks_to_ms(length_ticks, n_tempo)
            sil, sr = create_silence(dur_ms / 1000.0)
            out = f"tmp/sil_{cnt}.wav"
            sf.write(out, sil, sr)
            print(f'Silence: {out} ({dur_ms:.0f}ms)')
        else:
            # 从 meta.txt 读取 overlap (fixed_length)
            cons = '0'  # 默认值
            meta_path = f'{singer}/meta.txt'
            if os.path.exists(meta_path):
                with open(meta_path, 'r', encoding='utf-8') as f:
                    for ml in f:
                        if ml.startswith(phoneme):
                            parts = ml.strip().split(',')
                            if len(parts) >= 3:
                                cons = parts[2].strip()
                            break

            length_ticks = int(float(note.get('length', '480')))
            n_tempo = int(float(note.get('tempo', tempo)))
            ms_total = int(ticks_to_ms(length_ticks, n_tempo))  # 期望总时长
            # server 的 length_require 是 stretchable 部分，总输出 = length_require + cons
            ms_stretch = max(0, ms_total - int(cons or 0))
            cutoff = 0

            pitch = note.get('pitch', 'C4')
            velocity = note.get('velocity', '100')
            flags = note.get('flags', '')
            volume = note.get('volume', '100')
            modulation = note.get('modulation', '0')
            tempo_str = note.get('tempo', tempo)
            pitch_str = note.get('pitch_string', '')
            if not pitch_str:
                # 根据 pt_x/pt_y 和颤音参数生成 pitch string
                pitch_str = generate_pitch_string(
                    length_ticks=length_ticks,
                    tempo=float(n_tempo),
                    pt_x=note.get('pt_x', ''),
                    pt_y=note.get('pt_y', ''),
                    vib_start=note.get('vib_start', ''),
                    vib_end=note.get('vib_end', ''),
                    vib_hz=note.get('vib_hz', ''),
                    vib_hard=note.get('vib_hard', ''),
                )
            # 新格式：pt_x/pt_y 控制点（已整合到 generate_pitch_string 中）

            print(f'  [DEBUG] {phoneme}: len_ticks={length_ticks} tempo={n_tempo} -> total_ms={ms_total} stretch_ms={ms_stretch} cons={cons}')

            cmd_list = resampler.split() + [
                        f'{singer}/{phoneme}.wav',
                        f'tmp/{phoneme}_{cnt}.wav',
                        pitch, velocity, flags,
                        '0', str(ms_stretch), cons, str(cutoff),
                        volume, modulation, f'!{tempo_str}', pitch_str]
            print(' '.join(cmd_list))
            subprocess.run(cmd_list, check=False)

        cnt += 1


# ── 拼接 ───────────────────────────────────────────────────────────────

def call_wavtool(notes: list[dict]):
    global wavtool, singer
    wavs = []
    for i, note in enumerate(notes):
        phoneme = note.get('phoneme', note.get('lyric', ''))
        is_sil = phoneme.lower() in ('r', 'sil', 'pau')
        name = 'sil' if is_sil else phoneme
        wavs.append(f'tmp/{name}_{i}.wav')
    wavs.append('tmp/out.wav')

    # 从 meta.txt 读取每个音素的 overlap 值
    meta_overlap = {}
    meta_path = f'{singer}/meta.txt'
    if os.path.exists(meta_path):
        with open(meta_path, 'r', encoding='utf-8') as f:
            for ml in f:
                parts = ml.strip().split(',')
                if len(parts) >= 3:
                    meta_overlap[parts[1].strip()] = int(parts[2].strip())

    crossfade_vals = []
    for note in notes[:-1]:
        phoneme = note.get('phoneme', note.get('lyric', ''))
        # 从 meta.txt 查找 crossfade，找不到则用默认值
        cf = meta_overlap.get(phoneme, 50)
        crossfade_vals.append(str(cf))

    wavs.extend(crossfade_vals)
    cmd_list = wavtool.split() + wavs
    print(' '.join(cmd_list))
    subprocess.run(cmd_list, check=False)


# ── 入口 ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: read_e2s <filename>")
        sys.exit(1)

    path = sys.argv[1]
    print("----------------------------")
    print(f"Reading e2s: {path}")

    notes = read_e2s(path)

    # phonemer 可能已修改了文件，重新读一遍以获取更新后的值
    notes = read_e2s(path)

    os.makedirs('tmp', exist_ok=True)

    call_resampler(notes)
    call_wavtool(notes)
