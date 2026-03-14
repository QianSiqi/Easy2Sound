import librosa
import numpy as np
import soundfile as sf
import os, sys

def crossfade(audio1, audio2, fade_duration_ms=50, sample_rate=22050):
    """
    对两个音频片段进行交叉淡化处理
    
    Args:
        audio1: 第一个音频数据
        audio2: 第二个音频数据
        fade_duration_ms: 交叉淡化持续时间（毫秒）
        sample_rate: 采样率
    
    Returns:
        交叉淡化后的拼接音频
    """
    # 将毫秒转换为秒，然后计算采样点数
    fade_seconds = fade_duration_ms / 1000.0
    fade_samples = int(fade_seconds * sample_rate)
    
    # 获取两个音频的末尾和开头部分用于交叉淡化
    if len(audio1) >= fade_samples and len(audio2) >= fade_samples:
        # 分别获取要进行交叉淡化的部分
        tail_of_first = audio1[-fade_samples:]
        head_of_second = audio2[:fade_samples]
        
        # 创建淡出和淡入的权重
        fade_out = np.linspace(1, 0, fade_samples)
        fade_in = np.linspace(0, 1, fade_samples)
        
        # 应用交叉淡化
        crossfaded = tail_of_first * fade_out + head_of_second * fade_in
        
        # 拼接结果：第一个音频的前面部分 + 交叉淡化区域 + 第二个音频的后面部分
        result = np.concatenate([
            audio1[:-fade_samples],  # 第一个音频去掉交叉淡化尾巴的部分
            crossfaded,              # 交叉淡化后的中间部分
            audio2[fade_samples:]    # 第二个音频去掉交叉淡化头部的部分
        ])
    else:
        # 如果音频太短，无法应用交叉淡化，则直接拼接
        result = np.concatenate([audio1, audio2])
    
    return result

def wavtool(wavs=[], output='', crossfade_durations_ms=None):
    """
    拼接多个音频文件，支持每个拼接点不同的交叉淡化时间（毫秒）
    
    Args:
        wavs: 音频文件路径列表
        output: 输出文件路径
        crossfade_durations_ms: 交叉淡化持续时间列表（毫秒），长度应为len(wavs)-1
                               如果为None，则所有拼接点使用默认50毫秒
    """
    if not wavs:
        print("没有提供音频文件")
        return
    
    if len(wavs) == 1:
        # 如果只有一个音频文件，直接复制它
        audio_data, sample_rate = librosa.load(wavs[0], sr=None)
        sf.write(output, audio_data, sample_rate)
        print(f"单个音频文件已复制到 {output}")
        return audio_data, sample_rate
    
    # 验证交叉淡化时间列表的长度是否正确
    if crossfade_durations_ms is None:
        crossfade_durations_ms = [50] * (len(wavs) - 1)  # 为每个拼接点使用默认值（50毫秒）
    elif len(crossfade_durations_ms) != len(wavs) - 1:
        print(f"警告: 提供了 {len(crossfade_durations_ms)} 个交叉淡化值，但需要 {len(wavs) - 1} 个")
        # 使用提供的值，不够的部分用默认值补充
        required_count = len(wavs) - 1
        if len(crossfade_durations_ms) < required_count:
            crossfade_durations_ms.extend([50] * (required_count - len(crossfade_durations_ms)))
        else:
            crossfade_durations_ms = crossfade_durations_ms[:required_count]
    
    # 加载第一个音频文件
    final_audio, sample_rate = librosa.load(wavs[0], sr=None)
    
    # 依次拼接后续音频文件
    for i in range(1, len(wavs)):
        # 加载当前音频文件
        current_audio, current_sr = librosa.load(wavs[i], sr=None)
        
        # 处理采样率不一致的情况
        if current_sr != sample_rate:
            current_audio = librosa.resample(current_audio, orig_sr=current_sr, target_sr=sample_rate)
        
        # 获取当前拼接点的交叉淡化时间（毫秒）
        current_crossfade_duration_ms = crossfade_durations_ms[i-1]
        
        # 对两个音频进行交叉淡化拼接
        final_audio = crossfade(final_audio, current_audio, current_crossfade_duration_ms, sample_rate)
        
        print(f"已拼接第{i}个音频文件，交叉淡化时间：{current_crossfade_duration_ms}毫秒")
    
    # 保存最终的音频文件
    if output and len(final_audio) > 0:
        sf.write(output, final_audio, sample_rate)
        print(f"音频已拼接并保存到 {output}")
    
    return final_audio, sample_rate

# 使用示例
if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python wavtool.py <input_wav1> <input_wav2> ... <output_wav> [crossfade1_ms] [crossfade2_ms] ...")
        print("Example: python wavtool.py audio1.wav audio2.wav audio3.wav output.wav 50 100")
        print("         (表示audio1和audio2之间用50毫秒交叉淡化，audio2和audio3之间用100毫秒交叉淡化)")
        sys.exit(1)
    
    # 解析命令行参数
    args = sys.argv[1:]
    
    # 从后往前查找可能的交叉淡化值（数字）
    crossfade_values_ms = []
    while len(args) > 2:  # 至少需要2个音频文件+1个输出文件
        try:
            # 尝试将最后一个参数解析为整数（毫秒通常用整数表示）
            cf_value = int(args[-1])
            crossfade_values_ms.insert(0, cf_value)  # 插入到列表开头以保持顺序
            args = args[:-1]  # 移除最后一个参数
        except ValueError:
            try:
                # 如果不是整数，尝试浮点数
                cf_value = float(args[-1])
                crossfade_values_ms.insert(0, cf_value)
                args = args[:-1]
            except ValueError:
                # 如果不是数字，则认为这是输出文件名，停止解析交叉淡化值
                break
    
    # 现在args应该包含音频文件和输出文件
    if len(args) < 2:
        print("错误: 至少需要一个输入音频文件和一个输出音频文件")
        sys.exit(1)
    
    audio_files = args[:-1]  # 除最后一个外的所有都是输入音频文件
    output_file = args[-1]   # 最后一个是输出文件
    
    # 验证输入文件是否存在
    for wav_file in audio_files:
        if not os.path.exists(wav_file):
            print(f"错误: 输入文件 '{wav_file}' 不存在")
            sys.exit(1)
    
    print(f"输入音频文件: {audio_files}")
    print(f"输出文件: {output_file}")
    print(f"交叉淡化时间: {crossfade_values_ms if crossfade_values_ms else '[使用默认值50毫秒]'}")
    
    # 调用wavtool函数
    wavtool(audio_files, output_file, crossfade_values_ms)