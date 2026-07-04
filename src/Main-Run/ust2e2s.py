import re
from pathlib import Path
import sys
import codecs
import math

class UstToE2sConverter:
    """UST文件转换为E2S文件的转换器（精准匹配UST音符长度，歌词一致，支持pitchbend调整）"""
    
    # 音符数字到音高名称的映射（MIDI标准：C1=24）
    NOTE_NUM_TO_PITCH = {
        24: "C1", 25: "C#1", 26: "D1", 27: "D#1", 28: "E1", 29: "F1", 30: "F#1", 31: "G1",
        32: "G#1", 33: "A1", 34: "A#1", 35: "B1",
        36: "C2", 37: "C#2", 38: "D2", 39: "D#2", 40: "E2", 41: "F2", 42: "F#2", 43: "G2",
        44: "G#2", 45: "A2", 46: "A#2", 47: "B2",
        48: "C3", 49: "C#3", 50: "D3", 51: "D#3", 52: "E3", 53: "F3", 54: "F#3", 55: "G3",
        56: "G#3", 57: "A3", 58: "A#3", 59: "B3",
        60: "C4", 61: "C#4", 62: "D4", 63: "D#4", 64: "E4", 65: "F4", 66: "F#4", 67: "G4",
        68: "G#4", 69: "A4", 70: "A#4", 71: "B4",
        72: "C5", 73: "C#5", 74: "D5", 75: "D#5", 76: "E5", 77: "F5", 78: "F#5", 79: "G5",
        80: "G#5", 81: "A5", 82: "A#5", 83: "B5",
        84: "C6", 85: "C#6", 86: "D6", 87: "D#6", 88: "E6", 89: "F6", 90: "F#6", 91: "G6",
        92: "G#6", 93: "A6", 94: "A#6", 95: "B6",
        96: "C7", 97: "C#7", 98: "D7", 99: "D#7", 100: "E7", 101: "F7", 102: "F#7", 103: "G7",
        104: "G#7", 105: "A7", 106: "A#7", 107: "B7"
    }

    def __init__(self, singer_path="./voicebank", resampler="python resampler.py", 
                 wavtool="python wavtool.py", pitchbend_coeff=1.0):
        """
        初始化转换器（不接收phonemer参数，固定写入JA_CV）
        :param singer_path: 音源路径（默认：./voicebank）
        :param resampler: 重采样器命令（默认：python resampler.py）
        :param wavtool: 音频工具命令（默认：python wavtool.py）
        :param pitchbend_coeff: pitchbend调整系数（1.0=原调，>1升调，<1降调）
        """
        # E2S头部配置（固定写入phonemer=JA_CV）
        self.e2s_header = {
            "singer_path": singer_path,
            "resampler": resampler,
            "wavtool": wavtool,
            "phonemer": "JA_CV"
        }
        
        # 默认的颤音参数
        self.vib_defaults = {
            "vib_start": 0,
            "vib_end": 0,
            "vib_rate": 0,
            "vib_depth": 0
        }
        
        # pitchbend调整系数（限制在0.1~5.0之间，避免极端值）
        self.pitchbend_coeff = max(0.1, min(pitchbend_coeff, 5.0))
        
        # 休止符标记（UST中R/sil都视为休止符）
        self.rest_markers = {'R', 'sil', 'r'}

    def parse_ust(self, ust_content: str, encoding: str = 'shift_jis') -> dict:
        """
        解析UST文件内容（重点：完整读取Tempo字段，即UST实际BPM）
        :param ust_content: UST文件的文本内容
        :param encoding: 编码格式（UTAU标准为shift_jis）
        :return: 解析后的UST数据字典（包含settings[Tempo]）
        """
        ust_data = {
            "settings": {},  # 存放UST的Tempo、其他配置
            "notes": []      # 存放音符数据
        }

        # 修复分割逻辑：兼容不同换行符和节头格式
        ust_content = ust_content.replace('\r\n', '\n').replace('\r', '\n')
        blocks = re.split(r'\[\#(SETTING|\d+|PREV|NEXT|INSERT|DELETE|VERSION)\]', ust_content)
        
        # 提取节头和内容（修复索引越界问题）
        headers = []
        contents = []
        for i in range(1, len(blocks), 2):
            if i < len(blocks):
                marker = blocks[i].strip()
                headers.append(f"[#{marker}]")
            if i+1 < len(blocks):
                contents.append(blocks[i+1].strip())

        for header, content in zip(headers, contents):
            # 重点：解析设置节，读取实际Tempo（BPM）
            if header == "[#SETTING]":
                lines = content.split('\n')
                for line in lines:
                    line = line.strip()
                    if '=' in line and not line.startswith('//'):  # 跳过注释
                        key, value = line.split('=', 1)
                        ust_data["settings"][key.strip()] = value.strip()
            
            # 解析音符节（仅处理数字节）
            elif header.startswith("[#") and header[2:-1].isdigit():
                note_id = int(header[2:-1])
                note_data = {"id": note_id}
                
                lines = content.split('\n')
                for line in lines:
                    line = line.strip()
                    if '=' in line and not line.startswith('//'):
                        key, value = line.split('=', 1)
                        note_data[key.strip()] = value.strip()
                
                # 确保必要字段存在（遵循UST必填条目规范）
                note_data.setdefault("Length", "480")  # 默认1拍
                note_data.setdefault("Lyric", "")
                note_data.setdefault("NoteNum", "60")  # 默认C4
                note_data.setdefault("PreUtterance", "0")
                note_data.setdefault("Velocity", "100")  # 默认音量
                note_data.setdefault("VBR", "")  # 默认无颤音
                note_data.setdefault("PBS", ""), note_data.setdefault("PBW", ""), note_data.setdefault("PBY", ""), note_data.setdefault("PBM", "")
                
                ust_data["notes"].append(note_data)

        # 按音符ID排序（确保音符顺序正确）
        ust_data["notes"].sort(key=lambda x: x["id"])
        return ust_data

    def convert_note_length(self, ust_length: str, tempo: float) -> int:
        """
        精准转换UST音符长度（核心：用UST实际BPM计算，输出整数毫秒）
        遵循UTAU标准公式：
        1. 四分音符时长 = 60000ms / BPM（1分钟=60000毫秒，除以每分钟节拍数，得单个四分音符时长）
        2. 音符时长（ms）= （UST Length值 / 480） * 四分音符时长（480是UST默认TPQN，固定不变）
        :param ust_length: UST中的Length值（Ticks单位）
        :param tempo: UST实际BPM（从parse_ust中读取）
        :return: 转换后的音符长度（整数毫秒，符合E2S解析要求）
        """
        try:
            # 解析UST Length值，限制在UTAU合法范围（1~7680）
            length_ticks = int(ust_length)
            length_ticks = max(1, min(length_ticks, 7680))
            
            tpqn = 480  # UTAU固定TPQN（四分音符=480 Ticks，无需修改）
            quarter_note_ms = 60000.0 / tempo  # 四分音符时长（毫秒）
            note_ms = (length_ticks / tpqn) * quarter_note_ms  # 最终音符时长
            
            # 转换为整数毫秒（E2S解析代码要求整数）
            return max(10, int(round(note_ms)))  # 最小10ms避免无效长度
        except (ValueError, TypeError, ZeroDivisionError):
            # 异常情况（Length无效、BPM为0），用默认值兜底
            return 500

    def parse_pitch_bend(self, note_data: dict) -> str:
        """
        解析UST音高弯曲参数，应用pitchbend调整系数（修复解析逻辑）
        """
        try:
            pbs = note_data.get("PBS", "").strip()
            pbw = note_data.get("PBW", "").strip()
            pby = note_data.get("PBY", "").strip()
            pbm = note_data.get("PBM", "").strip()
            
            if not pbs or not pbw or not pby:
                return ""
            
            # 解析PBS（时间;音高偏移，单位：毫秒;10音分）
            pbs_parts = pbs.split(';')
            time_offset = float(pbs_parts[0]) if len(pbs_parts) > 0 and pbs_parts[0].replace('.','').isdigit() else 0
            pitch_offset = float(pbs_parts[1]) if len(pbs_parts) > 1 and pbs_parts[1].replace('.','').isdigit() else 0
            pitch_offset *= self.pitchbend_coeff  # 应用调整系数

            # 解析PBW/PBY/PBM（兼容空值和非数字）
            pbw_list = []
            for x in pbw.split(','):
                x = x.strip()
                if x.replace('.','').isdigit():
                    pbw_list.append(float(x))
            
            pby_list = []
            for x in pby.split(','):
                x = x.strip()
                if x.replace('.','').isdigit():
                    pby_list.append(float(x) * self.pitchbend_coeff)
            
            pbm_list = [x.strip() if x.strip() in ['c', 'l', 'r', 's'] else 'c' for x in pbm.split(',')]

            # 生成E2S格式pitchbend字符串（修复索引越界）
            pitchbend_parts = []
            current_time = max(0.0, time_offset)
            # 添加起始点（偏移量转换为音分：10音分 * 10 = 音分）
            pitchbend_parts.append(f"{current_time:.1f}:{pitch_offset*10:.1f}:{pbm_list[0] if pbm_list else 'c'}")

            # 添加后续音高点（匹配列表长度）
            max_len = min(len(pbw_list), len(pby_list))
            for i in range(max_len):
                current_time += pbw_list[i]
                bend_type = pbm_list[i+1] if len(pbm_list) > i+1 else 'c'
                pitchbend_parts.append(f"{current_time:.1f}:{pby_list[i]*10:.1f}:{bend_type}")
            
            return ','.join(pitchbend_parts)
        except Exception as e:
            # 解析失败时返回空字符串，不中断转换
            return ""

    def parse_vibrato(self, note_data: dict) -> tuple:
        """
        解析UST颤音参数，颤音深度同步应用pitchbend系数（增强容错）
        """
        try:
            vbr = note_data.get("VBR", "").strip()
            if not vbr:
                return (0, 0, 0, 0)
            
            vbr_parts = vbr.split(',')
            # VBR格式：长度(%)、周期(ms)、深度(音分)、入(%)、出(%)、相位(%)、高度(%)、未使用
            # 补全不足的参数
            while len(vbr_parts) < 8:
                vbr_parts.append("0")
            
            # 安全解析每个参数
            vib_length = self._safe_float(vbr_parts[0], 0)
            vib_rate = self._safe_int(vbr_parts[1], 0)
            vib_depth = self._safe_int(vbr_parts[2], 0)
            vib_start = self._safe_int(vbr_parts[3], 0)
            vib_end = self._safe_int(vbr_parts[4], 0)
            
            # 颤音深度应用pitchbend系数，限制范围（0~200音分）
            vib_depth = int(vib_depth * self.pitchbend_coeff)
            vib_depth = max(0, min(vib_depth, 200))
            
            # 限制参数范围
            vib_start = max(0, min(vib_start, 100))
            vib_end = max(0, min(vib_end, 100))
            vib_rate = max(0, min(vib_rate, 500))
            
            return (vib_start, vib_end, vib_rate, vib_depth)
        except Exception:
            return (0, 0, 0, 0)
    
    def _safe_float(self, value: str, default: float) -> float:
        """安全转换为浮点数"""
        try:
            return float(value.strip())
        except:
            return default
    
    def _safe_int(self, value: str, default: int) -> int:
        """安全转换为整数"""
        try:
            return int(float(value.strip()))
        except:
            return default

    def adjust_base_pitch(self, note_num: int) -> tuple:
        """
        根据pitchbend系数调整基础音高（优化音高计算逻辑）
        """
        if self.pitchbend_coeff == 1.0:
            adjusted_num = note_num
        else:
            # 基于对数音阶计算音分偏移（符合音乐声学标准）
            cent_offset = math.log2(self.pitchbend_coeff) * 1200  # 1200音分=1八度
            semitone_offset = int(round(cent_offset / 100))  # 100音分=1半音
            adjusted_num = max(24, min(note_num + semitone_offset, 107))  # 限制音符范围
        
        pitch_name = self.NOTE_NUM_TO_PITCH.get(adjusted_num, "C4")
        return (adjusted_num, pitch_name)

    def convert_ust_to_e2s(self, ust_path: str, e2s_path: str, adjust_base_pitch: bool = False) -> bool:
        """
        核心转换逻辑（整合所有功能，精准匹配音符长度，保留休止符）
        """
        try:
            # 1. 读取UST文件（增强编码兼容性）
            ust_path = Path(ust_path)
            encodings = ['shift_jis']
            ust_content = None
            
            for enc in encodings:
                try:
                    with codecs.open(ust_path, 'r', encoding=enc) as f:
                        ust_content = f.read()
                    break
                except:
                    continue
            
            if ust_content is None:
                print(f"错误：无法读取UST文件（所有编码尝试失败）")
                return False
            
            # 2. 解析UST数据（重点：获取实际BPM）
            ust_data = self.parse_ust(ust_content)
            
            # 3. 获取UST实际BPM（优先读取Tempo字段，无则用默认135）
            tempo_str = ust_data["settings"].get("Tempo", "135")
            tempo = self._safe_float(tempo_str, 135)
            tempo = max(10, min(tempo, 512))  # 限制BPM在UTAU合法范围（10~512）
            
            # 4. 构建E2S内容
            e2s_lines = []
            # 添加E2S头部（含固定phonemer=JA_CV）
            for key, value in self.e2s_header.items():
                e2s_lines.append(f"{key}={value}")
            e2s_lines.append("")  # 空行分隔头部和音符

            # 5. 处理每个音符（精准计算长度，保留休止符）
            for idx, note in enumerate(ust_data["notes"]):
                # 精准计算音符长度（传入UST实际BPM，返回整数毫秒）
                length = self.convert_note_length(note.get("Length", "480"), tempo)
                
                # 处理歌词（UST的R/sil统一转为sil）
                lyric = note.get("Lyric", "").strip()
                if lyric.upper() == 'R' or lyric in self.rest_markers:
                    lyric = "sil"
                
                # 处理音量（Velocity：0~200，默认100）
                volume = self._safe_int(note.get("Velocity", "100"), 100)
                volume = max(0, min(volume, 200))  # 限制音量范围

                # 处理基础音高（休止符用默认C4）
                note_num = self._safe_int(note.get("NoteNum", 60), 60)
                note_num = max(24, min(note_num, 107))  # 限制音符编号范围
                
                if lyric == "sil":
                    pitch = "C4"  # 休止符音高无意义，默认C4
                elif adjust_base_pitch:
                    _, pitch = self.adjust_base_pitch(note_num)
                else:
                    pitch = self.NOTE_NUM_TO_PITCH.get(note_num, "C4")

                # 处理音高弯曲和颤音（休止符跳过）
                if lyric == "sil":
                    pitchbend = ""
                    vib_start = vib_end = vib_rate = vib_depth = 0
                else:
                    pitchbend = self.parse_pitch_bend(note)
                    vib_start, vib_end, vib_rate, vib_depth = self.parse_vibrato(note)

                # 构建单个音符块（符合E2S格式，参数名精准匹配）
                e2s_lines.append(f"[{idx}]:")
                e2s_lines.append(f"lyric={lyric}")
                e2s_lines.append(f"length={length}")  # 整数毫秒，精准匹配
                e2s_lines.append(f"volume={volume}")
                e2s_lines.append(f"pitch={pitch}")
                e2s_lines.append(f"pitchbend={pitchbend}")
                e2s_lines.append(f"vib_start={vib_start}")
                e2s_lines.append(f"vib_end={vib_end}")
                e2s_lines.append(f"vib_rate={vib_rate}")
                e2s_lines.append(f"vib_depth={vib_depth}")
                e2s_lines.append(f"crossfade=50")  # 默认交叉淡化值（符合E2S规范）
                e2s_lines.append(f"dyn_vol=")
                e2s_lines.append(f"dyn_pitch=")
                e2s_lines.append("")  # 音符块之间空行分隔

            # 6. 写入E2S文件（UTF-8编码，确保换行符兼容）
            e2s_content = '\n'.join(e2s_lines).rstrip('\n')
            e2s_path = Path(e2s_path)
            e2s_path.parent.mkdir(parents=True, exist_ok=True)  # 确保输出目录存在
            
            with open(e2s_path, 'w', encoding='utf-8', newline='\n') as f:
                f.write(e2s_content)
            
            print(f"转换成功！")
            print(f"  输入文件: {ust_path}")
            print(f"  输出文件: {e2s_path}")
            print(f"  适配UST BPM: {tempo} | Pitchbend系数: {self.pitchbend_coeff}")
            print(f"  处理音符数: {len(ust_data['notes'])}")
            return True
            
        except FileNotFoundError:
            print(f"错误：找不到输入文件 {ust_path}")
            return False
        except Exception as e:
            print(f"转换失败：{str(e)}")
            import traceback
            traceback.print_exc()
            return False

