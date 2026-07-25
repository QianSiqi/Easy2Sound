"""
ust2e2s.py — UST → E2S 格式转换器
将 UTAU 序列文件 (.ust) 转换为 Easy2Sound 格式 (.e2s)

用法:
    python ust2e2s.py <input.ust> [output.e2s]
    python ust2e2s.py test.ust              # → test.e2s
    python ust2e2s.py test.ust output.e2s   # → output.e2s
"""

import sys
import os
import re

NOTES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

def note_num_to_pitch(note_num):
    """NoteNum (60=C4) → 音名 (如 'C4')"""
    octave = (note_num // 12) - 1
    note = NOTES[note_num % 12]
    return f'{note}{octave}'

# ── UST 解析 ───────────────────────────────────────────────────────────

def detect_encoding(path):
    """检测 UST 文件编码（尝试常见编码）"""
    for enc in ['shift_jis']:
        try:
            with open(path, 'r', encoding=enc) as f:
                f.read(4096)
            return enc
        except (UnicodeDecodeError, UnicodeError):
            continue
    return 'latin-1'

def parse_ust(path):
    """
    解析 UST 文件，返回 (settings, notes)
    settings: dict  — [#SETTING] 段的所有键值对
    notes:    list[dict] — 每个音符的字段字典（含 [#XXXX] 段名信息）
    """
    enc = detect_encoding(path)
    with open(path, 'r', encoding=enc, errors='replace') as f:
        lines = f.readlines()

    settings = {}
    notes = []
    current_note = None
    current_section = ''

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 段头 [xxx]
        if line.startswith('[') and line.endswith(']'):
            section = line[1:-1].lstrip('#')
            if section == 'SETTING':
                current_section = 'SETTING'
            elif section == 'VERSION':
                current_section = 'VERSION'
            elif section == 'TRACKEND':
                current_section = 'TRACKEND'
            elif re.match(r'^\d{4}$', section):
                current_section = 'NOTE'
                current_note = {'_section': section}
                notes.append(current_note)
            else:
                current_section = section
                current_note = None
            continue

        # 键值对
        key, _, val = line.partition('=')
        key = key.strip()
        val = val.strip()

        if current_section == 'SETTING':
            settings[key] = val
        elif current_section == 'NOTE' and current_note is not None:
            current_note[key] = val

    return settings, notes

# ── Pitch Bend 转换 ───────────────────────────────────────────────────

def ust_pitch_to_samples(note, total_ticks):
    """
    将 UST 的 PBS/PBW/PBY 转换为每 5 ticks 一个采样的 cents 数组。
    用于写入 e2s 的 pitch_string 字段。
    """
    pbs = note.get('PBS', '')
    pbw = note.get('PBW', '')
    pby = note.get('PBY', '')

    if not pbw or not pby:
        return []

    # 解析 PBS: "start_cents;start_ticks" 或 "start_cents"
    start_cents = 0.0
    start_ticks = 0
    if pbs:
        parts = pbs.split(';')
        try:
            start_cents = float(parts[0])
        except ValueError:
            start_cents = 0.0
        if len(parts) > 1:
            try:
                start_ticks = float(parts[1])
            except ValueError:
                start_ticks = 0

    # 解析各数组
    widths = [float(x) for x in pbw.split(',') if x.strip() != '']
    heights = [float(x) for x in pby.split(',') if x.strip() != '']

    # 构建控制点: [(tick, cents), ...]
    n = max(len(widths), len(heights))
    control_points = [(start_ticks, start_cents)]

    tick_cursor = start_ticks
    for i in range(n):
        w = widths[i] if i < len(widths) else 0
        h = heights[i] if i < len(heights) else 0
        tick_cursor += w
        control_points.append((tick_cursor, h))

    if not control_points:
        return []

    # 重采样到每 5 ticks 一个点
    ticks_per_sample = 5
    total_samples = max(1, int(total_ticks / ticks_per_sample))
    samples = []

    for s in range(total_samples + 1):
        tick = s * ticks_per_sample
        cents = _interpolate_control_points(control_points, tick)
        samples.append(round(cents))

    return samples

def _interpolate_control_points(points, tick):
    """在控制点之间做线性插值"""
    if not points:
        return 0.0
    if tick <= points[0][0]:
        return points[0][1]
    if tick >= points[-1][0]:
        return points[-1][1]

    for i in range(len(points) - 1):
        t0, c0 = points[i]
        t1, c1 = points[i + 1]
        if t0 <= tick <= t1:
            if t1 == t0:
                return c0
            ratio = (tick - t0) / (t1 - t0)
            return c0 + (c1 - c0) * ratio

    return points[-1][1]

# ── 主转换逻辑 ────────────────────────────────────────────────────────

def convert_ust_to_e2s(ust_path, e2s_path):
    """
    将 UST 文件转换为 E2S 文件。
    返回 (note_count, warnings) 元组。
    """
    settings, notes = parse_ust(ust_path)

    # 提取全局设置
    tempo = settings.get('Tempo', '120')
    if '.' in tempo:
        tempo = str(int(float(tempo)))

    # 工具配置
    wavtool = settings.get('Tool1', 'wavtool.exe')
    resampler = settings.get('Tool2', 'f2resamp64.exe')

    # VoiceDir → singer（去掉 %VOICE% 前缀）
    voice_dir = settings.get('VoiceDir', '')
    singer = voice_dir.replace('%VOICE%', '').strip().rstrip('\\')

    warnings = []

    # 写 e2s
    lines = []
    lines.append(f'resampler={resampler}')
    lines.append(f'wavtool={wavtool}')
    lines.append(f'singer={singer}')
    lines.append(f'phonemer=')
    lines.append(f'tempo={tempo}')

    for i, note in enumerate(notes):
        lyric = note.get('Lyric', '')
        # UST 的 R/pau/sil 转为 sil
        if lyric.upper() in ('R', 'PAU', 'SIL', 'REST'):
            lyric = 'sil'
        note_num = int(note.get('NoteNum', '60'))
        length = int(note.get('Length', '480'))
        velocity = int(note.get('Velocity', '100'))
        flags = note.get('Flags', '')
        intensity = note.get('Intensity', '100')
        modulation = note.get('Modulation', '0')

        # PreUtterance → consonant
        pre = note.get('PreUtterance', '')
        consonant = 0
        if pre and pre.strip():
            try:
                consonant = int(float(pre))
            except ValueError:
                consonant = 0

        cutoff = int(note.get('Cutoff', '0'))

        # VBR → vib_start/vib_end/vib_hz/vib_hard
        # UST VBR 格式: "start%;end%;depth;rate"
        #   start/end: 颤音范围（0~100%，相对音符长度）
        #   depth: 振幅（cents）
        #   rate: 频率（/10，如 65 = 6.5Hz）
        vib_start_ticks = ''
        vib_end_ticks = ''
        vib_hz = ''
        vib_hard = ''
        vbr = note.get('VBR', '')
        if vbr:
            vbr_parts = vbr.split(',')
            if len(vbr_parts) >= 4:
                try:
                    vbr_start_pct = float(vbr_parts[0]) / 100.0  # 0~1
                    vbr_end_pct = float(vbr_parts[1]) / 100.0
                    vbr_depth = int(float(vbr_parts[2]))  # cents
                    vbr_rate = int(float(vbr_parts[3]))    # /10
                    # 百分比 → tick
                    vib_start_ticks = str(int(vbr_start_pct * length))
                    vib_end_ticks = str(int(vbr_end_pct * length))
                    vib_hz = str(vbr_rate)
                    vib_hard = str(vbr_depth)
                except (ValueError, IndexError):
                    pass

        # Pitch bend → pt_x/pt_y 控制点（read_e2s.py 运行时会转换为 pitch_string）
        pitch_samples = ust_pitch_to_samples(note, length)
        
        pt_x_list = []
        pt_y_list = []
        if pitch_samples:
            ticks_per_sample = 5
            step = 48  # 每 48 ticks 一个控制点
            for tick in range(0, length + 1, step):
                sample_idx = min(tick // ticks_per_sample, len(pitch_samples) - 1)
                pt_x_list.append(str(tick))
                pt_y_list.append(str(pitch_samples[sample_idx]))
            # 确保最后一个点
            if pt_x_list[-1] != str(length):
                pt_x_list.append(str(length))
                pt_y_list.append(str(pitch_samples[-1] if pitch_samples else 0))
        
        lines.append(f'{i + 1}:')
        lines.append(f'lyric={lyric}')
        lines.append(f'phoneme={lyric}')  # phonemer 会更新这个值
        lines.append(f'pitch={note_num_to_pitch(note_num)}')
        lines.append(f'velocity={velocity}')
        lines.append(f'flags={flags}')
        lines.append(f'length={length}')
        lines.append(f'volume={intensity}')  # e2s 用 volume 代替 intensity
        lines.append(f'modulation={modulation}')
        lines.append(f'tempo={tempo}')
        lines.append(f'crossfade=50')  # 默认 crossfade
        if pt_x_list:
            lines.append(f'pt_x={",".join(pt_x_list)}')
            lines.append(f'pt_y={",".join(pt_y_list)}')
        if vib_start_ticks:
            lines.append(f'vib_start={vib_start_ticks}')
            lines.append(f'vib_end={vib_end_ticks}')
            lines.append(f'vib_hz={vib_hz}')
            lines.append(f'vib_hard={vib_hard}')

    with open(e2s_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')

    return len(notes), warnings

# ── 命令行入口 ────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print('用法: python ust2e2s.py <input.ust> [output.e2s]')
        print()
        print('示例:')
        print('  python ust2e2s.py song.ust')
        print('  python ust2e2s.py song.ust output.e2s')
        sys.exit(1)

    ust_path = sys.argv[1]
    if not os.path.isfile(ust_path):
        print(f'错误: 文件不存在 — {ust_path}')
        sys.exit(1)

    if len(sys.argv) >= 3:
        e2s_path = sys.argv[2]
    else:
        e2s_path = os.path.splitext(ust_path)[0] + '.e2s'

    print(f'转换: {ust_path} → {e2s_path}')
    count, warnings = convert_ust_to_e2s(ust_path, e2s_path)

    for w in warnings:
        print(f'  警告: {w}')

    print(f'完成: {count} 个音符已写入 {e2s_path}')

if __name__ == '__main__':
    main()
