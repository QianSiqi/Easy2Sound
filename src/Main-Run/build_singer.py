import librosa
import soundfile as sf
import textgrid as tg
import numpy as np
import sys, os

def get_word(tg_path):
    tg_obj = tg.TextGrid.fromFile(tg_path)
    word_tier = None
    for tier in tg_obj.tiers:
        if tier.name.lower() == 'words':
            word_tier = tier
            break
    if word_tier is None:
        raise ValueError("No 'words' tier found in the TextGrid file.")
    
    words = []
    for interval in word_tier.intervals:
        if interval.mark.strip():
            words.append(interval.mark.strip())
    return words

def get_start_end(tg_path):
    tg_obj = tg.TextGrid.fromFile(tg_path)
    word_tier = None
    for tier in tg_obj.tiers:
        if tier.name.lower() == 'words':
            word_tier = tier
            break
    if word_tier is None:
        raise ValueError("No 'words' tier found in the TextGrid file.")
    
    start_times = []
    end_times = []
    for interval in word_tier.intervals:
        if interval.mark.strip():
            start_times.append(interval.minTime)
            end_times.append(interval.maxTime)
    return start_times, end_times

def remove_audio_segments_by_time(audio, sr, time_segments):
    """
    根据时间范围删除音频片段
    """
    # 按照时间倒序排列，避免删除前面的数据影响后续索引
    sorted_segments = sorted(time_segments, key=lambda x: x[0], reverse=True)
    
    modified_audio = audio.copy()
    
    for start_time, end_time in sorted_segments:
        start_sample = int(start_time * sr)
        end_sample = int(end_time * sr)
        
        # 删除指定时间段
        modified_audio = np.concatenate([
            modified_audio[:start_sample],
            modified_audio[end_sample:]
        ])
    
    return modified_audio

def find_matching_textgrid(textgrid_dir, audio_filename):
    """
    根据音频文件名查找匹配的TextGrid文件
    
    Parameters:
    - textgrid_dir: TextGrid文件所在的目录
    - audio_filename: 音频文件名（不含扩展名）
    
    Returns:
    - 匹配的TextGrid文件完整路径，如果没有找到则返回None
    """
    # 移除音频文件的扩展名，得到基础名称
    base_name = os.path.splitext(os.path.basename(audio_filename))[0]
    
    # 在TextGrid目录中搜索匹配的文件
    for file in os.listdir(textgrid_dir):
        if file.lower().endswith('.textgrid'):
            # 检查TextGrid文件名是否与音频文件名匹配（忽略大小写和扩展名）
            tg_base_name = os.path.splitext(file)[0]
            if tg_base_name.lower() == base_name.lower():
                return os.path.join(textgrid_dir, file)
    
    # 如果没找到完全匹配的，尝试其他匹配方式
    for file in os.listdir(textgrid_dir):
        if file.lower().endswith('.textgrid'):
            tg_base_name = os.path.splitext(file)[0]
            # 检查音频文件名是否包含TextGrid基础名或反之
            if tg_base_name.lower() in base_name.lower() or base_name.lower() in tg_base_name.lower():
                return os.path.join(textgrid_dir, file)
    
    return None

