#!/usr/bin/env python3

import os
import sys
import json
import uuid
import shutil
import subprocess
import tempfile
import logging
import struct
import io
from pathlib import Path
from datetime import datetime

from flask import (
    Flask, render_template, request, jsonify, send_file,
    send_from_directory, abort
)

# ── 路径设置 ──────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent  # Main-Run
WEBUI_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = WEBUI_DIR / 'templates'
STATIC_DIR = WEBUI_DIR / 'static'
TMP_DIR = BASE_DIR / 'tmp'
VOICEBANK_DIRS = ['voicebank', 'voices', 'singers', 'Voicebanks']

SERVER_URL = 'http://127.0.0.1:8572'

app = Flask(
    __name__,
    template_folder=str(TEMPLATE_DIR),
    static_folder=str(STATIC_DIR),
)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB upload limit

logging.basicConfig(format='[WebUI] %(message)s', level=logging.INFO)
log = logging.getLogger(__name__)


# ── 项目状态管理 ──────────────────────────────────────────────────────

class Project:
    """内存中的项目状态"""

    def __init__(self):
        self.name = 'Untitled'
        self.bpm = 120.0
        self.beats_per_bar = 4
        self.beat_unit = 4
        self.tracks = []
        self.modified = False
        self.file_path = None
        self._init_default_track()

    def _init_default_track(self):
        self.tracks.append({
            'id': str(uuid.uuid4())[:8],
            'name': 'Track 1',
            'singer': '',
            'phonemer': '',
            'volume': 0.0,
            'pan': 0.0,
            'muted': False,
            'solo': False,
            'notes': [],
        })

    def to_dict(self):
        return {
            'name': self.name,
            'bpm': self.bpm,
            'beats_per_bar': self.beats_per_bar,
            'beat_unit': self.beat_unit,
            'tracks': self.tracks,
            'file_path': self.file_path,
            'modified': self.modified,
        }

    def from_dict(self, data):
        self.name = data.get('name', 'Untitled')
        self.bpm = data.get('bpm', 120.0)
        self.beats_per_bar = data.get('beats_per_bar', 4)
        self.beat_unit = data.get('beat_unit', 4)
        self.tracks = data.get('tracks', [])
        self.file_path = data.get('file_path')
        self.modified = False


project = Project()


# ── 路由：页面 ───────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/favicon.ico')
def favicon():
    return '', 204


# ── 路由：项目 API ───────────────────────────────────────────────────

@app.route('/api/project', methods=['GET'])
def get_project():
    return jsonify(project.to_dict())


@app.route('/api/project', methods=['POST'])
def save_project():
    data = request.get_json()
    if data:
        project.from_dict(data)
    return jsonify({'ok': True})


@app.route('/api/project/new', methods=['POST'])
def new_project():
    global project
    project = Project()
    return jsonify(project.to_dict())


@app.route('/api/project/open', methods=['POST'])
def open_project():
    """打开 .e2s 项目文件"""
    data = request.get_json()
    file_path = data.get('path', '')
    if not file_path or not os.path.exists(file_path):
        return jsonify({'error': 'File not found'}), 404

    ext = Path(file_path).suffix.lower()

    if ext == '.e2s':
        return _load_e2s(file_path)
    elif ext == '.mue2s':
        return _load_mue2s(file_path)
    elif ext == '.mid':
        return _load_midi(file_path)
    elif ext == '.json':
        return _load_json_project(file_path)
    elif ext == '.e2sp':
        return _load_json_project(file_path)
    else:
        return jsonify({'error': f'Unsupported format: {ext}'}), 400


@app.route('/api/project/save', methods=['POST'])
def save_project_to_file():
    """保存项目：.e2s 走 _write_e2s_file，其他走 JSON"""
    data = request.get_json()
    file_path = data.get('path', '')

    # 先用前端数据更新 project 对象
    if data:
        project.from_dict(data)

    if not file_path:
        file_path = str(TMP_DIR / f'{project.name}.e2s')

    os.makedirs(os.path.dirname(file_path) or '.', exist_ok=True)

    ext = Path(file_path).suffix.lower()
    if ext == '.e2s':
        # 找第一个非静音轨道保存
        track = None
        for t in project.tracks:
            if not t.get('muted'):
                track = t
                break
        if not track and project.tracks:
            track = project.tracks[0]
        if track:
            _write_e2s_file(
                file_path, track,
                singer=track.get('singer', ''),
                phonemer=track.get('phonemer', ''),
            )
        else:
            return jsonify({'error': '没有可保存的轨道'}), 400
    else:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(project.to_dict(), f, ensure_ascii=False, indent=2)

    project.file_path = file_path
    project.modified = False
    return jsonify({'ok': True, 'path': file_path})


