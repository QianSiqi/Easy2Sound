# Easy2Sound

一个基于 **hifisampler** 二次开发的 UTAU 兼容歌声合成工具链（非官方、非关联项目）。

> ⚠️ 本项目渲染引擎（server / server_onnx / server_onnx_rs / resampler 客户端 / HN-SEP 模型）
> 均衍生自 [openhachimi/hifisampler](https://github.com/openhachimi/hifisampler)，遵循其开源许可；
> 自研部分为 e2s/mue2s 格式、WebUI 编辑器、多语言词典工具与音源制作工具。
> 详见下方 [上游项目与致谢](#上游项目与致谢)。
> ⚠️ 本项目有AI编写成分 ⚠️

## 目录

- [上游项目与致谢](#上游项目与致谢)
- [功能特性](#功能特性)
- [快速开始](#快速开始)
- [从源码构建](#从源码构建)
- [命令行参数](#命令行参数)
- [报错解决方案](#报错解决方案)
- [相关法律条文](#相关法律条文)
- [贡献者](#贡献者)

---

## 上游项目与致谢

本项目离不开以下开源项目的贡献，特此致谢：

| 项目 | 用途 | 许可证 |
|---|---|---|
| [openhachimi/hifisampler](https://github.com/openhachimi/hifisampler) | 渲染服务器（PyTorch/ONNX/Rust 版）、HN-SEP 分离、resampler 客户端 | 待确认（以仓库为准） |
| [openvpi/vocoders](https://github.com/openvpi/vocoders) | PC-NSF-HiFiGAN 声码器（44.1k/hop512/128bin） | 待确认（以仓库为准） |
| [UtaUtaUtau/straycat](https://github.com/UtaUtaUtau/straycat) | hifisampler 的上游（WORLD resampler） | 待确认（以仓库为准） |
| [wolfgitpr/HubertFA](https://relatedrepos.com/gh/wolfgitpr/HubertFA) | Hubert 强制对齐（音素边界 TextGrid） | 待确认（以仓库为准） |

> 各上游项目的许可证以其仓库内 LICENSE 文件为准；使用本项目包含的模型权重时，请一并遵守对应模型发布页的条款。

---

## 功能特性

- 基于 NSF-HiFiGAN 的高质量声码器
- 支持 ONNX 推理（无需 CUDA）
- 支持多语言音素转换（中文、日文、英文、IPA）
- 提供 WebUI 界面（未完成）
- 合成器客户端使用 Rust 编写，性能优异

---

## 快速开始

### 方式一：使用预编译版本

1. 下载最新版本的发行包
2. 解压后运行

### 方式二：从源码构建

#### 环境要求

- **Python** 3.10 或更高版本
- **Rust** 工具链（用于编译客户端）
- **Make**（用于批量构建）

#### 安装步骤

**1. 克隆仓库**

```bash
git clone https://github.com/QianSiqi/Easy2Sound.git
cd Easy2Sound
```

**2. 安装 Python 依赖**

```bash
cd src
pip install -r requirements.txt
```

**3. 启动服务端**

推荐使用 ONNX 版本（无需安装 PyTorch 和 CUDA）：

```bash
python server_onnx.py
```

如果需要使用 CUDA 加速，请先安装 PyTorch：

```bash
# 根据你的 CUDA 版本选择合适的命令
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu130
```

查看 CUDA 版本：

```bash
nvidia-smi
```

然后启动 CUDA 版本的服务端：

```bash
python server.py
```

**4. 构建 Rust 客户端**

```bash
cd src
make build
```

构建完成后会生成以下可执行文件：
- `resampler.exe` - 重采样器
- `english_dict_lookup.exe` - 英文词典查询
- `ch-ddy-ysq.exe` - 中文音素转换
- `jp-ddy-ysq.exe` - 日文音素转换
- `ipa-ysq.exe` - IPA 音素转换

---

## 命令行参数

客户端命令格式：

```bash
resampler <输入文件> <输出文件> <音高> <力度> [选项]
```

**参数说明：**

| 参数 | 说明 |
|------|------|
| `in_file` | 输入音频文件 |
| `out_file` | 输出音频文件 |
| `pitch` | 音高 |
| `velocity` | 力度 |

**可选参数：**

| 参数 | 说明 |
|------|------|
| `offset` | 偏移量 |
| `length` | 长度 |
| `consonant` | 辅音 |
| `cutoff` | 截止频率 |
| `volume` | 音量 |
| `modulation` | 调制 |
| `tempo` | 速度 |
| `pitch_string` | 音高字符串 |

---

## 报错解决方案

### 文件缺失

如果遇到文件缺失错误，请尝试重新下载软件。

### 程序无法运行

如果程序可以打开但无法运行，请尝试重新下载或重新安装依赖。

### 运行时错误

如果遇到运行时错误，请：
1. 检查 Python 版本是否为 3.10 或更高
2. 检查依赖是否完整安装
3. 尝试重新安装所有依赖
4. 联系开发人员获取帮助

---

## 相关法律条文

- 本项目**自研代码**采用 MIT 许可证，完整协议内容请参阅 [LICENSE](LICENSE) 文件。
- 本项目包含的**第三方代码与模型**版权归其原作者所有，使用、修改、再分发时请遵守各上游项目（见 [上游项目与致谢](#上游项目与致谢)）的许可证要求。
- 任何对第三方成果的再分发均不得移除或篡改原作者的版权声明。

---

## 贡献者

### 自研部分开发

- 钱思齐
- L7

### 意见部门

- Teto-Kasane（QQ：テト普照大地, 3473850198）
- 白糖の正义铃
- 叽里咕噜说啥我要开始闯了
- 少年?还是追逐?
- 水山
- 吟之和

### 采样组

- Leon Liu
- ECHO
- 皮塔豆子 pitabeans
- 人淡如菊
- 由奈_
- (^Antipathy^)

### UI 组

- 白师傅
- AAA足力健批发供应商
- 星空

### 音素器组

- 地月系月球

### 网页

- Spinglan
- Teto-Kasane

### 自动音高组

- Evidence"

### 上游致谢

渲染引擎、分离模型与声码器部分基于 [openhachimi/hifisampler](https://github.com/openhachimi/hifisampler)
及其上游 [straycat](https://github.com/UtaUtaUtau/straycat)、[openvpi/vocoders](https://github.com/openvpi/vocoders) 二次开发，特此感谢原作者。

---

## 许可证

本项目采用 MIT 许可证，详见 [LICENSE](LICENSE) 文件。
