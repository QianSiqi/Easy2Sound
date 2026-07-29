"""
oto_hira2roma.py — 将 UTAU oto.ini 中的平假名转换为罗马音
=========================================================
用法: python oto_hira2roma.py <oto.ini路径> [字典路径]

字典默认使用 hira2roma_list.txt
"""

import sys
import os
import re


def load_dict(dict_path):
    """加载平假名->罗马音字典"""
    mapping = {}
    with open(dict_path, 'r', encoding='utf-8') as f:
        for line in f:
            parts = line.strip().split(',')
            if len(parts) == 2 and parts[0] and parts[1]:
                mapping[parts[0]] = parts[1]
    # 按长度降序排列，用于贪心匹配
    sorted_keys = sorted(mapping.keys(), key=len, reverse=True)
    return mapping, sorted_keys


def is_hiragana(char):
    """检查是否是平假名（含小假名）"""
    code = ord(char)
    return (0x3040 <= code <= 0x309F) or (0x3099 <= code <= 0x309F)


def hira2roma(text, mapping, sorted_keys):
    """将文本中的平假名转换为罗马音，如果有无法转换的平假名则返回 None"""
    result = ""
    i = 0
    while i < len(text):
        matched = False
        for key in sorted_keys:
            if text[i:].startswith(key):
                result += mapping[key]
                i += len(key)
                matched = True
                break
        if not matched:
            # 如果是平假名但字典里没有，返回 None 表示跳过
            if is_hiragana(text[i]):
                return None
            # 非平假名字符，原样保留
            result += text[i]
            i += 1
    # 去掉末尾的下划线（如果有）
    result = result.rstrip('_')
    # R 转换为 SP（静音）
    result = result.replace('R', 'SP')
    return result


def convert_oto(oto_path, dict_path):
    """转换 oto.ini 中的平假名为罗马音"""
    mapping, sorted_keys = load_dict(dict_path)

    with open(oto_path, 'r', encoding='shift_jis') as f:
        lines = f.readlines()

    new_lines = []
    for line in lines:
        line = line.strip()
        if not line:
            new_lines.append('')
            continue

        # oto.ini 格式: filename.wav=alias,offset,consonant,overlap,preutterance,processed
        # 有些行可能没有等号（注释或空行）
        if '=' not in line:
            new_lines.append(line)
            continue

        # 分离文件名和其余部分
        filename_part, rest = line.split('=', 1)

        # 分离 alias 和参数
        if ',' in rest:
            alias_part, params = rest.split(',', 1)
        else:
            alias_part, params = rest, ''

        # 去掉文件扩展名进行转换
        name_no_ext = filename_part.rsplit('.', 1)[0] if '.' in filename_part else filename_part
        ext = '.' + filename_part.rsplit('.', 1)[1] if '.' in filename_part else '.wav'

        # 保留前缀下划线
        prefix = ''
        if name_no_ext.startswith('_'):
            prefix = '_'
            name_no_ext = name_no_ext[1:]

        # 转换文件名中的平假名
        new_name = hira2roma(name_no_ext, mapping, sorted_keys)

        # 转换 alias 中的平假名
        new_alias = hira2roma(alias_part, mapping, sorted_keys)

        # 如果任一转换失败（有字典中没有的平假名），跳过该条目
        if new_name is None or new_alias is None:
            continue

        # 重组行
        new_filename = prefix + new_name + ext
        new_line = f"{new_filename}={new_alias}"
        if params:
            new_line += f",{params}"

        new_lines.append(new_line)

    # 写回文件
    with open(oto_path, 'w', encoding='shift_jis') as f:
        f.write('\n'.join(new_lines) + '\n')

    print(f"已转换: {oto_path}")
    print(f"共处理 {len(new_lines)} 行")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python oto_hira2roma.py <oto.ini路径> [字典路径]")
        print("示例: python oto_hira2roma.py voicebank/あ/oto.ini")
        sys.exit(1)

    oto_path = sys.argv[1]
    dict_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(__file__), 'hira2roma_list.txt')

    if not os.path.exists(oto_path):
        print(f"错误: 文件不存在 {oto_path}")
        sys.exit(1)

    convert_oto(oto_path, dict_path)
