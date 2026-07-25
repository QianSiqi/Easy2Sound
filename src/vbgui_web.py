#!/usr/bin/env python3
"""
vbgui_web.py — 音源制作 Web GUI 工具 (Flask)
============================================
启动: python vbgui_web.py
访问: http://localhost:5000
"""

import os
import re
import json
import subprocess
import sys
from pathlib import Path

from flask import Flask, render_template, request, jsonify, send_file, send_from_directory

app = Flask(__name__, template_folder='templates')

# ═══════════════════════════════════════════════════════════════════════
#  TextGrid 解析 (复用 vbgui.py 逻辑)
# ═══════════════════════════════════════════════════════════════════════

class TextGridInterval:
    __slots__ = ('xmin', 'xmax', 'text')
    def __init__(self, xmin=0.0, xmax=0.0, text=''):
        self.xmin = xmin
        self.xmax = xmax
        self.text = text
    def to_dict(self):
        return {'xmin': self.xmin, 'xmax': self.xmax, 'text': self.text}

class TextGridTier:
    __slots__ = ('name', 'xmin', 'xmax', 'intervals')
    def __init__(self, name='', xmin=0.0, xmax=0.0):
        self.name = name
        self.xmin = xmin
        self.xmax = xmax
        self.intervals = []
    def to_dict(self):
        return {
            'name': self.name, 'xmin': self.xmin, 'xmax': self.xmax,
            'intervals': [iv.to_dict() for iv in self.intervals]
        }

class TextGrid:
    def __init__(self):
        self.xmin = 0.0
        self.xmax = 0.0
        self.tiers = []
        self.file_path = None

    @staticmethod
    def parse(text):
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        tg = TextGrid()

        def _get_float(pattern, src, default=0.0):
            m = re.search(pattern, src)
            return float(m.group(1)) if m else default
        def _get_str(pattern, src, default=''):
            m = re.search(pattern, src)
            return m.group(1).strip('"') if m else default

        tg.xmin = _get_float(r'xmin\s*=\s*([\d.eE+-]+)', text, 0.0)
        tg.xmax = _get_float(r'xmax\s*=\s*([\d.eE+-]+)', text, 0.0)

        size_match = re.search(r'size\s*=\s*(\d+)', text)
        if not size_match:
            return tg

        item_pattern = re.compile(r'item\s*\[\s*\d+\s*\]:')
        parts = item_pattern.split(text)

        for part in parts[1:]:
            tier = TextGridTier()
            tier.name = _get_str(r'name\s*=\s*"([^"]*)"', part, 'default')
            tier.xmin = _get_float(r'xmin\s*=\s*([\d.eE+-]+)', part, 0.0)
            tier.xmax = _get_float(r'xmax\s*=\s*([\d.eE+-]+)', part, 0.0)

            int_pattern = re.compile(
                r'intervals\s*\[\s*\d+\s*\]:\s*'
                r'xmin\s*=\s*([\d.eE+-]+)\s*'
                r'xmax\s*=\s*([\d.eE+-]+)\s*'
                r'text\s*=\s*"([^"]*)"',
                re.DOTALL
            )
            for m in int_pattern.finditer(part):
                tier.intervals.append(TextGridInterval(
                    float(m.group(1)), float(m.group(2)), m.group(3).strip()))

            tg.tiers.append(tier)
        return tg

    @staticmethod
    def parse_file(path):
        with open(path, 'r', encoding='utf-8') as f:
            tg = TextGrid.parse(f.read())
        tg.file_path = path
        return tg

    def write(self):
        lines = [
            'File type = "ooTextFile"',
            'Object class = "TextGrid"',
            '', f'xmin = {self.xmin:.10f}', f'xmax = {self.xmax:.10f}',
            'tiers? <exists>', f'size = {len(self.tiers)}', 'item []:',
        ]
        for i, tier in enumerate(self.tiers):
            lines.append(f'    item [{i + 1}]:')
            lines.append(f'        class = "IntervalTier"')
            lines.append(f'        name = "{tier.name}"')
            lines.append(f'        xmin = {tier.xmin:.10f}')
            lines.append(f'        xmax = {tier.xmax:.10f}')
            lines.append(f'        intervals: size = {len(tier.intervals)}')
            for j, iv in enumerate(tier.intervals):
                lines.append(f'        intervals [{j + 1}]:')
                lines.append(f'            xmin = {iv.xmin:.10f}')
                lines.append(f'            xmax = {iv.xmax:.10f}')
                lines.append(f'            text = "{iv.text}"')
        return '\n'.join(lines)

    def to_dict(self):
        return {
            'xmin': self.xmin, 'xmax': self.xmax,
            'file_path': self.file_path,
            'tiers': [t.to_dict() for t in self.tiers]
        }

    @staticmethod
    def from_dict(d):
        tg = TextGrid()
        tg.xmin = d.get('xmin', 0.0)
        tg.xmax = d.get('xmax', 0.0)
        tg.file_path = d.get('file_path')
        for td in d.get('tiers', []):
            tier = TextGridTier(td['name'], td.get('xmin', 0.0), td.get('xmax', 0.0))
            for ivd in td.get('intervals', []):
                tier.intervals.append(TextGridInterval(ivd['xmin'], ivd['xmax'], ivd['text']))
            tg.tiers.append(tier)
        return tg


# ═══════════════════════════════════════════════════════════════════════
#  API 路由
# ═══════════════════════════════════════════════════════════════════════

@app.route('/')
def index():
    return render_template('vbgui.html')