def _load_e2s(file_path):
    """加载 E2S 文件"""
    try:
        sys.path.insert(0, str(BASE_DIR))
        from read_e2s import read_e2s
        notes_data = read_e2s(file_path, execute_phonemer=False)

        notes = []
        for n in notes_data:
            note = {
                'id': str(uuid.uuid4())[:8],
                'lyric': n.get('lyric', n.get('phoneme', '')),
                'phoneme': n.get('phoneme', ''),
                'pitch': 60,  # 默认 C4
                'length': int(float(n.get('length', 480))),
                'velocity': int(float(n.get('velocity', 100))),
                'start': 0,
                'flags': n.get('flags', ''),
                'offset': float(n.get('offset', 0)),
                'consonant': float(n.get('consonant', 0)),
                'cutoff': float(n.get('cutoff', 0)),
                'modulation': float(n.get('modulation', 0)),
                'pitch_string': n.get('pitchbend', ''),
                'intensity': n.get('intensity', '100'),
                'vib_start': n.get('vib_start', ''),
                'vib_end': n.get('vib_end', ''),
                'vib_hz': n.get('vib_hz', ''),
                'vib_hard': n.get('vib_hard', ''),
                'pt_x': n.get('pt_x', ''),
                'pt_y': n.get('pt_y', ''),
            }

            # 解析音高：优先 NoteNum (MIDI编号), 否则从 pitch 字段(如 "C4")转换
            pitch_str = n.get('NoteNum', n.get('note_num', ''))
            if pitch_str:
                try:
                    note['pitch'] = int(pitch_str)
                except (ValueError, TypeError):
                    note['pitch'] = _note_name_to_midi(str(pitch_str))
            else:
                pitch_name = n.get('pitch', 'C4')
                note['pitch'] = _note_name_to_midi(str(pitch_name))
            notes.append(note)

        # 计算每个音符的 start tick
        current_tick = 0
        tempo = 120.0
        for n in notes_data:
            if n.get('tempo'):
                try:
                    tempo = float(n['tempo'])
                except (ValueError, TypeError):
                    pass
        project.bpm = tempo

        # 从 read_e2s 的全局获取 singer 信息
        try:
            singer = sys.modules['read_e2s'].singer if hasattr(sys.modules.get('read_e2s', None), 'singer') else ''
        except Exception:
            singer = ''
        
        try:
            phonemer = sys.modules['read_e2s'].phonemer if hasattr(sys.modules.get('read_e2s', None), 'phonemer') else ''
        except Exception:
            phonemer = ''

        for i, note in enumerate(notes):
            note['start'] = current_tick
            current_tick += note['length']

        if project.tracks:
            project.tracks[0]['notes'] = notes
            project.tracks[0]['singer'] = singer
            project.tracks[0]['phonemer'] = phonemer
        else:
            project._init_default_track()
            project.tracks[0]['notes'] = notes

        project.name = Path(file_path).stem
        project.file_path = file_path
        project.modified = False
        return jsonify(project.to_dict())

    except Exception as e:
        log.error(f'Failed to load E2S: {e}')
        return jsonify({'error': str(e)}), 500


def _load_midi(file_path):
    """加载 MIDI 文件"""
    try:
        sys.path.insert(0, str(BASE_DIR))
        from midi2e2s import parse_midi
        notes, tempo_bpm, tempo_changes = parse_midi(file_path)

        project.bpm = tempo_bpm

        project_notes = []
        for n in notes:
            project_notes.append({
                'id': str(uuid.uuid4())[:8],
                'lyric': n.lyric or midi_to_note_name(n.pitch),
                'phoneme': '',
                'pitch': n.pitch,
                'length': n.end_tick - n.start_tick,
                'velocity': n.velocity,
                'start': n.start_tick,
                'flags': '',
                'offset': 0,
                'consonant': 0,
                'cutoff': 0,
                'modulation': 0,
                'pitch_string': '',
                'intensity': '100',
            })

        if project.tracks:
            project.tracks[0]['notes'] = project_notes
        else:
            project._init_default_track()
            project.tracks[0]['notes'] = project_notes

        project.name = Path(file_path).stem
        project.file_path = file_path
        project.modified = False
        return jsonify(project.to_dict())

    except Exception as e:
        log.error(f'Failed to load MIDI: {e}')
        return jsonify({'error': str(e)}), 500


