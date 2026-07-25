# Easy2Sound

一个免费、开源的歌声合成软件，基于 AI 技术实现高质量的声音合成。
（有AI编写成分）

## 目录

- [功能特性](#功能特性)
- [快速开始](#快速开始)
- [从源码构建](#从源码构建)
- [命令行参数](#命令行参数)
- [报错解决方案](#报错解决方案)
- [相关法律条文](#相关法律条文)
- [开发团队](#开发团队)

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

**本程序遵守 MIT 协议**

完整协议内容请参阅 [LICENSE](LICENSE) 文件。

**重要提醒：**

1. 您不得以任何方式盗用或倒卖此程序，否则我们将追究法律责任
2. 如需借用此程序，请署名且仅限非商业使用
3. 本软件为开源软件，任何收费行为均为盗版

---

## 开发团队

### 底层开发

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

---

## 许可证

本项目采用 MIT 许可证，详见 [LICENSE](LICENSE) 文件。