def split_CV_single(textgrid_path, wav_path, out_dir):
    """
    处理单个音频文件，去除开头和结尾的静音部分
    """
    word = get_word(textgrid_path)
    start_times, end_times = get_start_end(textgrid_path)
    x, sr = librosa.load(wav_path, sr=44100)
    
    # 计算需要删除的时段：从0到第一个start_time之前，以及最后一个end_time之后到音频结尾
    segments_to_remove = []
    
    # 添加从0到第一个start_time的部分
    if start_times:
        segments_to_remove.append((0, start_times[0]))
    
    # 添加从最后一个end_time到音频结束的部分
    if end_times:
        audio_duration = librosa.get_duration(y=x, sr=sr)
        last_end_time = end_times[-1]
        if last_end_time < audio_duration:
            segments_to_remove.append((last_end_time, audio_duration))
    
    # 删除指定的音频片段
    modified_audio = remove_audio_segments_by_time(x, sr, segments_to_remove)
    
    # 创建输出目录（如果不存在）
    os.makedirs(out_dir, exist_ok=True)
    
    # 生成输出文件名
    base_name = os.path.splitext(os.path.basename(wav_path))[0]
    output_path = os.path.join(out_dir, f"{word[0]}.wav")
    
    # 保存处理后的音频
    sf.write(output_path, modified_audio, sr)
    
    print(f"已处理音频: {wav_path}")
    print(f"  -> 对应TextGrid: {textgrid_path}")
    print(f"  -> 输出: {output_path}")
    print(f"  -> 原始时长: {librosa.get_duration(y=x, sr=sr):.2f}秒")
    print(f"  -> 处理后时长: {librosa.get_duration(y=modified_audio, sr=sr):.2f}秒")
    
    return output_path

def batch_split_CV(wavs_dir, out_dir, textgrid_dir):
    """
    批量处理音频文件
    
    Parameters:
    - wavs_dir: 包含音频文件的目录
    - out_dir: 输出目录
    - textgrid_dir: 包含TextGrid文件的目录
    """
    # 验证输入参数
    if not os.path.exists(wavs_dir):
        raise FileNotFoundError(f"音频目录不存在: {wavs_dir}")
    
    if not os.path.exists(textgrid_dir):
        raise FileNotFoundError(f"TextGrid目录不存在: {textgrid_dir}")
    
    # 创建输出目录
    os.makedirs(out_dir, exist_ok=True)
    
    # 获取所有音频文件
    audio_extensions = ['.wav']
    audio_files = []
    
    for file in os.listdir(wavs_dir):
        if any(file.lower().endswith(ext) for ext in audio_extensions):
            audio_files.append(os.path.join(wavs_dir, file))
    
    if not audio_files:
        print(f"在目录 {wavs_dir} 中未找到音频文件")
        return
    
    print(f"找到 {len(audio_files)} 个音频文件，开始批量处理...")
    print(f"TextGrid目录: {textgrid_dir}")
    print(f"输出目录: {out_dir}")
    print("-" * 70)
    
    # 处理每个音频文件
    success_count = 0
    error_count = 0
    no_match_count = 0
    
    for wav_path in audio_files:
        # 查找匹配的TextGrid文件
        matching_tg_path = find_matching_textgrid(textgrid_dir, os.path.basename(wav_path))
        
        if matching_tg_path is None:
            print(f"警告: 未找到与音频文件匹配的TextGrid文件: {wav_path}")
            no_match_count += 1
            continue
        
        try:
            output_path = split_CV_single(matching_tg_path, wav_path, out_dir)
            success_count += 1
        except Exception as e:
            print(f"处理失败: {wav_path}")
            print(f"错误信息: {str(e)}")
            error_count += 1
    
    print("-" * 70)
    print(f"批量处理完成!")
    print(f"成功处理: {success_count} 个文件")
    print(f"找不到匹配TextGrid: {no_match_count} 个文件")
    print(f"处理失败: {error_count} 个文件")
    
def make_meta_CV(wavs_dir):
    wavs=os.listdir(wavs_dir)
    f=open(f"{wavs_dir}/meta.txt",'w',encoding='utf-8')
    for wav in wavs:
        if not wav.endswith('.wav'):
            continue
        wavpath = os.path.join(wavs_dir, wav)
        f.write(f"{wav},{wav.split('.')[0]},0,50\n")
    f.close()
        
        # 使用示例
if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("用法: python build_singer.py <音频目录> <输出目录> <TextGrid目录>")
        sys.exit(1)
    wavs_dir = sys.argv[1]
    out_dir = sys.argv[2]
    textgrid_dir = sys.argv[3]
    batch_split_CV(wavs_dir, out_dir, textgrid_dir)
    make_meta_CV(out_dir)