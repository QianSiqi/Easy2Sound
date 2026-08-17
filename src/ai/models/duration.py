# -*- coding: utf-8 -*-
"""
duration.py — 音素时长分配
==========================
第一版：统计时长表 + 乐谱缩放（不依赖神经网络）
- 从 data_cache/duration_table.json 读取每个音素的平均时长
- 给定目标总时长，按各音素统计时长的比例分配
进阶：可替换为神经网络时长预测（接口保持一致）
"""

import json
from pathlib import Path


class DurationModel:
    def __init__(self, table_path: Path):
        with open(table_path, encoding='utf-8') as f:
            self.table = json.load(f)
        # 兜底时长：所有音素均值（未收录音素用）
        self._fallback = float(sum(v['mean'] for v in self.table.values()) /
                               len(self.table)) if self.table else 0.3

    def mean_duration_ms(self, phoneme: str) -> float:
        """音素的统计平均时长（毫秒）"""
        entry = self.table.get(phoneme)
        return entry['mean'] * 1000.0 if entry else self._fallback * 1000.0

    def assign_durations_ms(self, phonemes, total_ms: float):
        """把 total_ms 按各音素的统计时长比例分配给音素序列。

        Args:
            phonemes: list[str]，音素序列
            total_ms: float，这一句/音符段的目标总时长（毫秒）
        Returns:
            list[float]，每个音素的时长（毫秒），之和 == total_ms
        """
        n = len(phonemes)
        if n == 0:
            return []
        means = [self.mean_duration_ms(p) for p in phonemes]
        total_mean = sum(means)
        if total_mean <= 0:
            per = total_ms / n
            return [per] * n
        # 按比例缩放，最后修正舍入误差
        durs = [total_ms * m / total_mean for m in means]
        durs[-1] += total_ms - sum(durs)
        return durs
