# -*- coding: utf-8 -*-
"""
ai_server.py — AI 渲染服务（Flask，端口 8573）
===============================================
与 webui/app.py 对接：
  POST /render   乐谱 JSON → wav（返回 wav 文件）
  GET  /health   健康检查

乐谱 JSON 格式:
  {
    "bpm": 120,
    "notes": [
      {"pitch": 60, "start_ms": 0,   "length_ms": 600, "phoneme": "ka"},
      {"pitch": 62, "start_ms": 600, "length_ms": 800, "phoneme": "o"}
    ]
  }

渲染模式:
  - template: 使用音素 mel 模板拼接（M2，无需训练）
  - neural:   使用训练好的声学模型（M3，需 checkpoints/acoustic.pt）

用法:
    cd src/ai
    python server/ai_server.py --mode template --port 8573
"""

import argparse
import io
import json
import sys
from pathlib import Path

import numpy as np

AI_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AI_DIR))

from flask import Flask, jsonify, request, send_file

from render.renderer import Renderer

app = Flask(__name__)
renderer: Renderer = None
mode: str = 'template'


@app.route('/health')
def health():
    return jsonify({'ok': True, 'mode': mode, 'singers': ['teto_roma']})


@app.route('/render', methods=['POST'])
def render():
    try:
        data = request.get_json()
        if not data or 'notes' not in data:
            return jsonify({'error': 'missing notes'}), 400
        bpm = float(data.get('bpm', 120))
        notes = []
        for n in data['notes']:
            notes.append({
                'pitch': int(n.get('pitch', 60)),
                'start_ms': float(n.get('start_ms', 0)),
                'length_ms': float(n.get('length_ms', 480)),
                'phoneme': n.get('phoneme') or n.get('lyric') or 'a',
                'flags': n.get('flags', ''),
                'pt_x': n.get('pt_x', ''),
                'pt_y': n.get('pt_y', ''),
                'pitch_string': n.get('pitch_string', ''),
                'vib_start': n.get('vib_start', ''),
                'vib_end': n.get('vib_end', ''),
                'vib_hz': n.get('vib_hz', ''),
                'vib_hard': n.get('vib_hard', ''),
            })
        wav = renderer.render_notes(notes, bpm=bpm)
        buf = io.BytesIO()
        import soundfile as sf
        sf.write(buf, wav, renderer.sr, format='WAV')
        buf.seek(0)
        return send_file(buf, mimetype='audio/wav', download_name='render.wav')
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def main():
    global renderer, mode
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8573)
    ap.add_argument('--mode', choices=['template', 'neural'], default='template')
    ap.add_argument('--singer', default='teto_roma', help='AI 音源名（加载对应 checkpoint）')
    args = ap.parse_args()
    mode = args.mode
    renderer = Renderer(mode=args.mode, singer=args.singer)
    print(f'[ai_server] mode={mode} singer={args.singer} listening on :{args.port}')
    app.run(host='127.0.0.1', port=args.port, debug=False, threaded=True)


if __name__ == '__main__':
    main()