@app.route('/api/browse', methods=['POST'])
def browse_directory():
    """浏览目录，返回文件夹和文件列表。"""
    data = request.get_json()
    dir_path = data.get('dir', os.path.expanduser('~'))

    if not os.path.isdir(dir_path):
        return jsonify({'error': 'Not a directory'}), 400

    entries = []
    try:
        for name in sorted(os.listdir(dir_path)):
            full = os.path.join(dir_path, name)
            entries.append({
                'name': name,
                'is_dir': os.path.isdir(full),
                'path': full.replace('\\', '/'),
            })
    except PermissionError:
        return jsonify({'error': 'Permission denied'}), 403

    return jsonify({
        'path': dir_path.replace('\\', '/'),
        'parent': os.path.dirname(dir_path).replace('\\', '/'),
        'entries': entries,
    })


@app.route('/api/project', methods=['POST'])
def load_project():
    """加载项目目录：扫描 TextGrid + WAV 文件。"""
    data = request.get_json()
    project_dir = data.get('dir', '')

    if not os.path.isdir(project_dir):
        return jsonify({'error': 'Not a directory'}), 400

    # TextGrid 目录：优先找子目录 TextGrid/
    tg_dir = os.path.join(project_dir, 'TextGrid')
    if not os.path.isdir(tg_dir):
        tg_dir = project_dir

    wav_dir = project_dir

    files = {}  # base_name → {textgrid: dict, has_audio: bool}

    # 扫描 TextGrid
    if os.path.isdir(tg_dir):
        for f in os.listdir(tg_dir):
            if f.lower().endswith('.textgrid'):
                path = os.path.join(tg_dir, f)
                try:
                    tg = TextGrid.parse_file(path)
                    base = os.path.splitext(f)[0]
                    files[base] = {
                        'textgrid': tg.to_dict(),
                        'has_audio': _find_wav(base, wav_dir) is not None,
                        'tg_path': path.replace('\\', '/'),
                    }
                except Exception as e:
                    print(f'[WARN] Failed to parse {f}: {e}')

    return jsonify({
        'project_dir': project_dir.replace('\\', '/'),
        'wav_dir': wav_dir.replace('\\', '/'),
        'tg_dir': tg_dir.replace('\\', '/'),
        'files': files,
    })


def _find_wav(base_name, wav_dir):
    if not os.path.isdir(wav_dir):
        return None
    for f in os.listdir(wav_dir):
        if f.lower().startswith(base_name.lower()) and f.lower().endswith('.wav'):
            return os.path.join(wav_dir, f)
    return None


@app.route('/api/textgrid/<base>', methods=['GET'])
def get_textgrid(base):
    """获取指定文件的 TextGrid。"""
    project_dir = request.args.get('project_dir', '')
    tg_dir = os.path.join(project_dir, 'TextGrid')
    if not os.path.isdir(tg_dir):
        tg_dir = project_dir

    path = os.path.join(tg_dir, f'{base}.TextGrid')
    if not os.path.isfile(path):
        # 尝试小写
        path = os.path.join(tg_dir, f'{base}.textgrid')
    if not os.path.isfile(path):
        return jsonify({'error': 'TextGrid not found'}), 404

    tg = TextGrid.parse_file(path)
    return jsonify(tg.to_dict())


@app.route('/api/textgrid/<base>', methods=['PUT'])
def save_textgrid(base):
    """保存 TextGrid。"""
    data = request.get_json()
    project_dir = data.get('project_dir', '')
    tg_dir = os.path.join(project_dir, 'TextGrid')
    if not os.path.isdir(tg_dir):
        tg_dir = project_dir

    tg = TextGrid.from_dict(data.get('textgrid', {}))
    out_path = os.path.join(tg_dir, f'{base}.TextGrid')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(tg.write())

    return jsonify({'ok': True, 'path': out_path.replace('\\', '/')})


@app.route('/api/audio/<base>')
def get_audio(base):
    """返回 WAV 文件供浏览器播放。"""
    project_dir = request.args.get('project_dir', '')
    wav_path = _find_wav(base, project_dir)
    if not wav_path:
        return jsonify({'error': 'Audio not found'}), 404
    return send_file(wav_path, mimetype='audio/wav')


@app.route('/api/build', methods=['POST'])
def run_build():
    """运行 build_singer.py。"""
    data = request.get_json()
    project_dir = data.get('project_dir', '')

    build_script = os.path.join(os.path.dirname(__file__), 'build_singer.py')
    if not os.path.isfile(build_script):
        build_script = os.path.join(project_dir, 'build_singer.py')
    if not os.path.isfile(build_script):
        return jsonify({'error': 'build_singer.py not found'}), 404

    out_dir = data.get('out_dir', os.path.join(project_dir, 'output'))
    tg_dir = data.get('tg_dir', os.path.join(project_dir, 'TextGrid'))
    if not os.path.isdir(tg_dir):
        tg_dir = project_dir

    try:
        proc = subprocess.Popen(
            [sys.executable, build_script, project_dir, out_dir, tg_dir],
            cwd=os.path.dirname(build_script),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        stdout, stderr = proc.communicate(timeout=30)
        return jsonify({
            'ok': proc.returncode == 0,
            'returncode': proc.returncode,
            'stdout': stdout.decode('utf-8', errors='replace'),
            'stderr': stderr.decode('utf-8', errors='replace'),
        })
    except subprocess.TimeoutExpired:
        proc.kill()
        return jsonify({'error': 'Build timed out (30s)'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    import threading
    import webview

    # Flask 在后台线程运行
    flask_thread = threading.Thread(
        target=lambda: app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False),
        daemon=True
    )
    flask_thread.start()

    # pywebview 打开窗口
    window = webview.create_window(
        'VBGui Web — 音源制作工具',
        'http://localhost:5000',
        width=1280, height=800,
        resizable=True,
        min_size=(800, 600),
    )
    webview.start()
