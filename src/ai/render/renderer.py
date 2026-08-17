# -*- coding: utf-8 -*-
"""
renderer.py — M2 渲染编排（模板拼接 MVP）
==========================================
乐谱 → 每音素 mel 模板 → 按时长插值 → 拼接 → f0 → NSF-HiFiGAN → wav

这是"完全 AI 合成"的第一版渲染链路：
- mel 来自音素模板（后续被神经声学模型替换）
- 音高完全由乐谱 f0 控制（vocoder 的 f0 输入）
- 输出 wav 是 vocoder 神经重合成结果，非采样拼接

用法:
    from ai.render.renderer import Renderer
    r = Renderer()
    wav = r.render_notes([
        {'pitch': 60, 'start_ms': 0,    'length_ms': 600, 'phoneme': 'ka'},
        {'pitch': 62, 'start_ms': 600,  'length_ms': 600, 'phoneme': 'o'},
    ])
"""

import json
import sys
from pathlib import Path

import numpy as np

AI_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AI_DIR))

import yaml

from models.duration import DurationModel
from models.f0 import gen_f0, build_pitchbend_curve
from models.flags import parse_flags, apply_gender
from models.vocoder import Vocoder


class Renderer:
    def __init__(self, cache_dir: Path = None, vocoder: Vocoder = None,
                 mode: str = 'template', device: str = 'cuda',
                 singer: str = 'teto_roma'):
        self.cfg = yaml.safe_load((AI_DIR / 'config.yaml').read_text(encoding='utf-8'))
        self.singer = singer
        # singer 可以是音源名（如 teto_roma）或路径（如 .../src/teto_roma）
        singer_path = Path(singer)
        if singer_path.is_absolute() or len(singer_path.parts) > 1:
            self.singer_dir = singer_path
            self.singer_name = singer_path.name
        else:
            self.singer_dir = AI_DIR.parent / singer
            self.singer_name = singer
        self.cache_dir = (cache_dir or
                          (AI_DIR / self.cfg['data']['cache_dir'] / self.singer_name)).resolve()
        self.hop = self.cfg['mel']['hop_size']
        self.sr = self.cfg['data']['sample_rate']
        self.crossfade = self.cfg['render']['crossfade_frames']
        self.mode = mode
        self.sample_pitch = float(self.cfg['data'].get('sample_pitch', 63))
        self.mix_model = float(self.cfg['render'].get('mix_model', 0.4))
        self.singer_pitch = float(self.cfg['data'].get('singer_pitch', 66))

        # 加载音素表 + 时长表 + 模板
        self.phonemes = json.loads((self.cache_dir / 'phonemes.json').read_text(encoding='utf-8'))
        self.duration_model = DurationModel(self.cache_dir / 'duration_table.json')
        self.templates = {}
        for ph, idx in self.phonemes.items():
            p = self.cache_dir / 'templates' / f'{idx}.npz'
            if p.exists():
                self.templates[ph] = np.load(p)['mel']

        # 加载 samples 的子音素边界（TextGrid phones 层），用于辅音保持拉伸
        # （VCV 连续数据无子音素拆分时跳过，靠模型自身学习辅音）
        self.sub_phones = {}
        for p in sorted((self.cache_dir / 'samples').glob('*.npz')):
            d = np.load(p, allow_pickle=True)
            ph = str(d['phoneme'])
            if ph not in self.sub_phones and 'sub_phones' in d.files:
                sp = d['sub_phones']
                # sp: [(start_s, end_s, label_bytes), ...]
                if sp is not None and len(sp) >= 1:
                    self.sub_phones[ph] = sp

        # neural 模式：加载训练好的声学模型（按 singer 自动查找）
        self.acoustic = None
        if mode == 'neural':
            import torch
            from models.acoustic import SequenceAcousticModel
            ckpt_candidates = [
                self.singer_dir / 'acoustic.pt',                            # 音源目录内
                AI_DIR / 'checkpoints' / self.singer_name / 'acoustic.pt',  # 集中管理
                AI_DIR / 'checkpoints' / 'acoustic.pt',                     # 默认（兼容旧布局）
            ]
            ckpt_path = next((p for p in ckpt_candidates if p.exists()), None)
            if ckpt_path is None:
                raise FileNotFoundError(
                    f'no checkpoint for singer "{self.singer_name}" (looked in: '
                    + ', '.join(str(p) for p in ckpt_candidates)
                    + '). Run train/train_acoustic.py --singer {name} first')
            model = SequenceAcousticModel(
                n_phonemes=len(self.phonemes),
                phoneme_dim=self.cfg['model']['phoneme_dim'],
                hidden_dim=self.cfg['model']['hidden_dim'],
                n_mels=self.cfg['mel']['n_mels'],
            )
            st = torch.load(ckpt_path, map_location=device)
            model.load_state_dict(st['model'])
            model.to(device)
            model.eval()
            self.acoustic = model
            self.device = device
            print(f'[renderer] neural model: {ckpt_path}')

        self.vocoder = vocoder or Vocoder()

    # ── 乐谱 → 音素分段 ──
    def _plan_segments(self, notes, bpm):
        """按音符切分音素，分配时长，解析 flags/音高曲线。返回 segment 列表。"""
        segments = []
        for note in notes:
            phoneme = note.get('phoneme') or note.get('lyric') or 'a'
            total_ms = note['length_ms']
            durs = self.duration_model.assign_durations_ms([phoneme], total_ms)

            flags = parse_flags(note.get('flags', ''))
            pitchbend = build_pitchbend_curve(note, bpm) if bpm else None
            vib = None
            if note.get('vib_hz'):
                vib = {
                    'vib_start_ms': float(note.get('vib_start', 0) or 0),
                    'vib_end_ms': float(note.get('vib_end', 0) or 0),
                    'vib_hz': float(note.get('vib_hz', 5) or 5),
                    'vib_depth_semi': float(note.get('vib_hard', 0) or 0) / 10.0,
                }

            segments.append({
                'phoneme': phoneme,
                'dur_ms': durs[0],
                'pitch': note['pitch'],
                'start_ms': note['start_ms'],
                'transpose': flags.get('t', 0) / 100.0,   # t flag → 半音
                'gender': flags.get('g', 0) / 100.0,      # g flag → 半音（mel 域）
                'pitchbend': pitchbend,
                'vib': vib,
            })
        return segments

    # ── mel 时间轴插值辅助 ──
    @staticmethod
    def _interp_mel(mat, n):
        from scipy.interpolate import interp1d
        if mat.shape[1] == n:
            return mat
        if mat.shape[1] < 2:
            return np.repeat(mat, n, axis=1)
        return interp1d(np.linspace(0, 1, mat.shape[1]), mat, axis=1,
                        kind='linear')(np.linspace(0, 1, n)).astype(np.float32)

    def _cons_frames(self, ph):
        """音素的辅音段帧数（子音素/辅音区间），无信息返回 0"""
        sp = self.sub_phones.get(ph)
        if sp is None or len(sp) < 1:
            return 0
        cons_end_sec = float(sp[0][1])
        return max(1, int(round(cons_end_sec * self.sr / self.hop)))

    # ── 音素 mel 拉伸（辅音保持、元音拉伸） ──
    def _stretch_phoneme(self, tpl, ph, target_frames):
        """把音素模板拉伸到目标帧数。
        有辅音信息时：辅音段（首段）保持时长（最多占 1/3），元音段拉伸到剩余。
        无辅音信息：整体线性插值。
        """
        M = tpl.shape[1]

        sp = self.sub_phones.get(ph)
        if sp is None or len(sp) < 1 or target_frames <= 2:
            return self._interp_mel(tpl, target_frames)

        cons_frames = self._cons_frames(ph)
        cons_frames = min(cons_frames, M - 1)
        # 目标太短时整体压缩
        if target_frames <= cons_frames + 2:
            return self._interp_mel(tpl, target_frames)
        # 辅音最多占 1/3，避免元音过短
        cons_target = min(cons_frames, max(1, target_frames // 3))

        cons = self._interp_mel(tpl[:, :cons_frames], cons_target)
        vowel = self._interp_mel(tpl[:, cons_frames:], target_frames - cons_target)
        return np.concatenate([cons, vowel], axis=1)

    # ── 拼接 mel ──
    def _build_mel(self, segments, f0_full=None):
        """每音素模板/模型生成，crossfade 拼接 → (mel [n_mels, T], seg_ranges)。
        f0_full: 全曲 f0（占位帧坐标），neural 模式作为模型输入（f0 条件生成）。
        seg_ranges: 每段在拼接后 mel 中的实际 [start, end) 帧范围。
        """
        mel_parts = []
        n_mels = self.cfg['mel']['n_mels']
        frames_per_ms = self.sr / self.hop / 1000.0
        seg_ranges = []

        # 占位帧坐标（用于从 f0_full 切片）
        ph_frames = [max(1, int(round(seg['dur_ms'] * frames_per_ms))) for seg in segments]

        for si, seg in enumerate(segments):
            ph = seg['phoneme']
            target_frames = ph_frames[si]
            seg_start_ph = sum(ph_frames[:si])

            # 休止符：静音 mel（log 域低能量）
            if ph.lower() in ('r', 'sil', 'pau'):
                mel = np.full((n_mels, target_frames), -10.0, dtype=np.float32)
            else:
                if ph not in self.phonemes:
                    ph = 'a'  # 未收录音素回退到 'a'

                if self.acoustic is not None:
                    # neural：上下文 + f0 条件生成（参考 DiffSinger）
                    prev_ph = segments[si - 1]['phoneme'] if si > 0 else '#'
                    next_ph = segments[si + 1]['phoneme'] if si < len(segments) - 1 else '#'
                    if prev_ph.lower() in ('r', 'sil', 'pau'):
                        prev_ph = '#'
                    if next_ph.lower() in ('r', 'sil', 'pau'):
                        next_ph = '#'
                    pad = self.phonemes.get('#', 0)
                    prev_idx = self.phonemes.get(prev_ph, pad)
                    next_idx = self.phonemes.get(next_ph, pad)
                    ph_idx = self.phonemes[ph]
                    # 该段 f0（占位坐标切片）
                    seg_f0 = None
                    seg_energy = None
                    if f0_full is not None:
                        fs, fe = seg_start_ph, seg_start_ph + target_frames
                        if fe <= len(f0_full):
                            seg_f0 = f0_full[fs:fe]
                    if seg_f0 is not None:
                        # energy 包络：音符内渐入渐出（log 域，与训练 rms log 一致）
                        seg_energy = np.full(target_frames, 0.0, dtype=np.float32)
                        fi = max(1, int(target_frames * 0.18))
                        fo = max(1, int(target_frames * 0.12))
                        seg_energy[:fi] = np.linspace(-0.6, 0.0, fi)
                        seg_energy[-fo:] = np.linspace(0.0, -0.4, fo)
                    mel = self.acoustic.generate_mel(prev_idx, ph_idx, next_idx,
                                                     target_frames, seg_f0, self.device,
                                                     energy=seg_energy)
                    # 动态恢复（参考 DiffSinger 的归一化域）：模型输出被 L1 压缩
                    # 无静音谷底（训练数据无静音帧），强制拉伸到 vocoder 训练域 [-20, 5]，
                    # 制造静音/发声对比（否则 vocoder 每帧都发声 → 正弦波感）
                    # 频谱锐化（温和）：放大通道偏差增强共振峰（过度会金属感）
                    frame_mean = mel.mean(axis=0, keepdims=True)
                    mel = frame_mean + (mel - frame_mean) * 1.25
                    # 动态拉伸（温和，percentile 2-98）
                    m_lo = float(np.percentile(mel, 2))
                    m_hi = float(np.percentile(mel, 98))
                    if m_hi > m_lo:
                        mel = -18.0 + (mel - m_lo) / (m_hi - m_lo) * 22.0
                    # 增益补偿：抬高到真实歌声能量水平（适度）
                    # mel += (-4.5 - float(np.percentile(mel, 50)))  # 已移至拼接后通用处理
                    # mel 时间轻平滑（降嘶声/伪影）
                    mel_s = mel.copy()
                    mel_s[:, 1:-1] = (mel[:, :-2] + mel[:, 1:-1] + mel[:, 2:]) / 3.0
                    mel = mel_s
                    # mel 通道平滑（线性域！log 域平均会抬谷底产生浑浊）：
                    # 降低频谱包络粗糙（"咯痰"声源）
                    lin = np.exp(np.clip(mel, -25, 10))
                    lin_s = lin.copy()
                    lin_s[1:-1] = (lin[:-2] + lin[1:-1] + lin[2:]) / 3.0
                    mel = np.log(np.clip(lin_s, 1e-12, None)).astype(np.float32)
                    # 模板混合：模型 mel（连续性）+ 模板 mel（真实频谱/人声感）
                    # 比例由 config.render.mix_model 控制
                    tpl_mix = self.templates.get(ph, self.templates.get('a'))
                    if tpl_mix is not None and 0.0 < self.mix_model < 1.0:
                        tpl_m = self._stretch_phoneme(tpl_mix, ph, target_frames)
                        # 模板也做同样的动态拉伸，保证值域一致再混合
                        tm_lo = float(np.percentile(tpl_m, 1))
                        tm_hi = float(np.percentile(tpl_m, 99))
                        if tm_hi > tm_lo:
                            tpl_m = -20.0 + (tpl_m - tm_lo) / (tm_hi - tm_lo) * 25.0
                        mel = self.mix_model * mel + (1.0 - self.mix_model) * tpl_m
                    # 辅音融合（有辅音段标记时）
                    tpl = self.templates.get(ph, self.templates.get('a'))
                    cons_frames = self._cons_frames(ph)
                    if cons_frames > 0 and target_frames > 4:
                        cons_tpl = tpl if tpl is not None else self.templates.get('a')
                        cons_frames = min(cons_frames, cons_tpl.shape[1] - 1)
                        cons_target = min(cons_frames, max(1, target_frames // 3))
                        # 渐变混合：模板辅音开头强、向模型段递减，避免硬切跳变
                        cons_tpl = self._interp_mel(cons_tpl[:, :cons_frames], cons_target)
                        blend = np.linspace(1.0, 0.0, cons_target)[None, :]  # [1, cons_target]
                        mel[:, :cons_target] = (cons_tpl * blend
                                                + mel[:, :cons_target] * (1.0 - blend))
                        # 时间平滑前段，消除辅音起音的极端 mel 跳变（vocoder 爆音源）
                        n_smooth = min(cons_target + 2, mel.shape[1])
                        if n_smooth >= 3:
                            smoothed = mel[:, :n_smooth].copy()
                            for c in range(1, n_smooth - 1):
                                smoothed[:, c] = (mel[:, c - 1] + mel[:, c] + mel[:, c + 1]) / 3.0
                            mel[:, :n_smooth] = smoothed
                else:
                    # template：平均 mel 模板，辅音保持 + 元音拉伸
                    tpl = self.templates.get(ph, self.templates.get('a'))
                    mel = self._stretch_phoneme(tpl, ph, target_frames)
                    # 注：不做逐音符变调（apply_gender 的通道重采样会破坏真实 mel
                    # 的谐波梳状结构 → 马达声）。改为整曲整体移调（render_notes 中），
                    # mel 保持原样，f0 移调到演唱音域，谐波天然匹配。
            mel_parts.append(mel)

        # crossfade 拼接 + 记录实际段范围
        if not mel_parts:
            return np.zeros((n_mels, 1), dtype=np.float32), []
        if len(mel_parts) == 1:
            return mel_parts[0], [(0, mel_parts[0].shape[1])]

        cf = self.crossfade
        out = mel_parts[0]
        seg_ranges.append((0, out.shape[1]))
        pos = out.shape[1]
        for part in mel_parts[1:]:
            overlap = min(cf, out.shape[1], part.shape[1])
            if overlap <= 0:
                out = np.concatenate([out, part], axis=1)
                seg_ranges.append((pos, pos + part.shape[1]))
                pos += part.shape[1]
                continue
            # 线性交叉渐变
            ramp = np.linspace(0, 1, overlap, dtype=np.float32)
            merged = (out[:, -overlap:] * (1 - ramp) + part[:, :overlap] * ramp)
            out = np.concatenate([out[:, :-overlap], merged, part[:, overlap:]], axis=1)
            seg_ranges.append((pos - overlap, pos - overlap + part.shape[1]))
            pos = pos - overlap + part.shape[1]
        return out, seg_ranges

    # ── vocoder 前 mel 后处理：抑制电音伪影 ──
    def _postprocess_mel(self, mel: np.ndarray) -> np.ndarray:
        """衰减异常高频（log 域加负偏移）。
        注意：mel 为 log 域（负值），衰减 = 加负偏移（乘 <1 会增强负值，通道平滑会抬高谷底）。
        """
        mel = mel.copy()
        n_mels = mel.shape[0]
        # 高频衰减：mel 通道 95（≈6kHz）起渐变，最高通道衰减约 -1.2 log 单位（≈-10dB）
        hi0 = 95
        if n_mels > hi0 + 1:
            ramp = np.linspace(0.0, -1.2, n_mels - hi0, dtype=np.float32)[:, None]
            mel[hi0:] += ramp
        return mel

    # ── 主渲染 ──
    def render_notes(self, notes, bpm: float = 120.0) -> np.ndarray:
        """渲染音符列表 → wav [N] float32

        notes: list[dict]，每项支持
            pitch(MIDI), start_ms, length_ms, phoneme,
            flags(UTAU风格), pt_x/pt_y 或 pitch_string(音高曲线),
            vib_start/vib_end/vib_hz/vib_hard(颤音)
        """
        notes = list(notes)
        # 整体移调（template 模式）：把乐谱音高对齐到演唱音域（singer_pitch），
        # 使 mel 谐波与 f0 天然匹配（避免逐音符变调的谐波破坏）
        if self.mode == 'template' and self.singer_pitch:
            pitches = [n.get('pitch', 60) for n in notes if n.get('pitch')]
            if pitches:
                song_mean = sum(pitches) / len(pitches)
                shift_all = round(self.singer_pitch - song_mean)
                if shift_all != 0:
                    for n in notes:
                        n['pitch'] = n.get('pitch', 60) + shift_all
                    print(f'[renderer] 整体移调 {shift_all:+d} 半音（对齐演唱音域 {self.singer_pitch:.0f}）')

        segments = self._plan_segments(notes, bpm)
        if not segments:
            raise ValueError('no notes to render')

        # 占位 f0（按每音素目标帧数累计坐标），供模型 f0 条件生成
        frames_per_ms = self.sr / self.hop / 1000.0
        ph_frames = [max(1, int(round(seg['dur_ms'] * frames_per_ms))) for seg in segments]
        T_ph = sum(ph_frames)
        frame_segments_ph = []
        acc = 0
        for seg, tf in zip(segments, ph_frames):
            frame_segments_ph.append({
                'start_frame': acc, 'end_frame': acc + tf,
                'pitch': seg['pitch'], 'transpose': seg['transpose'],
                'pitchbend': seg['pitchbend'], 'vib': seg['vib'],
                'start_ms': seg['start_ms'], 'dur_ms': seg['dur_ms'],
            })
            acc += tf
        f0_ph = gen_f0(frame_segments_ph, T_ph, self.sr, self.hop)

        # mel 生成（模型以 f0 为条件）+ 实际拼接段范围
        mel, seg_ranges = self._build_mel(segments, f0_ph)

        # 通用增益补偿（template/neural 都生效）：
        # mel 帧均值校准到真实歌声水平，避免 vocoder 输出过弱
        mel += (-3.2 - float(np.percentile(mel, 50)))

        # 能量包络注入：模拟真实演唱的吐字起伏（起音渐入/尾音渐出/音符间 dip）
        # 我们的训练数据是平稳哼唱，无振幅包络 → vocoder 输出无起伏（正弦波感）
        env = np.zeros(mel.shape[1], dtype=np.float32)
        for seg, (s, e) in zip(segments, seg_ranges):
            n = e - s
            if n < 4:
                continue
            if seg['phoneme'].lower() in ('r', 'sil', 'pau'):
                continue  # 休止符已静音
            seg_env = np.zeros(n, dtype=np.float32)
            fade_in = max(1, int(n * 0.18))   # 起音渐入
            fade_out = max(1, int(n * 0.12))  # 尾音渐出
            seg_env[:fade_in] = np.linspace(-0.7, 0.0, fade_in)   # log 域 -0.7 ≈ -6dB
            seg_env[-fade_out:] = np.linspace(0.0, -0.5, fade_out)
            # 取最大（与相邻段重叠时自然形成 dip）
            env[s:e] = np.maximum(env[s:e], seg_env)
        mel = mel + env[None, :]

        # 辅音高频增强：真人数据（teto_sample）自带真实辅音，无需注入
        # （之前的程序注入会产生电音/卡顿，已禁用）
        # for seg, (s, e) in zip(segments, seg_ranges):
        #     if seg['phoneme'].lower() in ('r', 'sil', 'pau'):
        #         continue
        #     cf = self._cons_frames(seg['phoneme'])
        #     if cf > 0 and e - s > 4:
        #         c_end = min(s + cf, e)
        #         n = c_end - s
        #         ramp = np.linspace(1.0, 0.3, n)[None, :]
        #         mel[85:, s:c_end] += 0.8 * ramp
        #         mel[60:85, s:c_end] += 0.35 * ramp

        mel = self._postprocess_mel(mel)

        # gender flag：mel 频率轴重采样（变声）
        genders = [seg['gender'] for seg in segments if seg['gender'] != 0]
        if genders:
            mel = apply_gender(mel, genders[0])
            print(f'[renderer] applied gender shift: {genders[0]:+.2f} semitones')

        total_frames = mel.shape[1]

        # vocoder f0：按实际拼接段范围生成（与 mel 帧完全对齐）
        frame_segments = []
        for seg, (s, e) in zip(segments, seg_ranges):
            frame_segments.append({
                'start_frame': s, 'end_frame': e,
                'pitch': seg['pitch'], 'transpose': seg['transpose'],
                'pitchbend': seg['pitchbend'], 'vib': seg['vib'],
                'start_ms': seg['start_ms'], 'dur_ms': seg['dur_ms'],
            })
        f0 = gen_f0(frame_segments, total_frames, self.sr, self.hop)

        # vocoder 神经重合成
        wav = self.vocoder.synth(mel, f0)

        # 输出后处理：高频 tilt（轻微衰减极高频，降低"电子音"合成感）
        try:
            from scipy.signal import butter, sosfilt
            sos = butter(2, 11000, 'low', fs=self.sr, output='sos')
            wav = sosfilt(sos, wav).astype(np.float32)
        except Exception:
            pass

        # 轻量后处理：削峰 + 归一化
        peak = float(np.max(np.abs(wav))) if len(wav) else 0.0
        if peak > 0.95:
            wav = wav / peak * 0.95
        return wav.astype(np.float32)


def demo():
    """命令行演示：渲染"かお"（ka-o），输出 demo.wav
    演示功能：音高曲线（滑音）+ 颤音 + gender 变声
    用法: python render/renderer.py [--mode template|neural]"""
    import argparse
    import soundfile as sf
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', choices=['template', 'neural'], default='template')
    ap.add_argument('--device', default='cuda' if __import__('torch').cuda.is_available() else 'cpu')
    args = ap.parse_args()

    r = Renderer(mode=args.mode, device=args.device)
    notes = [
        # ka: C4，音高曲线滑音（0 → +1 半音），尾段颤音
        {'pitch': 60, 'start_ms': 0,   'length_ms': 600, 'phoneme': 'ka',
         'pt_x': '0,480', 'pt_y': '0,100',
         'vib_hz': 5.0, 'vib_hard': 3.0},
        # o: D4，gender -30（变声，mel 频率下移）
        {'pitch': 62, 'start_ms': 600, 'length_ms': 800, 'phoneme': 'o',
         'flags': 'g-30'},
    ]
    wav = r.render_notes(notes, bpm=120)
    out = AI_DIR / f'demo_{args.mode}.wav'
    sf.write(str(out), wav, r.sr)
    print(f'[DONE] [{args.mode}] rendered -> {out} ({len(wav) / r.sr:.2f}s)')


if __name__ == '__main__':
    demo()
