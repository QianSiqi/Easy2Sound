#!/usr/bin/env python3
"""
vbgui.py — 音源制作 GUI 工具
================================
工作流：
  1. 用户用 SOFA/HURBURT-FA 生成 TextGrid 文件
  2. 本工具加载 TextGrid + 对应的 WAV 音频
  3. 左侧文件列表 → 右侧波形+音素编辑
  4. 拖拽边界线微调、编辑音素名、播放试听
  5. 保存 → 运行 build_singer.py 生成音源
"""

import sys
import os
import re
import json
import subprocess
import tempfile
from pathlib import Path
from collections import OrderedDict

import numpy as np

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QSplitter, QTreeWidget, QTreeWidgetItem,
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit,
    QSlider, QMessageBox, QFileDialog, QInputDialog, QToolBar, QStatusBar,
    QProgressBar, QMenu, QMenuBar, QAbstractItemView,
)
from PyQt6.QtCore import (
    Qt, QRectF, QPointF, pyqtSignal, QTimer, QEvent,
)
from PyQt6.QtGui import (
    QPainter, QPen, QColor, QBrush, QFont, QAction, QKeySequence,
    QMouseEvent, QWheelEvent, QPaintEvent,
)

import soundfile as sf
import sounddevice as sd


# ═══════════════════════════════════════════════════════════════════════
#  国际化 (i18n)
# ═══════════════════════════════════════════════════════════════════════

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'vbgui_config.json')
_LANG_DIR = os.path.join(os.path.dirname(__file__), 'lang')
_LANG_DATA: dict[str, str] = {}  # 当前语言的翻译表
_LANG_NAME = ''


def _load_config():
    """加载配置（含语言选择）。"""
    global _LANG_NAME
    try:
        with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        _LANG_NAME = cfg.get('language', 'zh')
    except Exception:
        _LANG_NAME = 'zh'