def main():
    """
    主函数（命令行调用，无phonemer参数，支持自定义核心配置）
    命令行格式：python ust2e2s.py <输入UST路径> <输出E2S路径> [--singer_path 音源路径] [--resampler 命令] [--wavtool 命令] [--pitchbend_coeff 系数] [--adjust_base_pitch]
    """
    import argparse
    
    parser = argparse.ArgumentParser(description="UST to E2S Converter（精准匹配音符长度+歌词一致）")
    parser.add_argument("ustfile", help="输入UST文件路径")
    parser.add_argument("e2sfile", help="输出E2S文件路径")
    parser.add_argument("--singer_path", default="./voicebank", help="音源路径（默认：./voicebank）")
    parser.add_argument("--resampler", default="python resampler.py", help="重采样器命令")
    parser.add_argument("--wavtool", default="python wavtool.py", help="音频工具命令")
    parser.add_argument("--pitchbend_coeff", type=float, default=1.0, help="pitchbend调整系数（1.0=原调，1.2=升20%，0.8=降20%）")
    parser.add_argument("--adjust_base_pitch", action="store_true", help="是否同时调整基础音高（默认仅调整pitchbend）")
    
    args = parser.parse_args()
    
    # 验证输入文件存在
    if not Path(args.ustfile).exists():
        print(f"❌ 错误：输入文件 {args.ustfile} 不存在")
        sys.exit(1)
    
    # 创建转换器实例，执行转换
    converter = UstToE2sConverter(
        singer_path=args.singer_path,
        resampler=args.resampler,
        wavtool=args.wavtool,
        pitchbend_coeff=args.pitchbend_coeff
    )
    success = converter.convert_ust_to_e2s(args.ustfile, args.e2sfile, args.adjust_base_pitch)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()