def _load_json_project(file_path):
    """加载 JSON 项目文件"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        project.from_dict(data)
        project.file_path = file_path
        return jsonify(project.to_dict())
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def _load_mue2s(file_path):
    """加载 .mue2s 多轨文件"""
    try:
        current_blocks = []
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        track_mode = False
        current_track = {}

        for line in lines:
            line = line.strip()
            if line.endswith(':'):
                if track_mode and 'file' in current_track and 'volume' in current_track:
                    current_blocks.append(current_track.copy())
                track_mode = True
                current_track = {}
                continue
            if track_mode and '=' in line:
                key, value = line.split('=', 1)
                key, value = key.strip(), value.strip()
                if key in ('file', 'volume'):
                    current_track[key] = value

        if track_mode and 'file' in current_track and 'volume' in current_track:
            current_blocks.append(current_track)

        # 逐轨加载 e2s 文件
        project.tracks = []
        project.bpm = 120.0

        for i, block in enumerate(current_blocks):
            e2s_path = block['file']
            if not os.path.isabs(e2s_path):
                e2s_path = str(Path(file_path).parent / e2s_path)

            if not os.path.exists(e2s_path):
                log.warning(f'MUE2S track file not found: {e2s_path}')
                continue

            # 临时加载单轨 e2s
            saved_tracks = project.tracks[:]
            project.tracks = []
            _load_e2s(e2s_path)
            loaded_track = project.tracks[0] if project.tracks else None
            project.tracks = saved_tracks

            if loaded_track:
                loaded_track['name'] = f'Track {i + 1}'
                loaded_track['volume'] = float(block.get('volume', 0))
                project.tracks.append(loaded_track)

        if not project.tracks:
            project._init_default_track()

        project.name = Path(file_path).stem
        project.file_path = file_path
        project.modified = False
        return jsonify(project.to_dict())

    except Exception as e:
        log.error(f'Failed to load MUE2S: {e}')
        return jsonify({'error': str(e)}), 500


def _write_e2s_file(file_path, track, singer='', resampler='', wavtool='', phonemer=''):
    """将一个轨道写为 .e2s 文本格式"""
    lines = []
    lines.append(f'resampler={resampler}')
    lines.append(f'wavtool={wavtool}')
    lines.append(f'singer={singer}')
    if phonemer:
        lines.append(f'phonemer={phonemer}')
    lines.append(f'tempo={int(project.bpm)}')

    notes = sorted(track.get('notes', []), key=lambda n: n.get('start', 0))
    for i, note in enumerate(notes):
        lines.append(f'{i+1}:')
        lines.append(f'NoteNum={note.get("pitch", 60)}')
        lines.append(f'lyric={note.get("lyric", "")}')
        lines.append(f'phoneme={note.get("phoneme", "")}')
        lines.append(f'length={note.get("length", 480)}')
        lines.append(f'velocity={note.get("velocity", 100)}')
        lines.append(f'flags={note.get("flags", "")}')
        lines.append(f'offset={note.get("offset", 0)}')
        lines.append(f'consonant={note.get("consonant", 0)}')
        lines.append(f'cutoff={note.get("cutoff", 0)}')
        lines.append(f'modulation={note.get("modulation", 0)}')
        lines.append(f'intensity={note.get("intensity", "100")}')
        # 颤音参数
        vib_start = note.get('vib_start', '')
        vib_end = note.get('vib_end', '')
        vib_hz = note.get('vib_hz', '')
        vib_hard = note.get('vib_hard', '')
        if vib_start: lines.append(f'vib_start={vib_start}')
        if vib_end: lines.append(f'vib_end={vib_end}')
        if vib_hz: lines.append(f'vib_hz={vib_hz}')
        if vib_hard: lines.append(f'vib_hard={vib_hard}')
        # 音高控制点
        pt_x = note.get('pt_x', '')
        pt_y = note.get('pt_y', '')
        if pt_x: lines.append(f'pt_x={pt_x}')
        if pt_y: lines.append(f'pt_y={pt_y}')

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


def midi_to_note_name(midi):
    notes = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
    octave = (midi // 12) - 1
    return f"{notes[midi % 12]}{octave}"


def _note_name_to_midi(name):
    """将音名字符串 (如 'C4', 'D#5', 'Bb3') 转为 MIDI 编号"""
    import re
    name = name.strip()
    # 兼容各种写法: C4, C#4, Db4, C#5, Bb3, c4 等
    m = re.match(r'^([A-Ga-g])(#{1,2}|b{1,2})?(-?\d+)$', name)
    if not m:
        return 60  # 默认 C4
    base = m.group(1).upper()
    sharp_flat = m.group(2) or ''
    octave = int(m.group(3))
    note_map = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
    midi = note_map[base]
    # 升降号处理
    for ch in sharp_flat:
        if ch == '#':
            midi += 1
        elif ch == 'b':
            midi -= 1
    midi += (octave + 1) * 12
    return max(0, min(127, midi))


# ── 路由：轨道 API ───────────────────────────────────────────────────

@app.route('/api/tracks', methods=['GET'])
def get_tracks():
    return jsonify(project.tracks)


@app.route('/api/tracks', methods=['POST'])
def update_tracks():
    data = request.get_json()
    if isinstance(data, list):
        project.tracks = data
    return jsonify({'ok': True})


@app.route('/api/tracks/add', methods=['POST'])
def add_track():
    new_track = {
        'id': str(uuid.uuid4())[:8],
        'name': f'Track {len(project.tracks) + 1}',
        'singer': '',
        'phonemer': '',
        'volume': 0.0,
        'pan': 0.0,
        'muted': False,
        'solo': False,
        'notes': [],
    }
    project.tracks.append(new_track)
    return jsonify(project.to_dict())


@app.route('/api/tracks/<track_id>', methods=['DELETE'])
def delete_track(track_id):
    project.tracks = [t for t in project.tracks if t['id'] != track_id]
    return jsonify(project.to_dict())


# ── 路由：音符 API ───────────────────────────────────────────────────

@app.route('/api/tracks/<track_id>/notes', methods=['GET'])
def get_notes(track_id):
    for track in project.tracks:
        if track['id'] == track_id:
            return jsonify(track['notes'])
    return jsonify({'error': 'Track not found'}), 404


@app.route('/api/tracks/<track_id>/notes', methods=['POST'])
def update_notes(track_id):
    """批量更新音符（钢琴卷帘保存）"""
    data = request.get_json()
    for track in project.tracks:
        if track['id'] == track_id:
            if isinstance(data, list):
                track['notes'] = data
            project.modified = True
            return jsonify({'ok': True})
    return jsonify({'error': 'Track not found'}), 404


@app.route('/api/tracks/<track_id>/notes/add', methods=['POST'])
def add_note(track_id):
    data = request.get_json()
    for track in project.tracks:
        if track['id'] == track_id:
            note = {
                'id': str(uuid.uuid4())[:8],
                'lyric': data.get('lyric', ''),
                'phoneme': data.get('phoneme', ''),
                'pitch': data.get('pitch', 60),
                'length': data.get('length', 480),
                'velocity': data.get('velocity', 100),
                'start': data.get('start', 0),
                'flags': data.get('flags', ''),
                'offset': 0,
                'consonant': 0,
                'cutoff': 0,
                'modulation': 0,
                'pitch_string': '',
                'intensity': '100',
            }
            track['notes'].append(note)
            project.modified = True
            return jsonify(note)
    return jsonify({'error': 'Track not found'}), 404


@app.route('/api/tracks/<track_id>/notes/<note_id>', methods=['PUT'])
def update_note(track_id, note_id):
    data = request.get_json()
    for track in project.tracks:
        if track['id'] == track_id:
            for note in track['notes']:
                if note['id'] == note_id:
                    note.update(data)
                    project.modified = True
                    return jsonify(note)
    return jsonify({'error': 'Not found'}), 404


@app.route('/api/tracks/<track_id>/notes/<note_id>', methods=['DELETE'])
def delete_note(track_id, note_id):
    for track in project.tracks:
        if track['id'] == track_id:
            track['notes'] = [n for n in track['notes'] if n['id'] != note_id]
            project.modified = True
            return jsonify({'ok': True})
    return jsonify({'error': 'Not found'}), 404


# ── 路由：Phonemer API ───────────────────────────────────────────────

@app.route('/api/phonemer/list', methods=['GET'])
def get_phonemer_list():
    """扫描可用的 phonemer 工具"""
    phonemers = []
    for item in BASE_DIR.iterdir():
        if item.is_file() and item.suffix.lower() == '.exe':
            name_lower = item.name.lower()
            if 'ysq' in name_lower or 'dict' in name_lower:
                # 跳过 resampler
                if 'resampler' in name_lower:
                    continue
                label = item.stem
                # 给常见 phonemer 起中文标签
                labels = {
                    'ch-ddy-ysq': '中文音素',
                    'jp-ddy-ysq': '日文音素',
                    'ipa-ysq': 'IPA 音素',
                    'english_dict_lookup': '英文词典',
                }
                phonemers.append({
                    'name': item.name,
                    'label': labels.get(item.stem, label),
                })
    return jsonify(phonemers)


@app.route('/api/phonemer/run', methods=['POST'])
def run_phonemer():
    """对指定轨道执行 phonemer，返回更新后的音符数据"""
    data = request.get_json()
    track_id = data.get('track_id', '')
    phonemer_name = data.get('phonemer', '')
    track_data = data.get('track', None)  # 前端发送的完整 track 数据

    if not phonemer_name:
        return jsonify({'error': '未指定 phonemer'}), 400

    phonemer_path = BASE_DIR / phonemer_name
    if not phonemer_path.exists():
        return jsonify({'error': f'phonemer 不存在: {phonemer_name}'}), 404

    # 找到目标轨道，如果前端发送了完整 track 数据，优先使用
    track = None
    if track_data and track_data.get('id') == track_id:
        # 使用前端发送的 track 数据
        for t in project.tracks:
            if t['id'] == track_id:
                # 更新 track 的 notes 和 phonemer
                t['notes'] = track_data.get('notes', [])
                t['phonemer'] = phonemer_name
                track = t
                break
        if not track:
            # 如果后端没有这个 track，添加它
            project.tracks.append(track_data)
            track = track_data
    else:
        # 从 project.tracks 中查找
        for t in project.tracks:
            if t['id'] == track_id:
                track = t
                break
    
    if not track:
        return jsonify({'error': '轨道未找到'}), 404

    # 将用户选择的 phonemer 同步到后端轨道对象
    track['phonemer'] = phonemer_name
    
    # 备份原始 notes 数据（phonemer 会修改文件，可能删除字段）
    backup_notes = [n.copy() for n in track['notes']]
    log.info(f'Phonemer input: {len(backup_notes)} notes in track')
    for idx, n in enumerate(backup_notes[:3]):
        log.info(f'  [{idx}] id={n.get("id","")} lyric={n.get("lyric","")} pitch={n.get("pitch","")} start={n.get("start","")} length={n.get("length","")}')

    try:
        # 写临时 e2s 文件
        os.makedirs(TMP_DIR, exist_ok=True)
        tmp_e2s = str(TMP_DIR / f'phonemer_{track_id}.e2s')
        _write_e2s_file(tmp_e2s, track, singer=track.get('singer', ''),
                        phonemer=phonemer_name)
        
        # 检查写入的文件
        if os.path.exists(tmp_e2s):
            with open(tmp_e2s, 'r', encoding='utf-8') as f:
                content = f.read()
            log.info(f'Written e2s file ({len(content)} bytes):\n{content[:500]}')
        else:
            log.error(f'Failed to write e2s file: {tmp_e2s}')

        # 执行 phonemer
        log.info(f'Running phonemer: {phonemer_path} {tmp_e2s}')
        result = subprocess.run(
            [str(phonemer_path), tmp_e2s],
            capture_output=True, text=True, timeout=60,
            cwd=str(BASE_DIR),
        )
        log.info(f'Phonemer return code: {result.returncode}')
        if result.stdout:
            log.info(f'Phonemer stdout: {result.stdout}')
        if result.returncode != 0:
            log.warning(f'phonemer stderr: {result.stderr}')
        
        # 检查处理后的文件
        if os.path.exists(tmp_e2s):
            with open(tmp_e2s, 'r', encoding='utf-8') as f:
                content = f.read()
            log.info(f'After phonemer ({len(content)} bytes):\n{content[:500]}')
        else:
            log.error(f'e2s file missing after phonemer: {tmp_e2s}')

        # 重新读取临时文件以获取 phoneme 值
        sys.path.insert(0, str(BASE_DIR))
        from read_e2s import read_e2s
        notes_data = read_e2s(tmp_e2s, execute_phonemer=False)
        log.info(f'read_e2s returned {len(notes_data)} notes')

        # 把 phoneme 字段同步回轨道音符
        # 策略：按原始 notes 顺序一一对应，只更新 phoneme 和 lyric
        old_notes = backup_notes  # 使用备份
        log.info(f'Phonemer result: {len(notes_data)} notes from file, {len(old_notes)} notes in track')
        for idx, nd in enumerate(notes_data[:3]):
            log.info(f'  [{idx}] lyric={nd.get("lyric","")} phoneme={nd.get("phoneme","")} NoteNum={nd.get("NoteNum","")} length={nd.get("length","")}')
        
        # 按写入时的顺序（start 排序）建立映射
        sorted_old = sorted(enumerate(old_notes), key=lambda x: x[1].get('start', 0))
        
        # 从 phonemer 结果中提取 phoneme，按顺序对应
        phoneme_map = {}
        for i, n in enumerate(notes_data):
            if i < len(sorted_old):
                orig_idx = sorted_old[i][0]
                phoneme_map[orig_idx] = {
                    'phoneme': n.get('phoneme', ''),
                    'lyric': n.get('lyric', ''),
                }
        
        # 更新 notes
        final_notes = []
        for orig_idx, old_note in sorted_old:
            note = old_note.copy()
            if orig_idx in phoneme_map:
                note['phoneme'] = phoneme_map[orig_idx]['phoneme']
                if phoneme_map[orig_idx]['lyric']:
                    note['lyric'] = phoneme_map[orig_idx]['lyric']
            final_notes.append(note)
        
        track['notes'] = final_notes
        project.modified = True

        # 清理临时文件
        try:
            os.remove(tmp_e2s)
        except OSError:
            pass

        return jsonify(project.to_dict())

    except subprocess.TimeoutExpired:
        return jsonify({'error': 'phonemer 执行超时'}), 500
    except Exception as e:
        log.error(f'phonemer 执行失败: {e}')
        return jsonify({'error': str(e)}), 500


# ── 路由：音源管理 ───────────────────────────────────────────────────

@app.route('/api/singers', methods=['GET'])
def get_singers():
    """扫描可用音源目录"""
    singers = []

    # 扫描常见音源目录
    for vdir in VOICEBANK_DIRS:
        vb_path = BASE_DIR / vdir
        if vb_path.is_dir():
            for item in vb_path.iterdir():
                if item.is_dir():
                    info = _read_singer_info(item)
                    if info:
                        singers.append(info)

    # 也扫描子目录中的 e2s 音源
    for d in BASE_DIR.iterdir():
        if d.is_dir() and (d / 'oto.ini').exists():
            singers.append({
                'name': d.name,
                'path': str(d),
                'type': 'e2s',
            })

    return jsonify(singers)


def _read_singer_info(singer_dir):
    """读取音源信息"""
    info = {
        'name': singer_dir.name,
        'path': str(singer_dir),
        'type': 'unknown',
    }

    # 检查是否是 E2S/UTAU 音源
    if (singer_dir / 'oto.ini').exists():
        info['type'] = 'utau'
    elif any(singer_dir.glob('*.e2s')):
        info['type'] = 'e2s'
    elif (singer_dir / 'singer.yaml').exists():
        info['type'] = 'openutau'
        try:
            import yaml
            with open(singer_dir / 'singer.yaml', 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
            info['name'] = data.get('name', info['name'])
        except Exception:
            pass
    elif any(singer_dir.glob('*.wav')) or any(singer_dir.glob('*.oto')):
        info['type'] = 'voicebank'
    else:
        return None

    return info


# ── 路由：文件浏览 ───────────────────────────────────────────────────

@app.route('/api/files/browse', methods=['POST'])
def browse_files():
    data = request.get_json()
    dir_path = data.get('path', str(BASE_DIR))

    if not os.path.isdir(dir_path):
        return jsonify({'error': 'Invalid directory'}), 400

    items = []
    try:
        for item in sorted(Path(dir_path).iterdir()):
            items.append({
                'name': item.name,
                'path': str(item),
                'is_dir': item.is_dir(),
                'size': item.stat().st_size if item.is_file() else 0,
            })
    except PermissionError:
        return jsonify({'error': 'Permission denied'}), 403

    return jsonify({
        'current': dir_path,
        'parent': str(Path(dir_path).parent),
        'items': items,
    })


# ── 路由：文件上传 ───────────────────────────────────────────────────

@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400

    f = request.files['file']
    if not f.filename:
        return jsonify({'error': 'No filename'}), 400

    upload_dir = TMP_DIR / 'uploads'
    os.makedirs(upload_dir, exist_ok=True)

    save_path = upload_dir / f.filename
    f.save(str(save_path))

    ext = Path(f.filename).suffix.lower()

    if ext == '.mid':
        return _load_midi(str(save_path))
    elif ext == '.e2s':
        return _load_e2s(str(save_path))
    elif ext == '.mue2s':
        return _load_mue2s(str(save_path))
    elif ext == '.ust':
        return _load_ust(str(save_path))
    elif ext in ('.json', '.e2sp'):
        return _load_json_project(str(save_path))

    return jsonify({'ok': True, 'path': str(save_path)})


def _load_ust(file_path):
    """加载 UST 文件"""
    try:
        sys.path.insert(0, str(BASE_DIR))
        from ust2e2s import UstToE2sConverter
        converter = UstToE2sConverter()

        # UTAU UST标准编码为Shift-JIS，先尝试Shift-JIS再fallback utf-8
        raw = open(file_path, 'rb').read()
        for enc in ('shift_jis', 'utf-8', 'latin-1'):
            try:
                content = raw.decode(enc)
                break
            except (UnicodeDecodeError, LookupError):
                continue
        else:
            content = raw.decode('utf-8', errors='replace')

        ust_data = converter.parse_ust(content)
        notes = ust_data.get('notes', [])

        tempo = float(ust_data.get('settings', {}).get('Tempo', 120))
        project.bpm = tempo

        project_notes = []
        current_tick = 0
        for n in notes:
            note_num = n.get('NoteNum', 60)
            try:
                note_num = int(note_num)
            except (ValueError, TypeError):
                note_num = 60

            length = int(float(n.get('Length', 480)))
            lyric = n.get('Lyric', '').strip()
            # UST中R/r转为sil（与convert_to_e2s保持一致）
            if lyric.upper() == 'R' or lyric in converter.rest_markers:
                lyric = 'sil'
            velocity = int(float(n.get('Velocity', 100)))

            project_notes.append({
                'id': str(uuid.uuid4())[:8],
                'lyric': lyric,
                'phoneme': '',
                'pitch': note_num,
                'length': length,
                'velocity': velocity,
                'start': current_tick,
                'flags': n.get('Flags', ''),
                'offset': float(n.get('Offset', 0)),
                'consonant': float(n.get('Consonant', 0)),
                'cutoff': float(n.get('Cutoff', 0)),
                'modulation': float(n.get('Modulation', 0)),
                'pitch_string': n.get('PBType', ''),
                'intensity': n.get('Intensity', '100'),
            })
            current_tick += length

        if project.tracks:
            project.tracks[0]['notes'] = project_notes
        else:
            project._init_default_track()
            project.tracks[0]['notes'] = project_notes

        project.name = Path(file_path).stem
        project.file_path = file_path
        project.modified = False
        return jsonify(project.to_dict())

    except Exception as e:
        log.error(f'Failed to load UST: {e}')
        return jsonify({'error': str(e)}), 500


# ── 路由：MIDI 导出 ──────────────────────────────────────────────────

@app.route('/api/export/midi', methods=['POST'])
def export_midi():
    """将项目导出为 MIDI"""
    try:
        import mido
        from mido import MidiFile, MidiTrack, MetaMessage, Message

        mid = MidiFile(ticks_per_beat=480)
        track = MidiTrack()
        mid.tracks.append(track)

        tempo = mido.bpm2tempo(project.bpm)
        track.append(MetaMessage('set_tempo', tempo=tempo))

        for proj_track in project.tracks:
            if proj_track.get('muted'):
                continue
            # 构建事件列表 (absolute_tick, event)，然后转为 delta time
            events = []
            for note in proj_track['notes']:
                start = note['start']
                end = start + note['length']
                events.append((start, Message('note_on',
                    note=note['pitch'],
                    velocity=note.get('velocity', 100), time=0)))
                events.append((end, Message('note_off',
                    note=note['pitch'],
                    velocity=0, time=0)))
            # 按绝对 tick 排序，相同 tick 时 note_off 排前面
            events.sort(key=lambda e: (e[0], 0 if e[1].type == 'note_off' else 1))
            prev_tick = 0
            for abs_tick, msg in events:
                msg.time = abs_tick - prev_tick
                track.append(msg)
                prev_tick = abs_tick

        export_dir = TMP_DIR / 'exports'
        os.makedirs(export_dir, exist_ok=True)
        out_path = export_dir / f'{project.name}.mid'
        mid.save(str(out_path))

        return send_file(str(out_path), as_attachment=True,
                         download_name=f'{project.name}.mid')

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── 路由：E2S / MUE2S 导出 ─────────────────────────────────────────

@app.route('/api/export/e2s', methods=['POST'])
def export_e2s():
    """将当前轨道导出为 .e2s 文件"""
    try:
        data = request.get_json() or {}
        file_path = data.get('path', '')

        if not file_path:
            export_dir = TMP_DIR / 'exports'
            os.makedirs(export_dir, exist_ok=True)
            file_path = str(export_dir / f'{project.name}.e2s')

        _sync_project_from_request(data)

        # 默认用第一个非静音轨道
        track = None
        for t in project.tracks:
            if not t.get('muted'):
                track = t
                break
        if not track and project.tracks:
            track = project.tracks[0]
        if not track:
            return jsonify({'error': 'No track to export'}), 400

        singer = track.get('singer', '')
        phonemer = track.get('phonemer', '')
        _write_e2s_file(file_path, track, singer=singer, phonemer=phonemer)

        project.file_path = file_path
        project.modified = False
        return jsonify({'ok': True, 'path': file_path})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/export/mue2s', methods=['POST'])
def export_mue2s():
    """将多轨项目导出为 .mue2s + 各轨 .e2s"""
    try:
        data = request.get_json() or {}
        file_path = data.get('path', '')

        if not file_path:
            export_dir = TMP_DIR / 'exports'
            os.makedirs(export_dir, exist_ok=True)
            file_path = str(export_dir / f'{project.name}.mue2s')

        _sync_project_from_request(data)

        out_dir = Path(file_path).parent
        e2s_base = Path(file_path).stem
        lines = []

        for i, track in enumerate(project.tracks):
            track_name = f'{e2s_base}_track{i}'
            e2s_path = str(out_dir / f'{track_name}.e2s')
            _write_e2s_file(e2s_path, track, singer=track.get('singer', ''), phonemer=track.get('phonemer', ''))

            # mue2s 中 file 用相对路径
            rel_path = f'{track_name}.e2s'
            vol = track.get('volume', 0.0)

            lines.append(':')
            lines.append(f'file={rel_path}')
            lines.append(f'volume={vol}')

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')

        project.file_path = file_path
        project.modified = False
        return jsonify({'ok': True, 'path': file_path})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


def _sync_project_from_request(data):
    """从前端请求数据同步项目状态"""
    if 'name' in data:
        project.name = data['name']
    if 'bpm' in data:
        project.bpm = float(data['bpm'])
    if 'beats_per_bar' in data:
        project.beats_per_bar = int(data['beats_per_bar'])
    if 'tracks' in data:
        project.tracks = data['tracks']


# ── 路由：原生文件对话框 ──────────────────────────────────────────────

@app.route('/api/files/dialog', methods=['POST'])
def file_dialog():
    """原生文件对话框，纯浏览器模式下 fallback 为前端选择"""
    data = request.get_json()
    mode = data.get('mode', 'open')  # open | save
    file_types = data.get('file_types', (
        'E2S 项目 (*.e2s)',
        '多轨 E2S (*.mue2s)',
        'MIDI 文件 (*.mid)',
        'UST 文件 (*.ust)',
        'JSON 项目 (*.json;*.e2sp)',
        '所有文件 (*.*)',
    ))

    # 尝试 pywebview
    try:
        import webview
        w = _get_webview_window()
        if w:
            if mode == 'save':
                result = w.create_file_dialog(
                    webview.SAVE_DIALOG,
                    file_types=tuple(file_types),
                )
            else:
                result = w.create_file_dialog(
                    webview.OPEN_DIALOG,
                    file_types=tuple(file_types),
                    allow_multiple=False,
                )

            if result and len(result) > 0:
                return jsonify({'ok': True, 'path': result[0] if isinstance(result, (list, tuple)) else result})
            return jsonify({'ok': False})
    except Exception:
        pass

    # Fallback: 返回当前浏览目录，让前端用 <input type="file"> 或目录列表
    return jsonify({
        'ok': False,
        'fallback': True,
        'current_dir': str(BASE_DIR),
        'message': '原生对话框不可用，请使用文件选择器',
    })


def _get_webview_window():
    """获取当前 pywebview 窗口实例"""
    try:
        import webview
        windows = webview.windows
        if windows:
            return windows[0]
    except Exception:
        pass
    return None

@app.route('/api/preview', methods=['POST'])
def preview_note():
    """预览单个音符（调用 server.py 渲染）"""
    import requests as req
    data = request.get_json()
    log.info(f"Preview request: {data}")

    try:
        # 找到目标轨道和音符
        track_id = data.get('track_id', '')
        note_id = data.get('note_id', '')
        note_data = data.get('note', {})

        # 如果没传 note 对象，从 project 中查找
        if not note_data and track_id and note_id:
            for t in project.tracks:
                if t['id'] == track_id:
                    for n in t['notes']:
                        if n['id'] == note_id:
                            note_data = n
                            break
                    break

        if not note_data:
            return jsonify({'error': '未找到音符'}), 400

        # 获取 singer 和 phonemer
        singer = note_data.get('singer', '')
        phonemer = note_data.get('phonemer', '')
        if not singer and track_id:
            for t in project.tracks:
                if t['id'] == track_id:
                    singer = t.get('singer', '')
                    phonemer = t.get('phonemer', '')
                    break

        # 音符参数
        pitch = note_data.get('pitch', 60)
        if isinstance(pitch, int):
            # MIDI 编号转音名
            note_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
            octave = (pitch // 12) - 1
            pitch_str = f"{note_names[pitch % 12]}{octave}"
        else:
            pitch_str = str(pitch)

        velocity = note_data.get('velocity', 100)
        flags = note_data.get('flags', '')
        offset = note_data.get('offset', 0)
        length = note_data.get('length', 480)
        # length 是 ticks，转毫秒: ms = ticks * 60000 / (bpm * ticks_per_beat)
        length_ms = int(float(length) * 60000.0 / (project.bpm * 480))
        consonant = note_data.get('consonant', 0)
        cutoff = note_data.get('cutoff', 0)
        volume = note_data.get('intensity', '100')
        modulation = note_data.get('modulation', 0)
        tempo_str = f"!{int(project.bpm)}"
        pitch_string = note_data.get('pitch_string', '') or 'AA'

        # 找一个可用的音色样本文件 (.wav)
        wav_file = _find_sample_wav(singer)
        if not wav_file:
            return jsonify({'error': f'未找到音色样本 (singer: {singer})'}), 400

        # 写临时输出文件
        os.makedirs(TMP_DIR, exist_ok=True)
        out_wav = str(TMP_DIR / f'preview_{uuid.uuid4().hex[:8]}.wav')

        # 组装 server.py 的参数
        args = [
            str(wav_file),
            out_wav,
            pitch_str,
            str(velocity),
            flags,
            str(offset),
            str(length_ms),
            str(consonant),
            str(cutoff),
            str(volume),
            str(modulation),
            tempo_str,
            pitch_string,
        ]

        # 调用 server.py
        resp = req.post(SERVER_URL, data=' '.join(args), timeout=30)
        if resp.status_code != 200:
            return jsonify({'error': f'渲染失败: {resp.text}'}), 500

        # 返回音频文件
        return send_file(out_wav, mimetype='audio/wav',
                         as_attachment=False,
                         download_name='preview.wav')

    except req.ConnectionError:
        return jsonify({'error': '音频服务器未启动 (server.py)'}), 503
    except Exception as e:
        log.error(f'Preview error: {e}')
        return jsonify({'error': str(e)}), 500


def _find_sample_wav(singer):
    """查找音色目录中的一个样本 .wav 文件"""
    if not singer:
        return None

    # 在常见音源目录中搜索
    for vdir in VOICEBANK_DIRS:
        vb_path = BASE_DIR / vdir / singer
        if vb_path.is_dir():
            # 优先找 oto.ini 中定义的第一个样本
            oto_ini = vb_path / 'oto.ini'
            if oto_ini.exists():
                wav = _parse_oto_first_wav(oto_ini, vb_path)
                if wav:
                    return wav
            # fallback: 找第一个 wav
            for f in sorted(vb_path.iterdir()):
                if f.suffix.lower() == '.wav':
                    return f

    # 也搜索根目录下同名文件夹
    d = BASE_DIR / singer
    if d.is_dir():
        for f in sorted(d.iterdir()):
            if f.suffix.lower() == '.wav':
                return f

    return None


def _parse_oto_first_wav(oto_ini, base_dir):
    """从 oto.ini 解析第一个 wav 文件名"""
    try:
        with open(oto_ini, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                line = line.strip()
                if '=' in line:
                    wav_name = line.split('=', 1)[0].strip()
                    if wav_name.endswith('.wav'):
                        wav_path = base_dir / wav_name
                        if wav_path.exists():
                            return wav_path
    except Exception:
        pass
    return None


# ── 路由：工具命令 ───────────────────────────────────────────────────

@app.route('/api/command', methods=['POST'])
def run_command():
    """执行工具命令"""
    data = request.get_json()
    cmd = data.get('command', '')

    if cmd == 'midi2e2s':
        input_path = data.get('input', '')
        output_path = data.get('output', str(TMP_DIR / 'output.e2s'))
        try:
            result = subprocess.run(
                [sys.executable, str(BASE_DIR / 'midi2e2s.py'), input_path, output_path],
                capture_output=True, text=True, timeout=30
            )
            return jsonify({
                'ok': result.returncode == 0,
                'stdout': result.stdout,
                'stderr': result.stderr,
                'output': output_path,
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    return jsonify({'error': f'Unknown command: {cmd}'}), 400


# ── 启动 ─────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import threading
    import webview
    import yaml
    
    os.makedirs(TMP_DIR, exist_ok=True)
    
    HOST = '127.0.0.1'
    PORT = 5000
    URL = f'http://{HOST}:{PORT}'

    log.info(f'Starting Easy2Sound WebUI on {URL}...')
    log.info(f'Base dir: {BASE_DIR}')

    # Flask 跑在后台线程，关掉 debug 避免 reloader 冲突
    flask_thread = threading.Thread(
        target=lambda: app.run(host=HOST, port=PORT, debug=False, threaded=True),
        daemon=True,
    )
    flask_thread.start()

    # 等 Flask 就绪
    import time
    for _ in range(50):
        try:
            import urllib.request
            urllib.request.urlopen(URL, timeout=1)
            break
        except Exception:
            time.sleep(0.1)

    
    
    if '--no-browser' not in sys.argv[1:]:
        # 打开 pywebview 窗口
        window = webview.create_window(
            'Easy2Sound',
            URL,
            width=1400,
            height=900,
            min_size=(900, 600),
            text_select=False,
        )

        def _on_closed():
            log.info('WebView window closed, exiting.')
            os._exit(0)

        window.events.closed += _on_closed
        webview.start(debug=False)
