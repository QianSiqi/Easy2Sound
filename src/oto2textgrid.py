"""
oto2textgrid.py — 将 UTAU oto.ini 转换为 Praat TextGrid
======================================================
用法: python oto2textgrid.py <oto.ini路径> <输出目录>

输出目录中每个 wav 文件对应一个 .TextGrid 文件
"""

import sys
import os


def parse_oto(oto_path):
    """解析 oto.ini 文件，按文件名分组"""
    groups = {}
    with open(oto_path, 'r', encoding='shift_jis') as f:
        for line in f:
            line = line.strip()
            if not line or '=' not in line:
                continue

            filename_part, rest = line.split('=', 1)
            if ',' not in rest:
                continue

            alias_part, params_str = rest.split(',', 1)
            params = params_str.split(',')

            if len(params) < 5:
                continue

            try:
                consonant = float(params[1])    # 辅音长度 (ms)
                preutterance = float(params[3]) # 预发声 (ms)

                entry = {
                    'filename': filename_part,
                    'alias': alias_part,
                    'consonant': consonant,
                    'preutterance': preutterance,
                }

                if filename_part not in groups:
                    groups[filename_part] = []
                groups[filename_part].append(entry)
            except (ValueError, IndexError):
                continue

    return groups


def entry_to_duration(entry):
    """估算单个条目的时长"""
    return max(100, entry['consonant'] + entry['preutterance'] + 200)


def write_textgrid(entries, output_path):
    """为一组条目写入 TextGrid 文件"""
    if not entries:
        return

    # 计算每个条目的时长和总时长
    durations = [entry_to_duration(e) for e in entries]
    total_ms = sum(durations)

    T = '\t'
    lines = []
    lines.append('File type = "ooTextFile"')
    lines.append('Object class = "TextGrid"')
    lines.append('')
    lines.append('xmin = 0')
    lines.append(f'xmax = {total_ms / 1000:.6f}')
    lines.append('tiers? <exists>')
    lines.append('size = 2')
    lines.append('item []:')

    # Words tier
    lines.append(f'{T}item [1]:')
    lines.append(f'{T*2}class = "IntervalTier"')
    lines.append(f'{T*2}name = "words"')
    lines.append(f'{T*2}xmin = 0')
    lines.append(f'{T*2}xmax = {total_ms / 1000:.6f}')
    lines.append(f'{T*2}intervals: size = {len(entries)}')

    current_time = 0
    for i, entry in enumerate(entries):
        duration = durations[i] / 1000
        start = current_time
        end = current_time + duration

        word = entry['alias'].split(' ')[0] if ' ' in entry['alias'] else entry['alias']

        lines.append(f'{T*3}intervals [{i+1}]:')
        lines.append(f'{T*4}xmin = {start:.6f}')
        lines.append(f'{T*4}xmax = {end:.6f}')
        lines.append(f'{T*4}text = "{word}"')

        current_time = end

    # Phones tier
    lines.append(f'{T}item [2]:')
    lines.append(f'{T*2}class = "IntervalTier"')
    lines.append(f'{T*2}name = "phones"')
    lines.append(f'{T*2}xmin = 0')
    lines.append(f'{T*2}xmax = {total_ms / 1000:.6f}')
    lines.append(f'{T*2}intervals: size = {len(entries)}')

    current_time = 0
    for i, entry in enumerate(entries):
        duration = durations[i] / 1000
        start = current_time
        end = current_time + duration

        alias = entry['alias']
        lines.append(f'{T*3}intervals [{i+1}]:')
        lines.append(f'{T*4}xmin = {start:.6f}')
        lines.append(f'{T*4}xmax = {end:.6f}')
        lines.append(f'{T*4}text = "{alias}"')

        current_time = end

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


def oto_to_textgrid(oto_path, output_dir):
    """将 oto.ini 转换为多个 TextGrid 文件"""
    groups = parse_oto(oto_path)

    if not groups:
        print("错误: oto.ini 中没有有效的条目")
        return

    os.makedirs(output_dir, exist_ok=True)

    count = 0
    for filename, entries in groups.items():
        # 生成输出文件名：把 .wav 替换为 .TextGrid，去掉前缀下划线，保留尾部下划线
        if '.' in filename:
            base = filename.rsplit('.', 1)[0]
        else:
            base = filename
        if base.startswith('_'):
            base = base[1:]
        # 确保尾部有下划线（匹配 hira2roma 生成的文件名格式）
        if not base.endswith('_'):
            base += '_'
        output_path = os.path.join(output_dir, base + '.TextGrid')

        write_textgrid(entries, output_path)
        count += 1

    print(f"已转换: {oto_path} -> {output_dir}")
    print(f"共 {count} 个 TextGrid 文件")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: python oto2textgrid.py <oto.ini路径> <输出目录>")
        print("示例: python oto2textgrid.py vcvtest2/oto.ini vcvtest2")
        sys.exit(1)

    oto_path = sys.argv[1]
    output_dir = sys.argv[2]

    if not os.path.exists(oto_path):
        print(f"错误: 文件不存在 {oto_path}")
        sys.exit(1)

    oto_to_textgrid(oto_path, output_dir)