def _save_config():
    """保存配置。"""
    try:
        with open(_CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump({'language': _LANG_NAME}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f'[i18n] Failed to save config: {e}')


def _load_lang(lang: str = None):
    """加载指定语言的翻译文件。lang='zh'/'en' 或 None（使用配置）。"""
    global _LANG_DATA, _LANG_NAME
    if lang:
        _LANG_NAME = lang
    if not _LANG_NAME:
        _load_config()

    path = os.path.join(_LANG_DIR, f'{_LANG_NAME}.json')
    try:
        with open(path, 'r', encoding='utf-8') as f:
            _LANG_DATA = json.load(f)
    except FileNotFoundError:
        # 回退到中文
        fallback = os.path.join(_LANG_DIR, 'zh.json')
        with open(fallback, 'r', encoding='utf-8') as f:
            _LANG_DATA = json.load(f)
        _LANG_NAME = 'zh'
        print(f'[i18n] Language "{lang}" not found, falling back to zh')


def _tr(key: str) -> str:
    """翻译：key → 当前语言的文本。找不到 key 时返回 key 本身。"""
    return _LANG_DATA.get(key, key)


# 启动时加载
_load_lang()


class TextGridInterval:
    """单个音素/词区间。"""
    __slots__ = ('xmin', 'xmax', 'text')

    def __init__(self, xmin: float = 0.0, xmax: float = 0.0, text: str = ''):
        self.xmin = xmin
        self.xmax = xmax
        self.text = text

    @property
    def duration(self) -> float:
        return self.xmax - self.xmin

    def __repr__(self):
        return f'<Interval {self.text} [{self.xmin:.4f}-{self.xmax:.4f}]>'


class TextGridTier:
    """一个层（tier），含多个区间（intervals）。"""
    __slots__ = ('name', 'xmin', 'xmax', 'intervals')

    def __init__(self, name: str = '', xmin: float = 0.0, xmax: float = 0.0):
        self.name = name
        self.xmin = xmin
        self.xmax = xmax
        self.intervals: list[TextGridInterval] = []

    def add_interval(self, interval: TextGridInterval):
        self.intervals.append(interval)

    def __repr__(self):
        return f'<Tier "{self.name}" [{self.xmin:.4f}-{self.xmax:.4f}] {len(self.intervals)} intervals>'


class TextGrid:
    """完整的 Praat TextGrid。"""

    def __init__(self):
        self.xmin = 0.0
        self.xmax = 0.0
        self.tiers: list[TextGridTier] = []
        self.file_path: str | None = None

    @staticmethod
    def parse(text: str):
        """解析 TextGrid 文本（支持短/长格式）。"""
        # 统一换行
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        tg = TextGrid()

        # 提取 xmin/xmax
        def _get_float(pattern, src, default=0.0):
            m = re.search(pattern, src)
            return float(m.group(1)) if m else default

        def _get_str(pattern, src, default=''):
            m = re.search(pattern, src)
            return m.group(1).strip('"') if m else default

        tg.xmin = _get_float(r'xmin\s*=\s*([\d.eE+-]+)', text, 0.0)
        tg.xmax = _get_float(r'xmax\s*=\s*([\d.eE+-]+)', text, 0.0)

        # 提取 tiers
        size_match = re.search(r'size\s*=\s*(\d+)', text)
        if not size_match:
            return tg
        num_tiers = int(size_match.group(1))

        # 按 item[i] 分割
        item_pattern = re.compile(r'item\s*\[\s*\d+\s*\]:')
        parts = item_pattern.split(text)

        # parts[0] 是头部，parts[1:] 是各个 item
        for part in parts[1:]:
            tier = TextGridTier()
            tier.name = _get_str(r'name\s*=\s*"([^"]*)"', part, 'default')
            tier.xmin = _get_float(r'xmin\s*=\s*([\d.eE+-]+)', part, 0.0)
            tier.xmax = _get_float(r'xmax\s*=\s*([\d.eE+-]+)', part, 0.0)

            # 提取 intervals
            int_pattern = re.compile(
                r'intervals\s*\[\s*\d+\s*\]:\s*'
                r'xmin\s*=\s*([\d.eE+-]+)\s*'
                r'xmax\s*=\s*([\d.eE+-]+)\s*'
                r'text\s*=\s*"([^"]*)"',
                re.DOTALL
            )
            for m in int_pattern.finditer(part):
                xmin = float(m.group(1))
                xmax = float(m.group(2))
                text = m.group(3).strip()
                tier.add_interval(TextGridInterval(xmin, xmax, text))

            tg.tiers.append(tier)

        return tg

    @staticmethod
    def parse_file(path: str):
        """从文件读取 TextGrid。"""
        with open(path, 'r', encoding='utf-8') as f:
            tg = TextGrid.parse(f.read())
        tg.file_path = path
        return tg

    def write(self) -> str:
        """序列化为 TextGrid 文本。"""
        lines = [
            'File type = "ooTextFile"',
            'Object class = "TextGrid"',
            '',
            f'xmin = {self.xmin:.10f}',
            f'xmax = {self.xmax:.10f}',
            'tiers? <exists>',
            f'size = {len(self.tiers)}',
            'item []:',
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

    def write_file(self, path: str):
        with open(path, 'w', encoding='utf-8') as f:
            f.write(self.write())

    def get_tier_names(self) -> list[str]:
        return [t.name for t in self.tiers]

    def get_interval_at(self, tier_idx: int, time: float) -> int | None:
        """返回指定时间点所在的 interval 索引。"""
        if tier_idx < 0 or tier_idx >= len(self.tiers):
            return None
        for i, iv in enumerate(self.tiers[tier_idx].intervals):
            if iv.xmin <= time < iv.xmax:
                return i
        return None


# ═══════════════════════════════════════════════════════════════════════
#  WAV 加载与播放
# ═══════════════════════════════════════════════════════════════════════

class AudioPlayer:
    """
    wav 播放管理器。
    用固定临时文件 + winsound 播放，避免多次创建/删除导致的异常。
    """

    _TMP = os.path.join(tempfile.gettempdir(), '_vbgui_play.wav')
    _LOCK = os.path.join(tempfile.gettempdir(), '_vbgui_play.lock')

    def play(self, data: np.ndarray, sr: int,
             start_sec: float = 0.0, duration: float | None = None):
        if data is None or len(data) == 0:
            return
        self.stop()
        start = int(start_sec * sr)
        if duration:
            end = start + int(duration * sr)
            chunk = data[start:end]
        else:
            chunk = data[start:]
        if len(chunk) == 0:
            return
        # 写入固定临时文件（覆盖旧文件）
        sf.write(self._TMP, chunk, sr)
        import winsound
        winsound.PlaySound(self._TMP, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)

    def stop(self):
        import winsound
        winsound.PlaySound(None, winsound.SND_PURGE)

    @staticmethod
    def is_playing():
        return False


# ═══════════════════════════════════════════════════════════════════════
#  波形显示 + 音素边界编辑控件
# ═══════════════════════════════════════════════════════════════════════

class WaveformEditor(QWidget):
    """显示波形 + 音素边界线，支持拖拽调整。"""

    boundary_changed = pyqtSignal(int, int, float)  # tier_idx, interval_idx, new_xmax_time

    COLORS = {
        'bg': QColor(30, 30, 30),
        'waveform': QColor(100, 180, 255),
        'boundary': QColor(255, 200, 50),
        'boundary_drag': QColor(255, 100, 50),
        'text': QColor(220, 220, 220),
        'tier_bg': QColor(45, 45, 55),
        'interval_odd': QColor(55, 55, 70),
        'interval_even': QColor(65, 65, 80),
        'cursor': QColor(255, 80, 80),
        'selected': QColor(80, 120, 200, 80),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(300)
        self.setMouseTracking(True)

        # Audio data
        self._audio: np.ndarray | None = None
        self._sr: int = 44100
        self._duration: float = 0.0

        # View
        self._view_start: float = 0.0
        self._view_end: float = 1.0

        # TextGrid data
        self._tg: TextGrid | None = None
        self._active_tier: int = 0

        # Drag state
        self._dragging_boundary: tuple[int, int, int] | None = None  # (tier, interval, which_side)
        self._drag_start_x: float = 0.0
        self._drag_orig_time: float = 0.0

        # Layout metrics
        self._margin_left = 60
        self._margin_right = 20
        self._margin_top = 30
        self._tier_height = 50
        self._waveform_height = 120
        self._ruler_height = 25
        self._snap_distance = 0.003  # snap threshold in seconds
        self._boundary_hit = 10  # pixel threshold for boundary hit test

        # Cursor
        self._cursor_time: float = -1.0

        # Audio player
        self._player = AudioPlayer()

    def set_audio(self, audio: np.ndarray, sr: int):
        self._audio = audio
        self._sr = sr
        self._duration = len(audio) / sr if len(audio) > 0 else 0.0
        self._view_start = 0.0
        self._view_end = min(self._duration, 5.0)  # default 5s view
        self.update()

    def set_textgrid(self, tg: TextGrid | None):
        self._tg = tg
        if tg:
            if tg.tiers:
                self._active_tier = 0
                if tg.xmax > self._duration:
                    self._view_end = min(tg.xmax, self._duration)
        self.update()

    def set_active_tier(self, idx: int):
        if self._tg and 0 <= idx < len(self._tg.tiers):
            self._active_tier = idx
            self.update()

    def zoom_in(self):
        mid = (self._view_start + self._view_end) / 2
        span = (self._view_end - self._view_start) * 0.6
        self._view_start = mid - span / 2
        self._view_end = mid + span / 2
        self._clamp_view()
        self.update()

    def zoom_out(self):
        mid = (self._view_start + self._view_end) / 2
        span = (self._view_end - self._view_start) / 0.6
        self._view_start = mid - span / 2
        self._view_end = mid + span / 2
        self._clamp_view()
        self.update()

    def zoom_to_fit(self):
        self._view_start = 0.0
        self._view_end = self._duration
        self.update()

    def reset_view(self):
        self._view_start = 0.0
        self._view_end = min(self._duration, 5.0)
        self.update()

    def _clamp_view(self):
        span = self._view_end - self._view_start
        min_span = 0.01
        if span < min_span:
            mid = (self._view_start + self._view_end) / 2
            self._view_start = mid - min_span / 2
            self._view_end = mid + min_span / 2
        if self._view_start < 0:
            self._view_end -= self._view_start
            self._view_start = 0.0
        if self._view_end > max(self._duration, 0.01):
            self._view_start -= (self._view_end - max(self._duration, 0.01))
            self._view_end = max(self._duration, 0.01)
            self._view_start = max(0, self._view_start)

    # ── Coordinate conversion ──
    def _time_to_x(self, t: float) -> float:
        w = self.width() - self._margin_left - self._margin_right
        return self._margin_left + (t - self._view_start) / (self._view_end - self._view_start) * w

    def _x_to_time(self, x: float) -> float:
        w = self.width() - self._margin_left - self._margin_right
        frac = (x - self._margin_left) / w
        return self._view_start + frac * (self._view_end - self._view_start)

    def _tier_y(self, idx: int) -> float:
        return self._margin_top + self._waveform_height + 10 + idx * (self._tier_height + 4)

    # ── Paint ──
    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        plot_left = self._margin_left
        plot_right = w - self._margin_right
        plot_width = plot_right - plot_left

        # Background
        painter.fillRect(self.rect(), self.COLORS['bg'])

        if self._audio is None or len(self._audio) == 0:
            painter.setPen(self.COLORS['text'])
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, _tr('editor.no_audio'))
            return

        view_span = self._view_end - self._view_start
        if view_span <= 0:
            return

        # ── Ruler ──
        painter.setPen(QPen(self.COLORS['text'], 1))
        ruler_y = self._margin_top - self._ruler_height
        painter.fillRect(plot_left, ruler_y, plot_width, self._ruler_height,
                         QColor(40, 40, 45))
        # Time labels
        step = self._nice_time_step(view_span)
        t0 = np.ceil(self._view_start / step) * step
        t = t0
        while t <= self._view_end:
            x = self._time_to_x(t)
            painter.drawLine(int(x), int(ruler_y + 15), int(x), int(ruler_y + 20))
            painter.drawText(int(x) - 20, int(ruler_y), 40, 15,
                             Qt.AlignmentFlag.AlignCenter, f'{t:.2f}s')
            t += step

        # ── Waveform ──
        wave_top = self._margin_top
        wave_bottom = wave_top + self._waveform_height
        painter.fillRect(plot_left, wave_top, plot_width, self._waveform_height,
                         QColor(20, 20, 25))

        sr = self._sr
        start_sample = max(0, int(self._view_start * sr))
        end_sample = min(len(self._audio), int(self._view_end * sr))
        n_samples = end_sample - start_sample

        if n_samples > 1:
            chunk = self._audio[start_sample:end_sample]
            # Downsample for display
            max_pixels = plot_width * 3  # 3 sub-pixels per pixel
            if n_samples > max_pixels:
                step_s = n_samples // max_pixels
                chunk = chunk[::max(1, step_s)]

            mid_y = (wave_top + wave_bottom) / 2
            amp = (wave_bottom - wave_top) / 2 * 0.85
            max_val = max(np.abs(chunk).max(), 1e-9)

            painter.setPen(QPen(self.COLORS['waveform'], 1))
            n_draw = len(chunk)
            for i in range(1, n_draw):
                x1 = plot_left + i / n_draw * plot_width
                y1 = mid_y - (chunk[i] / max_val) * amp
                x0 = plot_left + (i - 1) / n_draw * plot_width
                y0 = mid_y - (chunk[i - 1] / max_val) * amp
                painter.drawLine(QPointF(x0, y0), QPointF(x1, y1))

        # ── Cursor line ──
        if self._cursor_time >= 0:
            cx = self._time_to_x(self._cursor_time)
            painter.setPen(QPen(self.COLORS['cursor'], 1, Qt.PenStyle.DashLine))
            painter.drawLine(int(cx), int(self._margin_top),
                             int(cx), int(self._tier_bottom()))

        # ── Tier boundaries ──
        if self._tg:
            for ti, tier in enumerate(self._tg.tiers):
                ty = self._tier_y(ti)
                th = self._tier_height

                # Tier background
                painter.fillRect(plot_left, int(ty), plot_width, int(th),
                                 self.COLORS['tier_bg'])

                # Tier label
                painter.setPen(self.COLORS['text'])
                painter.drawText(2, int(ty), int(self._margin_left - 4), int(th),
                                 Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                                 tier.name)

                # Intervals
                for ii, iv in enumerate(tier.intervals):
                    xl = self._time_to_x(max(iv.xmin, self._view_start))
                    xr = self._time_to_x(min(iv.xmax, self._view_end))

                    if xr <= plot_left or xl >= plot_right:
                        continue

                    bg = self.COLORS['interval_odd'] if ii % 2 == 0 else self.COLORS['interval_even']
                    painter.fillRect(int(xl), int(ty), int(xr - xl), int(th), bg)

                    # Text label
                    painter.setPen(self.COLORS['text'])
                    label_rect = QRectF(xl, ty, xr - xl, th)
                    painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, iv.text)

                    # Boundary line (right edge) — 所有的边界线都画出来
                    is_last = (ii == len(tier.intervals) - 1)
                    is_drag = (self._dragging_boundary is not None
                               and self._dragging_boundary[0] == ti
                               and self._dragging_boundary[1] == ii)
                    pen_color = self.COLORS['boundary_drag'] if is_drag else self.COLORS['boundary']
                    pen_width = 1 if is_last else 2
                    if not is_last:
                        painter.setPen(QPen(pen_color, pen_width))
                    else:
                        painter.setPen(QPen(self.COLORS['boundary'].darker(120), pen_width, Qt.PenStyle.DashLine))
                    # 最后一根线如果超出音频长度，画在音频末尾
                    bx_time = min(iv.xmax, self._duration) if is_last else iv.xmax
                    bx = self._time_to_x(bx_time)
                    painter.drawLine(int(bx), int(ty), int(bx), int(ty + th))

                # 第一个 interval 的左边界 (xmin)
                is_drag_left = (self._dragging_boundary is not None
                                and self._dragging_boundary[0] == ti
                                and self._dragging_boundary[1] == 0
                                and self._dragging_boundary[2] == 0)
                pen_left = self.COLORS['boundary_drag'] if is_drag_left else self.COLORS['boundary'].darker(120)
                painter.setPen(QPen(pen_left, 2, Qt.PenStyle.DashLine))
                bx0 = self._time_to_x(tier.intervals[0].xmin)
                painter.drawLine(int(bx0), int(ty), int(bx0), int(ty + th))

            # Bottom line of last tier
            painter.setPen(QPen(self.COLORS['boundary'].darker(150), 1))
            last_ty = self._tier_y(len(self._tg.tiers)) if self._tg.tiers else 0
            painter.drawLine(plot_left, int(last_ty + self._tier_height),
                             plot_right, int(last_ty + self._tier_height))

    def _tier_bottom(self) -> int:
        if self._tg and self._tg.tiers:
            last = self._tier_y(len(self._tg.tiers) - 1) + self._tier_height
            return int(last)
        return self._margin_top + self._waveform_height + 10

    def _nice_time_step(self, span: float) -> float:
        """Choose a nice step for ruler ticks."""
        for step in [0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0]:
            if span / step <= 20:
                return step
        return 10.0

    # ── Mouse events ──
    def mousePressEvent(self, event: QMouseEvent):
        x = event.position().x()
        y = event.position().y()
        t = self._x_to_time(x)

        if event.button() == Qt.MouseButton.LeftButton:
            # Check if clicking near a boundary line
            boundary = self._find_boundary(x, y)
            if boundary:
                self._dragging_boundary = boundary
                self._drag_start_x = x
                self._drag_orig_time = t
                self.setCursor(Qt.CursorShape.SizeHorCursor)
                self.update()
                return

            # Check if clicking in a tier → move cursor + maybe play
            if self._tg:
                for ti in range(len(self._tg.tiers)):
                    ty = self._tier_y(ti)
                    if ty <= y <= ty + self._tier_height:
                        self._cursor_time = t
                        # Play a short preview around the click
                        self._play_preview(t, 0.5)
                        self.update()
                        return

            # Click on waveform → cursor
            if self._margin_top <= y <= self._margin_top + self._waveform_height:
                self._cursor_time = t
                self._play_preview(t, 0.5)
                self.update()
                return

        elif event.button() == Qt.MouseButton.RightButton:
            # Right click → play full file from click point
            self._play_preview(t, None)

    def mouseMoveEvent(self, event: QMouseEvent):
        x = event.position().x()
        y = event.position().y()
        t = self._x_to_time(x)

        if self._dragging_boundary:
            ti, ii, side = self._dragging_boundary
            tier = self._tg.tiers[ti]

            if side == 1:
                # ── 拖拽右边界 (xmax) ──
                iv = tier.intervals[ii]
                is_last = (ii == len(tier.intervals) - 1)

                prev_xmax = tier.intervals[ii - 1].xmax if ii > 0 else tier.xmin
                # 最后一根线的上限是音频总时长，不是 tier.xmax（否则拖不动）
                max_allowed = self._duration if is_last else tier.xmax
                min_allowed = prev_xmax + 0.001

                new_time = max(min_allowed, min(max_allowed, t))

                # 吸附到其他层的边界
                if self._tg:
                    for ti2 in range(len(self._tg.tiers)):
                        if ti2 == ti:
                            continue
                        for iv2 in self._tg.tiers[ti2].intervals:
                            for bd in [iv2.xmin, iv2.xmax]:
                                if abs(t - bd) < self._snap_distance:
                                    new_time = max(min_allowed, min(max_allowed, bd))

                if abs(new_time - iv.xmax) > 0.0005:  # 更灵敏
                    iv.xmax = new_time
                    if not is_last:
                        if ii + 1 < len(tier.intervals):
                            tier.intervals[ii + 1].xmin = new_time
                    else:
                        tier.xmax = new_time
                    self.boundary_changed.emit(ti, ii, new_time)
                    self._cursor_time = new_time
                    self.update()

            elif side == 0:
                # ── 拖拽第一个 interval 的左边界 (xmin) ──
                iv0 = tier.intervals[0]
                max_allowed = iv0.xmax - 0.001
                min_allowed = 0.0

                new_time = max(min_allowed, min(max_allowed, t))

                # 吸附到其他层的边界
                if self._tg:
                    for ti2 in range(len(self._tg.tiers)):
                        if ti2 == ti:
                            continue
                        for iv2 in self._tg.tiers[ti2].intervals:
                            for bd in [iv2.xmin, iv2.xmax]:
                                if abs(t - bd) < self._snap_distance:
                                    new_time = max(min_allowed, min(max_allowed, bd))

                if abs(new_time - iv0.xmin) > 0.0005:
                    iv0.xmin = new_time
                    tier.xmin = new_time  # 同步 tier 起始时间
                    self._cursor_time = new_time
                    self.update()

        else:
            # Hover → check if near boundary
            b = self._find_boundary(x, y)
            if b:
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self._dragging_boundary:
            self._dragging_boundary = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.update()

    def wheelEvent(self, event: QWheelEvent):
        modifiers = event.modifiers()
        delta = event.angleDelta().y()

        if modifiers == Qt.KeyboardModifier.ControlModifier:
            # Zoom
            factor = 1.1 if delta > 0 else 1 / 1.1
            mid = (self._view_start + self._view_end) / 2
            span = (self._view_end - self._view_start) * factor
            self._view_start = mid - span / 2
            self._view_end = mid + span / 2
            self._clamp_view()
            self.update()
        else:
            # Scroll
            shift = (self._view_end - self._view_start) * 0.1
            if delta > 0:
                self._view_start -= shift
                self._view_end -= shift
            else:
                self._view_start += shift
                self._view_end += shift
            self._clamp_view()
            self.update()

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        """Double-click on an interval to rename it."""
        x = event.position().x()
        y = event.position().y()
        t = self._x_to_time(x)

        if self._tg:
            for ti in range(len(self._tg.tiers)):
                ty = self._tier_y(ti)
                if ty <= y <= ty + self._tier_height:
                    ii = self._tg.get_interval_at(ti, t)
                    if ii is not None:
                        old_text = self._tg.tiers[ti].intervals[ii].text
                        new_text, ok = QInputDialog.getText(
                            self, _tr('dialog.edit_phoneme'), _tr('dialog.edit_phoneme.label'),
                            text=old_text
                        )
                        if ok and new_text:
                            self._tg.tiers[ti].intervals[ii].text = new_text
                            self.update()
                    return

        # Double-click on waveform → play from there
        if self._margin_top <= y <= self._margin_top + self._waveform_height:
            self._play_preview(t, None)

    # ── Boundary detection ──
    def _find_boundary(self, x: float, y: float) -> tuple | None:
        """Find if click is near a tier boundary. Returns (tier_idx, interval_idx, side)."""
        if not self._tg:
            return None
        threshold = self._boundary_hit

        for ti, tier in enumerate(self._tg.tiers):
            ty = self._tier_y(ti)
            if not (ty <= y <= ty + self._tier_height):
                continue
            # 也可以拖拽最后一个 interval 的右边界
            # 检查右边界 (xmax) — 所有 interval
            for ii, iv in enumerate(tier.intervals):
                is_last = (ii == len(tier.intervals) - 1)
                # 最后一根线按音频末尾位置算（防止超长不匹配）
                hit_time = min(iv.xmax, self._duration) if is_last else iv.xmax
                bx = self._time_to_x(hit_time)
                if abs(x - bx) < threshold:
                    return (ti, ii, 1)
            # 检查第一个 interval 的左边界 (xmin)
            iv0 = tier.intervals[0]
            bx0 = self._time_to_x(iv0.xmin)
            if abs(x - bx0) < threshold:
                return (ti, 0, 0)  # side=0 表示左边界
        return None

    # ── Playback ──
    def _play_preview(self, start_sec: float, duration: float | None):
        if self._audio is not None:
            self._player.stop()
            self._player.play(self._audio, self._sr, start_sec, duration)

    def play_selection(self):
        """Play audio from cursor to view end or one second."""
        if self._cursor_time >= 0 and self._audio is not None:
            self._player.stop()
            self._player.play(self._audio, self._sr, self._cursor_time, 1.0)
        elif self._audio is not None:
            self._player.stop()
            self._player.play(self._audio, self._sr, 0.0, 1.0)

    def play_all(self):
        if self._audio is not None:
            self._player.stop()
            dur = self._view_end - self._view_start
            self._player.play(self._audio, self._sr, self._view_start, dur)

    def stop_playback(self):
        self._player.stop()

    def get_textgrid(self) -> TextGrid | None:
        return self._tg

    def closeEvent(self, event):
        self._player.stop()
        super().closeEvent(event)


# ═══════════════════════════════════════════════════════════════════════
#  主窗口
# ═══════════════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(_tr('window.title'))
        self.resize(1200, 800)

        # Data
        self._project_dir: str | None = None
        self._wav_dir: str = ''
        self._textgrid_dir: str = ''
        self._current_file: str | None = None
        self._textgrids: dict[str, TextGrid] = {}  # base_name → TextGrid
        self._audio_cache: dict[str, tuple[np.ndarray, int]] = {}

        self._current_wav_path: str | None = None

        self._setup_ui()
        self._setup_menu()

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(4, 4, 4, 4)

        # ── Top toolbar ──
        toolbar = QToolBar(_tr('toolbar.name'))
        self.addToolBar(toolbar)

        self._btn_load = QAction(_tr('toolbar.load'), self)
        self._btn_load.triggered.connect(self._load_project)
        toolbar.addAction(self._btn_load)

        self._btn_save = QAction(_tr('toolbar.save'), self)
        self._btn_save.setShortcut(QKeySequence.StandardKey.Save)
        self._btn_save.triggered.connect(self._save_current)
        toolbar.addAction(self._btn_save)

        self._btn_save_all = QAction(_tr('toolbar.save_all'), self)
        self._btn_save_all.triggered.connect(self._save_all)
        toolbar.addAction(self._btn_save_all)

        toolbar.addSeparator()

        self._btn_play = QAction(_tr('toolbar.play'), self)
        self._btn_play.triggered.connect(self._play_current)
        toolbar.addAction(self._btn_play)

        self._btn_stop = QAction(_tr('toolbar.stop'), self)
        self._btn_stop.triggered.connect(self._stop_playback)
        toolbar.addAction(self._btn_stop)

        toolbar.addSeparator()

        self._btn_zoom_in = QAction(_tr('toolbar.zoom_in'), self)
        self._btn_zoom_in.triggered.connect(self._zoom_in)
        toolbar.addAction(self._btn_zoom_in)

        self._btn_zoom_out = QAction(_tr('toolbar.zoom_out'), self)
        self._btn_zoom_out.triggered.connect(self._zoom_out)
        toolbar.addAction(self._btn_zoom_out)

        self._btn_fit = QAction(_tr('toolbar.zoom_fit'), self)
        self._btn_fit.triggered.connect(self._zoom_fit)
        toolbar.addAction(self._btn_fit)

        toolbar.addSeparator()

        # ── 语言切换按钮 ──
        self._btn_lang = QAction(_tr('toolbar.lang'), self)
        self._btn_lang.triggered.connect(self._toggle_lang)
        toolbar.addAction(self._btn_lang)

        toolbar.addSeparator()

        self._btn_build = QAction(_tr('toolbar.build'), self)
        self._btn_build.triggered.connect(self._run_build)
        toolbar.addAction(self._btn_build)

        # ── Main splitter ──
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: file tree
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel(f'<b>{_tr("tree.header")}</b>'))

        self._file_tree = QTreeWidget()
        self._file_tree.setHeaderHidden(True)
        self._file_tree.setAnimated(True)
        self._file_tree.itemClicked.connect(self._on_file_selected)
        left_layout.addWidget(self._file_tree)

        # Tier selector
        tier_layout = QHBoxLayout()
        tier_layout.addWidget(QLabel(_tr('tier.label')))
        self._tier_combo = QLineEdit()
        self._tier_combo.setPlaceholderText('Click tier name in editor')
        self._tier_combo.setReadOnly(True)
        tier_layout.addWidget(self._tier_combo)
        left_layout.addLayout(tier_layout)

        splitter.addWidget(left_widget)

        # Right: waveform editor
        self._editor = WaveformEditor()
        splitter.addWidget(self._editor)

        splitter.setSizes([250, 950])
        layout.addWidget(splitter)

        # ── Status bar ──
        self._status = QStatusBar()
        self._status_label = QLabel(_tr('status.no_project'))
        self._status.addWidget(self._status_label)
        self.setStatusBar(self._status)

        # ── Connect editor signals ──
        self._editor.boundary_changed.connect(self._on_boundary_changed)

    def _make_action(self, text: str, slot, shortcut=None):
        act = QAction(text, self)
        act.triggered.connect(slot)
        if shortcut:
            act.setShortcut(shortcut)
        return act

    def _setup_menu(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu(_tr('menu.file'))
        file_menu.addAction(self._make_action(_tr('menu.file.load'), self._load_project))
        file_menu.addAction(self._make_action(_tr('menu.file.save'), self._save_current,
                                               QKeySequence.StandardKey.Save))
        file_menu.addAction(self._make_action(_tr('menu.file.save_all'), self._save_all))
        file_menu.addSeparator()
        file_menu.addAction(self._make_action(_tr('menu.file.exit'), self.close))

        view_menu = menubar.addMenu(_tr('menu.view'))
        view_menu.addAction(self._make_action(_tr('menu.view.zoom_in'), self._zoom_in, QKeySequence('Ctrl++')))
        view_menu.addAction(self._make_action(_tr('menu.view.zoom_out'), self._zoom_out, QKeySequence('Ctrl+-')))
        view_menu.addAction(self._make_action(_tr('menu.view.fit'), self._zoom_fit, QKeySequence('Ctrl+0')))

        tools_menu = menubar.addMenu(_tr('menu.tools'))
        tools_menu.addAction(self._make_action(_tr('menu.tools.play'), self._play_current,
                                                QKeySequence('Space')))
        tools_menu.addAction(self._make_action(_tr('menu.tools.stop'), self._stop_playback, QKeySequence('Esc')))
        tools_menu.addSeparator()
        tools_menu.addAction(self._make_action(_tr('menu.tools.build'), self._run_build))
        tools_menu.addSeparator()
        tools_menu.addAction(self._make_action(_tr('menu.tools.about'), self._show_about))

        # ── 语言切换菜单 ──
        lang_menu = menubar.addMenu(_tr('menu.lang'))
        for code, label in [('zh', '中文'), ('en', 'English')]:
            act = self._make_action(label, lambda c=code: self._switch_lang(c))
            act.setCheckable(True)
            act.setChecked(code == _LANG_NAME)
            lang_menu.addAction(act)

    # ── Project loading ──
    def _load_project(self):
        dir_path = QFileDialog.getExistingDirectory(self, _tr('dialog.load_project'))
        if not dir_path:
            return

        self._project_dir = dir_path
        self._wav_dir = dir_path  # 选中的文件夹本身是音频目录
        self._textgrid_dir = os.path.join(dir_path, 'TextGrid')  # TextGrid 在子目录

        # 如果 TextGrid 子目录不存在，回退到选中目录直接找
        if not os.path.isdir(self._textgrid_dir):
            self._textgrid_dir = dir_path

        self._load_files()
        self._status_label.setText(_tr('status.project').format(dir_path))
        self._update_file_tree()

    def _load_files(self):
        self._textgrids.clear()
        self._audio_cache.clear()

        # Find all TextGrid files
        tg_dir = self._textgrid_dir
        if not os.path.isdir(tg_dir):
            return

        for f in sorted(os.listdir(tg_dir)):
            if f.lower().endswith('.textgrid'):
                path = os.path.join(tg_dir, f)
                try:
                    tg = TextGrid.parse_file(path)
                    base = os.path.splitext(f)[0]
                    self._textgrids[base] = tg
                except Exception as e:
                    print(f'[WARN] Failed to parse {f}: {e}')

        # Pre-load audio
        for base in list(self._textgrids.keys()):
            wav_path = self._find_wav(base)
            if wav_path:
                try:
                    data, sr = sf.read(wav_path)
                    if len(data.shape) > 1:
                        data = data.mean(axis=1)
                    self._audio_cache[base] = (data, sr)
                except Exception:
                    pass

    def _find_wav(self, base_name: str) -> str | None:
        """Find matching wav file for a given base name."""
        candidates = [
            os.path.join(self._wav_dir, f'{base_name}.wav'),
            os.path.join(self._wav_dir, f'{base_name}.WAV'),
        ]
        for p in candidates:
            if os.path.isfile(p):
                return p
        # Search in wav dir
        if os.path.isdir(self._wav_dir):
            for f in os.listdir(self._wav_dir):
                if f.lower().startswith(base_name.lower()) and f.lower().endswith('.wav'):
                    return os.path.join(self._wav_dir, f)
        return None

    def _update_file_tree(self):
        self._file_tree.clear()
        for base in sorted(self._textgrids.keys()):
            item = QTreeWidgetItem([base])
            tg = self._textgrids[base]
            for tier in tg.tiers:
                child = QTreeWidgetItem([f'  {tier.name} ({len(tier.intervals)} intervals)'])
                child.setData(0, Qt.ItemDataRole.UserRole, {'base': base, 'tier': tier.name})
                item.addChild(child)
            self._file_tree.addTopLevelItem(item)

    def _on_file_selected(self, item: QTreeWidgetItem, column: int):
        """当点击文件列表中的条目时加载对应的音频 + 编辑器。"""
        # Check if it's a top-level item (file) or child (tier)
        parent = item.parent()
        if parent:
            # Clicked on a tier
            base = item.data(0, Qt.ItemDataRole.UserRole)['base']
            tier_name = item.data(0, Qt.ItemDataRole.UserRole)['tier']
        else:
            base = item.text(0)
            tier_name = None

        tg = self._textgrids.get(base)
        if not tg:
            return

        # Find tier index
        if tier_name:
            for i, t in enumerate(tg.tiers):
                if t.name == tier_name:
                    self._editor.set_active_tier(i)
                    self._tier_combo.setText(_tr('editor.active_tier').format(tier_name, i))
                    break

        # Load audio
        wav_path = self._find_wav(base)
        self._current_file = base

        if wav_path and base in self._audio_cache:
            data, sr = self._audio_cache[base]
            self._editor.set_audio(data, sr)
            self._editor.set_textgrid(tg)

            self._current_wav_path = wav_path
            self._status_label.setText(_tr('status.file').format(base, os.path.basename(wav_path)))
        else:
            self._editor.set_audio(np.zeros(4410), 44100)
            self._editor.set_textgrid(tg)
            self._status_label.setText(_tr('status.file').format(base, '(no audio)'))

    # ── Actions ──
    def _save_current(self):
        if not self._current_file or self._current_file not in self._textgrids:
            return
        tg = self._editor.get_textgrid()
        if tg is None:
            return

        # Save to original location
        tg_dir = self._textgrid_dir
        if not os.path.isdir(tg_dir):
            tg_dir = self._project_dir

        out_path = os.path.join(tg_dir, f'{self._current_file}.TextGrid')
        tg.write_file(out_path)
        self._status_label.setText(_tr('status.saved').format(out_path))

    def _save_all(self):
        if not self._project_dir:
            QMessageBox.warning(self, _tr('dialog.no_project'), _tr('dialog.no_project.msg'))
            return
        for base, tg in self._textgrids.items():
            # Update from editor if it's the current file
            if base == self._current_file:
                editor_tg = self._editor.get_textgrid()
                if editor_tg:
                    tg = editor_tg

            tg_dir = self._textgrid_dir
            if not os.path.isdir(tg_dir):
                tg_dir = self._project_dir
            out_path = os.path.join(tg_dir, f'{base}.TextGrid')
            tg.write_file(out_path)

        QMessageBox.information(self, _tr('dialog.save_all.title'), _tr('dialog.save_all.msg').format(tg_dir))
        self._status_label.setText(_tr('status.saved_all').format(tg_dir))

    def _play_current(self):
        self._editor.play_selection()

    def _stop_playback(self):
        self._editor.stop_playback()

    def _zoom_in(self):
        self._editor.zoom_in()

    def _zoom_out(self):
        self._editor.zoom_out()

    def _zoom_fit(self):
        self._editor.zoom_to_fit()

    def _on_boundary_changed(self, tier_idx, interval_idx, new_time):
        if self._current_file and self._current_file in self._textgrids:
            self._status_label.setText(
                _tr('status.edited').format(self._current_file, self._textgrids[self._current_file].tiers[tier_idx].name, interval_idx, new_time)
            )

    def _run_build(self):
        """Run build_singer.py on the current project."""
        if not self._project_dir:
            QMessageBox.warning(self, _tr('dialog.no_project'), _tr('dialog.no_project.msg'))
            return

        # Save all first
        self._save_all()

        # Ask for output directory
        out_dir = QFileDialog.getExistingDirectory(self, _tr('dialog.build.outdir'),
                                                    self._project_dir)
        if not out_dir:
            return

        build_script = os.path.join(os.path.dirname(__file__), 'build_singer.py')
        if not os.path.isfile(build_script):
            # Try relative to proj
            build_script = os.path.join(self._project_dir, 'build_singer.py')
        if not os.path.isfile(build_script):
            QMessageBox.critical(self, _tr('dialog.build.error'))
            return

        # Run build_singer
        try:
            QMessageBox.information(self, 'Building',
                                    f'Running:\n'
                                    f'python {build_script}\n'
                                    f'   wav={self._wav_dir}\n'
                                    f'   out={out_dir}\n'
                                    f'   tg={self._textgrid_dir}\n\n'
                                    f'Check console for progress.')
            subprocess.Popen(
                [sys.executable, build_script, self._wav_dir, out_dir, self._textgrid_dir],
                cwd=os.path.dirname(build_script)
            )
        except Exception as e:
            QMessageBox.critical(self, _tr('dialog.build.error'), str(e))

    def _show_about(self):
        QMessageBox.about(self, _tr('dialog.about.title'), _tr('dialog.about.msg'))

    def _switch_lang(self, code: str):
        """切换到指定语言并刷新界面。"""
        global _LANG_NAME
        if code == _LANG_NAME:
            return
        _LANG_NAME = code
        _save_config()
        _load_lang(code)
        # 重建 UI
        self.clear_widgets()
        self._setup_ui()
        self._setup_menu()

    def clear_widgets(self):
        """清除旧 UI 组件，准备重建。"""
        # 移除旧工具栏
        for tb in self.findChildren(QToolBar):
            self.removeToolBar(tb)
        # 移除旧菜单栏
        self.menuBar().clear()
        # 移除旧状态栏
        sb = self.statusBar()
        if sb:
            sb.removeWidget(self._status_label)
        # 清空 central widget
        old = self.centralWidget()
        if old:
            old.setParent(None)

    def _toggle_lang(self):
        """在中/英之间切换。"""
        next_code = 'en' if _LANG_NAME == 'zh' else 'zh'
        self._switch_lang(next_code)


# ═══════════════════════════════════════════════════════════════════════
#  Entry point
# ═══════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
