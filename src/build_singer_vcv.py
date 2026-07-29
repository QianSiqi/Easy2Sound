import librosa
import soundfile as sf
import textgrid as tg
import numpy as np
import sys, os

def get_words_and_times(tg_path):
    tg_obj = tg.TextGrid.fromFile(tg_path)
    # 优先读 phones tier（有完整 VCV 标注如 "a bi"）
    phone_tier = None
    for tier in tg_obj.tiers:
        if tier.name.lower() == 'phones':
            phone_tier = tier
            break
    if phone_tier is None:
        raise ValueError("No 'phones' tier found in the TextGrid file.")

    words = []
    start_times = []
    end_times = []
    for interval in phone_tier.intervals:
        if interval.mark.strip():
            words.append(interval.mark.strip())
            start_times.append(interval.minTime)
            end_times.append(interval.maxTime)
    return words, start_times, end_times

def detect_vowel_onset(audio, sr):
    """检测元音起始位置（RMS能量首次显著上升的点）"""
    if len(audio) < sr * 0.02:
        return 0

    hop_length = 512
    rms = librosa.feature.rms(y=audio, hop_length=hop_length)[0]
    frames_time = librosa.frames_to_time(range(len(rms)), sr=sr, hop_length=hop_length)

    threshold = np.max(rms) * 0.15
    onset_idx = np.argmax(rms > threshold)

    if onset_idx > 0:
        onset_time = frames_time[onset_idx]
    else:
        onset_time = len(audio) / sr * 0.2

    return int(onset_time * sr)

def split_VCV_single(textgrid_path, wav_path, out_dir):
    words, start_times, end_times = get_words_and_times(textgrid_path)
    x, sr = librosa.load(wav_path, sr=44100)
    audio_duration = len(x) / sr

    base_name = os.path.splitext(os.path.basename(wav_path))[0]

    for i, word in enumerate(words):
        start_sample = int(start_times[i] * sr)
        end_sample = int(end_times[i] * sr)
        end_sample = min(end_sample, len(x))
        word_audio = x[start_sample:end_sample]

        # word 格式是 "a bi" 或 "a" (第一个音符)
        # "a bi" 表示：前一个元音是 a，当前音符是 bi
        if ' ' in word:
            prev_vowel_name, current_note = word.split(' ', 1)
        else:
            prev_vowel_name = '-'
            current_note = word

        if i == 0:
            # 第一个音符：只有这个音符的元音部分
            out_name = f"- {prev_vowel_name}"
            out_audio = word_audio
        else:
            # 非第一个音符：取上一个音符的元音 + 当前音符
            # phones tier 格式: "a bi" 表示 前元音=a, 当前音符=bi
            # 对于第二个音符 "i bu"，前元音应该是第一个音符的元音 "a"
            # 所以应该从上一个音素标注中取元音名

            # 取上一个音符的音频尾部（元音部分）
            prev_start = int(start_times[i-1] * sr)
            prev_end = int(end_times[i-1] * sr)
            prev_end = min(prev_end, len(x))
            prev_audio = x[prev_start:prev_end]

            # 检测上一个音符的元音起始位置
            vowel_start_in_prev = detect_vowel_onset(prev_audio, sr)
            prev_vowel = prev_audio[vowel_start_in_prev:]

            # 拼接：上一个音符的元音 + 这个音符
            out_audio = np.concatenate([prev_vowel, word_audio])

            # 文件名：上一个音符的元音名 + 空格 + 当前音符名
            # 从上一个音素标注中取元音名和当前音符名
            prev_word = words[i-1]
            if ' ' in prev_word:
                prev_vowel_from_prev, prev_current_note = prev_word.split(' ', 1)
            else:
                prev_vowel_from_prev = '-'
                prev_current_note = prev_word
            out_name = f"{prev_vowel_from_prev} {prev_current_note}"

        out_path = os.path.join(out_dir, f"{out_name}.wav")
        sf.write(out_path, out_audio, sr)
        print(f"  {out_name} ({librosa.get_duration(y=out_audio, sr=sr):.2f}s)")

    return len(words)

def batch_split_VCV(wavs_dir, out_dir, textgrid_dir):
    if not os.path.exists(wavs_dir):
        raise FileNotFoundError(f"音频目录不存在: {wavs_dir}")
    if not os.path.exists(textgrid_dir):
        raise FileNotFoundError(f"TextGrid目录不存在: {textgrid_dir}")

    os.makedirs(out_dir, exist_ok=True)

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

    success_count = 0
    error_count = 0
    total_vcv = 0

    for wav_path in audio_files:
        matching_tg_path = find_matching_textgrid(textgrid_dir, os.path.basename(wav_path))
        if matching_tg_path is None:
            print(f"警告: 未找到TextGrid: {wav_path}")
            continue

        try:
            print(f"\n处理: {os.path.basename(wav_path)}")
            count = split_VCV_single(matching_tg_path, wav_path, out_dir)
            total_vcv += count
            success_count += 1
        except Exception as e:
            print(f"处理失败: {wav_path}")
            print(f"错误: {str(e)}")
            error_count += 1

    print("-" * 70)
    print(f"批量处理完成!")
    print(f"成功处理: {success_count} 个文件")
    print(f"生成VCV: {total_vcv} 个片段")
    print(f"处理失败: {error_count} 个文件")

def find_matching_textgrid(textgrid_dir, audio_filename):
    base_name = os.path.splitext(os.path.basename(audio_filename))[0]

    for file in os.listdir(textgrid_dir):
        if file.lower().endswith('.textgrid'):
            tg_base_name = os.path.splitext(file)[0]
            if tg_base_name.lower() == base_name.lower():
                return os.path.join(textgrid_dir, file)

    for file in os.listdir(textgrid_dir):
        if file.lower().endswith('.textgrid'):
            tg_base_name = os.path.splitext(file)[0]
            if tg_base_name.lower() in base_name.lower() or base_name.lower() in tg_base_name.lower():
                return os.path.join(textgrid_dir, file)

    return None

def compute_overlap_ms(wav_path: str) -> int:
    try:
        y, sr = librosa.load(wav_path, sr=None)
        duration = librosa.get_duration(y=y, sr=sr)
        if duration < 0.02:
            return 5

        hop_length = 512
        rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
        frames_time = librosa.frames_to_time(range(len(rms)), sr=sr, hop_length=hop_length)

        threshold = np.max(rms) * 0.15
        onset_idx = np.argmax(rms > threshold)

        if onset_idx > 0:
            onset_time = frames_time[onset_idx]
        else:
            onset_time = duration * 0.2

        overlap = int(onset_time * 1000)
        return max(5, min(150, overlap))
    except Exception:
        return 50

def make_meta_VCV(wavs_dir):
    wavs = os.listdir(wavs_dir)
    f = open(os.path.join(wavs_dir, "meta.txt"), 'w', encoding='utf-8')
    for wav in wavs:
        if not wav.endswith('.wav'):
            continue
        wavpath = os.path.join(wavs_dir, wav)
        name = wav.rsplit('.', 1)[0]
        overlap = compute_overlap_ms(wavpath)
        f.write(f"{wav},{name},{overlap}\n")
    f.close()

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("用法: python build_singer_vcv.py <音频目录> <输出目录> <TextGrid目录>")
        sys.exit(1)
    wavs_dir = sys.argv[1]
    out_dir = sys.argv[2]
    textgrid_dir = sys.argv[3]
    batch_split_VCV(wavs_dir, out_dir, textgrid_dir)
    make_meta_VCV(out_dir)
