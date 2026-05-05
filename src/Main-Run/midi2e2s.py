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
    # 按比例换算
    return round(ticks * E2S_TPQN / ppq)


# ── MIDI 解析 ─────────────────────────────────────────────────────────

class NoteEvent:
    """一个音符事件。"""
    __slots__ = ('start_tick', 'end_tick', 'pitch', 'velocity', 'lyric')

    def __init__(self, start_tick=0, end_tick=0, pitch=60, velocity=100, lyric=''):
        self.start_tick = start_tick
        self.end_tick = end_tick
        self.pitch = pitch
        self.velocity = velocity
        self.lyric = lyric


def parse_midi(path: str) -> tuple[list[NoteEvent], int, list[int]]:
    """
    解析 MIDI 文件。
    返回 (notes, tempo_bpm, tempo_changes_in_ticks)
    """
    mid = MidiFile(path)
    ppq = mid.ticks_per_beat

    # 收集所有音符
    notes_on: dict[int, tuple[int, int, int]] = {}  # channel*128+note → (tick, vel, channel)
    all_notes: list[NoteEvent] = []

    # 收集歌词
    lyrics: dict[int, str] = {}  # tick → lyric text

    # 收集速度变化
    tempo_bpm = 120.0
    tempo_changes = [(0, tempo_bpm)]

    for track in mid.tracks:
        abs_tick = 0
        for msg in track:
            abs_tick += msg.time

            if msg.type == 'set_tempo':
                bpm = mido.tempo2bpm(msg.tempo)
                tempo_bpm = bpm
                tempo_changes.append((abs_tick, bpm))

            elif msg.type == 'note_on' and msg.velocity > 0:
                key = msg.channel * 128 + msg.note
                notes_on[key] = (abs_tick, msg.velocity, msg.channel)

            elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                key = msg.channel * 128 + msg.note
                if key in notes_on:
                    start_tick, vel, ch = notes_on.pop(key)
                    note = NoteEvent(
                        start_tick=start_tick,
                        end_tick=abs_tick,
                        pitch=msg.note,
                        velocity=vel,
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

    # 分配歌词：依次匹配歌词到音符
    lyric_items = sorted(lyrics.items())
    li = 0
    for note in all_notes:
        if li < len(lyric_items):
            lt, ltxt = lyric_items[li]
            # 歌词时间接近或早于音符开始
            if abs(lt - note.start_tick) < ppq * 2:  # 2 拍内的歌词匹配
                note.lyric = ltxt
                li += 1
            elif lt < note.start_tick:
                li += 1

    return all_notes, int(tempo_bpm), ppq


# ── 音高曲线生成 ──────────────────────────────────────────────────────

def _cents_to_b64(cents: int) -> str:
    """单个 cent 值 → 2 个 Base64 字符"""
    if cents < 0:
        cents += 4096
    hi = (cents >> 6) & 0x3F
    lo = cents & 0x3F

    def _c(v):
        if 0 <= v <= 25: return chr(65 + v)
        if 26 <= v <= 51: return chr(97 + v - 26)
        if 52 <= v <= 61: return chr(48 + v - 52)
        if v == 62: return '+'
        if v == 63: return '/'
        raise ValueError(f"Out of range: {v}")

    return _c(hi) + _c(lo)


def _rle_encode(values: list[int]) -> str:
    """对 cent 值数组做 Base64 + RLE 编码。"""
    if not values:
        return 'AA#0#'

    # 全平 → 直接 RLE
    if all(v == values[0] for v in values):
        return f'{_cents_to_b64(values[0])}#{len(values) - 1}#'

    result = []
    i = 0
    while i < len(values):
        val = values[i]
        j = i + 1
        while j < len(values) and values[j] == val:
            j += 1
        run = j - i
        pair = _cents_to_b64(val)
        if run == 1:
            result.append(pair)
        else:
            result.append(f'{pair}#{run - 1}#')
        i = j

    return ''.join(result)


def generate_pitch_string(length_ticks: int,
                          prev_pitch: int | None = None,
                          next_pitch: int | None = None) -> str:
    """
    根据音符长度生成音高曲线字符串（Base64+RLE）。
    简单版本：仅连滑音，无 PBS/PBW/PBY 细节。
    """
    total_samples = max(4, length_ticks // 5)

    if prev_pitch is None and next_pitch is None:
        # 无连滑 → 平直音高
        return f'AA#{total_samples - 1}#'

    # 简单的连滑：从 prev_pitch 到当前音符的起始渐变
    samples = [0] * total_samples
    if prev_pitch is not None:
        # 前一个音到当前音有半音差，在前面做一些渐变
        diff_cents = prev_pitch * 100  # 用相对值表示
        # 简单的斜线在开头
        for s in range(min(10, total_samples)):
            frac = (10 - s) / 10.0
            samples[s] = round(frac * diff_cents)

    return _rle_encode(samples)


# ── 主转换 ────────────────────────────────────────────────────────────

def midi2e2s(midi_path: str, e2s_path: str,
              lyrics_text: str | list[str] | None = None,
              singer: str = 'default_singer',
              phonemer: str = 'your_phonemer',
              flags: str = 'g0B0H0P86',
              crossfade: int = 50,
              velocity_default: int = 100,
              volume_default: int = 100,
              modulation_default: int = 0):
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
    """
    # ── 解析 MIDI ──
    notes, tempo_bpm, ppq = parse_midi(midi_path)

    if not notes:
        print(f"[midi2e2s] No notes found in {midi_path}")
        return

    # ── 歌词分配 ──
    lyric_list: list[str] = []
    if isinstance(lyrics_text, str) and os.path.isfile(lyrics_text):
        # 从文件读取
        with open(lyrics_text, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    lyric_list.extend(line.split())
    elif isinstance(lyrics_text, str):
        # 空格分隔的字符串
        lyric_list = lyrics_text.split()
    elif isinstance(lyrics_text, list):
        lyric_list = lyrics_text
    elif notes and notes[0].lyric:
        # 从 MIDI 文本事件中取的歌词
        lyric_list = [n.lyric for n in notes if n.lyric]

    # 如果歌词不够，用音名填充
    for i, note in enumerate(notes):
        if i < len(lyric_list):
            note.lyric = lyric_list[i]
        elif not note.lyric:
            note.lyric = midi_note_to_name(note.pitch).lower().replace('#', 's')

    # ── 写入 E2S ──
    with open(e2s_path, 'w', encoding='utf-8') as f:
        # 头部
        f.write(f'resampler=resampler.exe\n')
        f.write(f'wavtool=python wavtool.py\n')
        f.write(f'singer={singer}\n')
        f.write(f'phonemer={phonemer}\n')
        f.write(f'tempo={tempo_bpm}\n\n')

        # 每个音符
        for i, note in enumerate(notes, 1):
            length_e2s = ticks_to_e2s_ticks(
                note.end_tick - note.start_tick, ppq)
            pitch_name = midi_note_to_name(note.pitch)
            pitch_str = generate_pitch_string(length_e2s)

            f.write(f'{i}:\n')
            f.write(f'lyric={note.lyric}\n')
            f.write(f'phoneme={note.lyric}\n')
            f.write(f'crossfade={crossfade}\n')
            f.write(f'pitch={pitch_name}\n')
            f.write(f'velocity={velocity_default}\n')
            f.write(f'flags={flags}\n')
            f.write(f'length={length_e2s}\n')
            f.write(f'volume={volume_default}\n')
            f.write(f'modulation={modulation_default}\n')
            f.write(f'tempo={tempo_bpm}\n')
            f.write(f'pitch_string={pitch_str}\n\n')

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
    )


if __name__ == '__main__':
    main()
