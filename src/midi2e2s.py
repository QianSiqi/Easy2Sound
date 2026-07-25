#!/usr/bin/env python3
"""
midi2e2s.py — MIDI → E2S 转换器
将标准 MIDI 文件转换为 E2S 格式（用于 Easy2Sound 引擎）。
支持歌词（MIDI 文本事件或外部 .txt）和自动音高曲线。

用法:
  python midi2e2s.py input.mid output.e2s [--lyrics lyrics.txt]
  python midi2e2s.py input.mid output.e2s [--lyrics "ka sa ne te to"]
  python midi2e2s.py input.mid output.e2s  (无歌词时用默认音名)
"""

import sys
import os
import re
import math
import mido
from mido import MidiFile, MidiTrack, MetaMessage


# ── 常量 ──────────────────────────────────────────────────────────────

NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
E2S_TPQN = 480  # E2S 标准每拍 tick 数

# ── 工具函数 ──────────────────────────────────────────────────────────

# 静音标记
SILENCE_LYRICS = {'r', 'R', 'sil', 'pau', '-', '_'}


def midi_note_to_name(note: int) -> str:
    """MIDI 音符编号 → 音名 (C4=60, D#4=63)"""
    octave = (note // 12) - 1
    return f"{NOTE_NAMES[note % 12]}{octave}"


def note_name_to_midi(name: str) -> int:
    """音名 → MIDI 音符编号"""
    m = re.match(r'([A-G]#?)(-?\d+)', name)
    if not m:
        raise ValueError(f"Invalid note name: {name}")
    n, octave = m.group(1), int(m.group(2)) + 1
    return octave * 12 + NOTE_NAMES.index(n)


def ticks_to_e2s_ticks(ticks: int, ppq: int) -> int:
    """将 MIDI 文件的 tick 转换为 E2S 的 480 TPQN tick"""
    if ppq == E2S_TPQN:
        return ticks
    return round(ticks * E2S_TPQN / ppq)


# ── MIDI 解析 ─────────────────────────────────────────────────────────

class NoteEvent:
    """一个音符事件。"""
    __slots__ = ('start_tick', 'end_tick', 'pitch', 'velocity', 'lyric',
                 'pitch_bends')

    def __init__(self, start_tick=0, end_tick=0, pitch=60, velocity=100,
                 lyric='', pitch_bends=None):
        self.start_tick = start_tick
        self.end_tick = end_tick
        self.pitch = pitch
        self.velocity = velocity
        self.lyric = lyric
        self.pitch_bends = pitch_bends if pitch_bends is not None else []


def _detect_midi_charset(path: str) -> str:
    """尝试检测 MIDI 文件文本事件的编码。"""
    mid = MidiFile(path)
    raw_texts: list[bytes] = []
    for track in mid.tracks:
        for msg in track:
            if msg.type in ('lyrics', 'text', 'copyright'):
                raw_texts.append(msg.text.encode('latin-1', errors='surrogateescape'))

    if not raw_texts:
        return 'latin-1'

    has_non_ascii = any(any(b > 127 for b in t) for t in raw_texts)
    if not has_non_ascii:
        return 'latin-1'

    for charset in ('utf-8', 'shift_jis', 'cp932', 'gbk', 'euc-kr'):
        try:
            for raw in raw_texts:
                raw.decode(charset)
            return charset
        except (UnicodeDecodeError, LookupError):
            continue

    return 'latin-1'


def parse_midi(path: str, charset: str | None = None) -> tuple[list[NoteEvent], int, int]:
    """
    解析 MIDI 文件。
    返回 (notes, tempo_bpm, ppq)
    """
    if charset is None:
        charset = _detect_midi_charset(path)
    mid = MidiFile(path, charset=charset)
    ppq = mid.ticks_per_beat

    notes_on: dict[int, tuple[int, int, int]] = {}  # channel*128+note → (tick, vel, channel)
    all_notes: list[NoteEvent] = []
    lyrics: dict[int, str] = {}

    tempo_bpm = 120.0

    # 每个 channel 的当前 pitch bend 值 (范围 -8192 ~ 8191, 中值 0)
    pitch_bends: dict[int, int] = {}
    # 每个 channel+note 的 pitch bend 事件时间线
    pb_events: dict[int, list[tuple[int, int]]] = {}

    for track in mid.tracks:
        abs_tick = 0
        for msg in track:
            abs_tick += msg.time

            if msg.type == 'set_tempo':
                bpm = mido.tempo2bpm(msg.tempo)
                tempo_bpm = bpm

            elif msg.type == 'pitchwheel':
                ch = msg.channel
                pitch_bends[ch] = msg.pitch
                key = ch  # 用 channel 追踪 pitch bend 时间线
                if key not in pb_events:
                    pb_events[key] = []
                pb_events[key].append((abs_tick, msg.pitch))

            elif msg.type == 'note_on' and msg.velocity > 0:
                key = msg.channel * 128 + msg.note
                notes_on[key] = (abs_tick, msg.velocity, msg.channel)

            elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                key = msg.channel * 128 + msg.note
                if key in notes_on:
                    start_tick, vel, ch = notes_on.pop(key)
                    # 提取该音符持续期间的 pitch bend 事件
                    note_bends = []
                    if ch in pb_events:
                        for tick, val in pb_events[ch]:
                            if start_tick <= tick <= abs_tick:
                                note_bends.append((tick, val))
                    note = NoteEvent(
                        start_tick=start_tick,
                        end_tick=abs_tick,
                        pitch=msg.note,
                        velocity=vel,
                        pitch_bends=note_bends,
                    )
                    all_notes.append(note)

            elif msg.type == 'lyrics':
                lyrics[abs_tick] = msg.text.strip()

            elif msg.type == 'text':
                text = msg.text.strip()
                if text and not text.startswith('@'):
                    lyrics[abs_tick] = text

    # 按 start_tick 排序
    all_notes.sort(key=lambda n: n.start_tick)

    # 分配歌词
    lyric_items = sorted(lyrics.items())
    li = 0
    for note in all_notes:
        if li < len(lyric_items):
            lt, ltxt = lyric_items[li]
            if abs(lt - note.start_tick) < ppq * 2:
                note.lyric = ltxt
                li += 1
            elif lt < note.start_tick:
                li += 1

    return all_notes, int(tempo_bpm), ppq


# ── 音高控制点生成 ────────────────────────────────────────────────────

def generate_pt_points(length_e2s: int,
                       pitch_bends: list[tuple[int, int]],
                       ppq: int) -> tuple[list[int], list[int]]:
    """
    根据 MIDI pitch bend 事件生成 pt_x / pt_y 控制点。

    返回 (pt_x_list, pt_y_list)，每个元素是 int 列表。
    pt_x 是 tick 偏移（相对于音符起点），pt_y 是 cent 偏移。
    控制点间隔约 48 ticks（约一拍的 1/10）。
    """
    STEP = 48  # 控制点间隔 (ticks in E2S TPQN)

    if not pitch_bends:
        # 无 pitch bend → 平直
        pt_x = [0, length_e2s]
        pt_y = [0, 0]
        return pt_x, pt_y

    # 将 pitch bend 转换为 cent 值
    # MIDI pitch wheel 范围 ±2 半音 = ±200 cents (默认)
    # pitch 值范围 -8192 ~ 8191
    def pb_to_cents(pb: int) -> int:
        return round(pb * 200.0 / 8192.0)

    # 生成时间采样点
    n_points = max(2, length_e2s // STEP + 1)
    cents = [0] * n_points

    # 在每个采样点做线性插值
    pb_times = [0] + [t for t, _ in pitch_bends] + [length_e2s]
    pb_vals = [0] + [pb_to_cents(v) for _, v in pitch_bends] + [0]

    for i in range(n_points):
        t = i * STEP
        # 找到 t 所在的区间
        for j in range(len(pb_times) - 1):
            if pb_times[j] <= t <= pb_times[j + 1]:
                dt = pb_times[j + 1] - pb_times[j]
                if dt > 0:
                    ratio = (t - pb_times[j]) / dt
                    cents[i] = round(pb_vals[j] + ratio * (pb_vals[j + 1] - pb_vals[j]))
                else:
                    cents[i] = pb_vals[j]
                break
        else:
            cents[i] = pb_vals[-1]

    # 转换为 pt_x, pt_y（跳过中间为 0 的点以压缩文件大小）
    pt_x = []
    pt_y = []
    for i in range(n_points):
        t = i * STEP
        if t <= length_e2s:
            pt_x.append(t)
            pt_y.append(cents[i])

    # 确保最后一个点在 length_e2s
    if pt_x[-1] != length_e2s:
        pt_x.append(length_e2s)
        pt_y.append(0)

    return pt_x, pt_y


# ── 主转换 ────────────────────────────────────────────────────────────

def midi2e2s(midi_path: str, e2s_path: str,
              lyrics_text: str | list[str] | None = None,
              singer: str = 'default_singer',
              phonemer: str = 'your_phonemer',
              flags: str = 'g0B0H0P86',
              crossfade: int = 50,
              velocity_default: int = 100,
              volume_default: int = 100,
              modulation_default: int = 0,
              charset: str | None = None):
    """
    将 MIDI 文件转换为 E2S 格式。

    Args:
        midi_path: 输入 MIDI 文件
        e2s_path: 输出 E2S 文件
        lyrics_text: 歌词（文件路径、字符串列表、或空格分隔的字符串）
        singer: 歌手/音源文件夹名
        phonemer: 音素器程序名
        flags: 默认 Flags
        crossfade: 默认交叉淡化 (ms)
        velocity_default: 默认辅音速度
        volume_default: 默认音量
        modulation_default: 默认移调
        charset: MIDI 文本编码
    """
    # ── 解析 MIDI ──
    notes, tempo_bpm, ppq = parse_midi(midi_path, charset=charset)

    if not notes:
        print(f"[midi2e2s] No notes found in {midi_path}")
        return

    # ── 歌词分配 ──
    lyric_list: list[str] = []
    if isinstance(lyrics_text, str) and os.path.isfile(lyrics_text):
        with open(lyrics_text, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    lyric_list.extend(line.split())
    elif isinstance(lyrics_text, str):
        lyric_list = lyrics_text.split()
    elif isinstance(lyrics_text, list):
        lyric_list = lyrics_text
    elif notes and notes[0].lyric:
        lyric_list = [n.lyric for n in notes if n.lyric]

    # 如果歌词不够，用音名填充
    for i, note in enumerate(notes):
        if i < len(lyric_list):
            note.lyric = lyric_list[i]
        elif not note.lyric:
            note.lyric = midi_note_to_name(note.pitch).lower().replace('#', 's')

    # ── 在空拍处插入 sil 音符 ──
    final_notes: list[NoteEvent] = []
    for i, note in enumerate(notes):
        if i > 0:
            prev_end = notes[i - 1].end_tick
            gap = note.start_tick - prev_end
            if gap > 0:
                sil_note = NoteEvent(
                    start_tick=prev_end,
                    end_tick=note.start_tick,
                    pitch=note.pitch,
                    velocity=velocity_default,
                    lyric='sil',
                )
                final_notes.append(sil_note)
        final_notes.append(note)
    notes = final_notes

    # ── 写入 E2S ──
    with open(e2s_path, 'w', encoding='utf-8') as f:
        # 头部
        f.write('resampler=resampler.exe\n')
        f.write('wavtool=python wavtool.py\n')
        f.write(f'singer={singer}\n')
        f.write(f'phonemer={phonemer}\n')
        f.write(f'tempo={tempo_bpm}\n')

        # 每个音符
        for i, note in enumerate(notes, 1):
            length_e2s = ticks_to_e2s_ticks(note.end_tick - note.start_tick, ppq)
            pitch_name = midi_note_to_name(note.pitch)

            # 生成 pt_x / pt_y 控制点
            pt_x, pt_y = generate_pt_points(length_e2s, note.pitch_bends, ppq)

            # 是否为静音音符
            is_silence = note.lyric.lower() in SILENCE_LYRICS

            f.write(f'\n{i}:\n')
            f.write(f'lyric={note.lyric}\n')
            f.write(f'phoneme={note.lyric}\n')
            f.write(f'pitch={pitch_name}\n')
            f.write(f'velocity={velocity_default}\n')
            f.write(f'flags={"" if is_silence else flags}\n')
            f.write(f'length={length_e2s}\n')
            f.write(f'volume={volume_default}\n')
            f.write(f'modulation={modulation_default}\n')
            f.write(f'tempo={tempo_bpm}\n')
            f.write(f'crossfade={crossfade}\n')
            f.write(f'pt_x={",".join(str(x) for x in pt_x)}\n')
            f.write(f'pt_y={",".join(str(y) for y in pt_y)}\n')

    print(f'[midi2e2s] Converted: {midi_path} → {e2s_path}')
    print(f'           Notes: {len(notes)}, Tempo: {tempo_bpm} BPM')


# ── CLI ────────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='MIDI → E2S 转换器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('input', help='输入 MIDI 文件')
    parser.add_argument('output', help='输出 E2S 文件')
    parser.add_argument('--lyrics', '-l', help='歌词文件或空格分隔的歌词字符串')
    parser.add_argument('--singer', '-s', default='default_singer', help='音源文件夹名')
    parser.add_argument('--phonemer', '-p', default='your_phonemer', help='音素器程序')
    parser.add_argument('--flags', '-f', default='g0B0H0P86', help='默认 Flags')
    parser.add_argument('--crossfade', '-c', type=int, default=50, help='交叉淡化 (ms)')
    parser.add_argument('--velocity', type=int, default=100, help='辅音速度')
    parser.add_argument('--volume', type=int, default=100, help='音量')
    parser.add_argument('--modulation', type=int, default=0, help='移调')
    parser.add_argument('--charset', '-C', default=None,
                        help='MIDI 文本编码 (默认自动检测, 可选: utf-8, shift_jis, cp932, gbk 等)')

    args = parser.parse_args()

    if not os.path.isfile(args.input):
        print(f'[midi2e2s] Error: File not found: {args.input}')
        sys.exit(1)

    midi2e2s(
        midi_path=args.input,
        e2s_path=args.output,
        lyrics_text=args.lyrics,
        singer=args.singer,
        phonemer=args.phonemer,
        flags=args.flags,
        crossfade=args.crossfade,
        velocity_default=args.velocity,
        volume_default=args.volume,
        modulation_default=args.modulation,
        charset=args.charset,
    )


if __name__ == '__main__':
    main()
