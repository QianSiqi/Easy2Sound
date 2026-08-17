# ai/ — Easy2Sound 自研 AI 歌声合成模块

完全 AI 合成（不依赖 DiffSinger 等现成框架）：
音素序列 → mel 生成 → NSF-HiFiGAN 声码器 → wav。

## 架构

```
乐谱(音符+音素) ─┬─> models/duration.py   音素时长分配（统计表）
                 ├─> models/f0.py         规则音高曲线（f0，供 vocoder）
                 ├─> render/renderer.py   mel 生成 + 拼接 + 调用 vocoder（M2 模板版）
                 └─> models/acoustic.py   神经声学模型（M3，帧级音素条件生成）
                                  │
                                  └─> models/vocoder.py → pc_nsf_hifigan → wav
```

- 音高完全由乐谱 f0 控制（vocoder 的 f0 输入），声学模型只学"音素 → mel 内容"
- 因此单音高采样数据（teto_roma）也能训练

## 目录

```
ai/
├── config.yaml                 # 配置（mel 参数与 vocoder 严格一致）
├── data/
│   ├── preprocess.py           # teto_roma wav+TextGrid → 数据缓存（M1）
│   └── dataset.py              # 帧级训练数据集 + 增强
├── models/
│   ├── duration.py             # 音素时长统计表 + 乐谱缩放
│   ├── f0.py                   # 规则 f0（滑音/颤音）
│   ├── acoustic.py             # 帧级声学模型（非自回归）
│   └── vocoder.py              # NSF-HiFiGAN onnx 推理封装
├── render/
│   └── renderer.py             # 渲染编排：乐谱 → mel → f0 → vocoder → wav
├── train/
│   └── train_acoustic.py       # 训练声学模型
└── server/
    └── ai_server.py            # Flask 8573 渲染服务（webui 对接）
```

## 使用步骤

```bash
cd src/ai

# 1. 预处理（M1）：teto_roma → data_cache/（音素表/时长表/样本/mel模板）
python data/preprocess.py

# 2. 渲染测试（M2 模板版，无需训练）：
python render/renderer.py        # 输出 demo.wav（"ka-o"）

# 3. 训练声学模型（M3，6-12GB 显卡，几分钟~几十分钟）
python train/train_acoustic.py --epochs 200

# 4. 启动 AI 渲染服务（webui 对接）
python server/ai_server.py --port 8573
```

## 依赖

numpy, scipy, soundfile, resampy, onnxruntime, torch, flask
（mel 提取优先用 util/wav2mel_numpy.py，不强制 librosa）

## 当前状态

- [x] M1 数据管线（preprocess.py）
- [x] M2 模板拼接渲染（renderer.py，可出声音）
- [x] M3 神经声学模型骨架（acoustic.py + train）
- [ ] M3 webui 集成（webui/app.py 加 ai_server 路由）
- [ ] M4 质量迭代（训练后切换 neural 模式）
