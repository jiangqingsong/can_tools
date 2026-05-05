"""
ASC文件解析器
支持CAN、CANFD、LIN等多种格式的ASC日志文件解析
"""

import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator, Optional, List, Dict, Any
from dataclasses import dataclass


@dataclass
class ASCSignal:
    """ASC信号数据类"""
    channel: str          # 通道号
    name: str             # 信号名称（CAN ID）
    value: str            # 信号值（原始十六进制数据）
    absolute_time: str    # 绝对时间（格式：YYYY-MM-DD HH:MM:SS.mmm）
    relative_time: float  # 相对时间（秒）
    frame_type: str       # 帧类型：CAN/CANFD/LIN
    dlc: int              # 数据长度
    direction: str        # 方向：Rx/Tx


class ASCReader:
    """ASC文件读取器"""
    
    def __init__(self, file_path: str, base_time_str: Optional[str] = None):
        """
        初始化ASC读取器
        
        Args:
            file_path: ASC文件路径
            base_time_str: 固定的起始时间（格式：YYYY-MM-DD HH:MM:SS.mmm）
        """
        self.file_path = Path(file_path)
        if not self.file_path.exists():
            raise FileNotFoundError(f"ASC文件不存在: {file_path}")
        
        self.base_time_str = base_time_str
        self.base_time: Optional[datetime] = None
        self.lines: List[str] = []
        
        self._load_file()
        self._parse_base_time()
    
    def _load_file(self):
        """加载ASC文件内容"""
        with open(self.file_path, 'r', encoding='utf-8', errors='ignore') as f:
            self.lines = f.readlines()
    
    def _parse_base_time(self):
        """解析起始时间"""
        if self.base_time_str:
            # 使用固定的起始时间
            self.base_time = datetime.strptime(
                self.base_time_str, 
                "%Y-%m-%d %H:%M:%S.%f"
            )
            return
        
        # 从文件中解析起始时间
        for line in self.lines[:50]:
            line = line.strip()
            if not line:
                continue
            
            # 匹配日期格式: date Sat Apr 4 00:13:08.043 AM 2026
            # 或: Begin TriggerBlock Sat Apr 4 00:13:08.043 AM 2026
            date_match = re.search(
                r'(?:date|Begin TriggerBlock)\s+'
                r'(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+'
                r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+'
                r'(\d{1,2})\s+'
                r'(\d{2}:\d{2}:\d{2}\.\d+)\s+'
                r'(AM|PM)\s+'
                r'(\d{4})',
                line,
                re.IGNORECASE
            )
            
            if date_match:
                month_str = date_match.group(1)
                day = int(date_match.group(2))
                time_str = date_match.group(3)
                am_pm = date_match.group(4).upper()
                year = int(date_match.group(5))
                
                # 解析时间
                hms, ms = time_str.split('.')
                hours, mins, secs = map(int, hms.split(':'))
                
                # 处理AM/PM
                if am_pm == 'PM' and hours != 12:
                    hours += 12
                elif am_pm == 'AM' and hours == 12:
                    hours = 0
                
                self.base_time = datetime(
                    year=year,
                    month=self._month_to_number(month_str),
                    day=day,
                    hour=hours,
                    minute=mins,
                    second=secs,
                    microsecond=int(ms.ljust(6, '0')[:6])
                )
                break
        
        if self.base_time is None:
            raise ValueError(f"无法从文件中解析起始时间: {self.file_path}")
    
    @staticmethod
    def _month_to_number(month_str: str) -> int:
        """将月份名称转换为数字"""
        months = {
            'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4,
            'may': 5, 'jun': 6, 'jul': 7, 'aug': 8,
            'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
        }
        return months.get(month_str.lower()[:3], 1)
    
    def _calculate_absolute_time(self, relative_time: float) -> str:
        """
        计算绝对时间
        
        Args:
            relative_time: 相对时间（秒）
        
        Returns:
            绝对时间字符串（格式：YYYY-MM-DD HH:MM:SS.mmm）
        """
        delta = timedelta(seconds=relative_time)
        abs_time = self.base_time + delta
        return abs_time.strftime("%Y-%m-%d %H:%M:%S.") + f"{abs_time.microsecond // 1000:03d}"
    
    def _parse_data_bytes(self, data_str: str, expected_dlc: int) -> str:
        """
        解析数据字节
        
        Args:
            data_str: 数据字节字符串
            expected_dlc: 期望的数据长度
        
        Returns:
            格式化后的十六进制数据字符串
        """
        # 提取有效的十六进制字节
        bytes_list = re.findall(r'[0-9A-Fa-f]{2}', data_str)
        
        # 限制长度
        bytes_list = bytes_list[:expected_dlc]
        
        # 补齐长度
        while len(bytes_list) < expected_dlc:
            bytes_list.append('00')
        
        return ' '.join(bytes_list).upper()
    
    def __iter__(self) -> Iterator[ASCSignal]:
        """迭代解析所有信号"""
        for line in self.lines:
            line = line.strip()
            
            # 跳过空行和注释
            if not line or line.startswith(';') or line.startswith('//'):
                continue
            
            # 跳过头部配置行
            lower_line = line.lower()
            if lower_line.startswith(('date ', 'base ', 'begin ', 'end ', 'internal ', 'start ', 'version ')):
                continue
            
            # 跳过非数据行（如 "Start of measurement"）
            if 'start of measurement' in lower_line:
                continue
            
            signal = self._parse_line(line)
            if signal:
                yield signal
    
    def _parse_line(self, line: str) -> Optional[ASCSignal]:
        """
        解析单行数据，支持CAN、CANFD、LIN格式
        """
        parts = line.split()
        if len(parts) < 5:
            return None
        
        try:
            # 第一列是相对时间
            relative_time = float(parts[0])
            
            # 判断帧类型
            if parts[1] == 'CANFD':
                # CANFD格式: 0.000000 CANFD 12 1DD Rx 0 0 d 13 32 B6 B5...
                # parts[0] = 时间
                # parts[1] = CANFD
                # parts[2] = 通道号
                # parts[3] = CAN ID
                # parts[4] = Rx/Tx
                # parts[5] = 标志位1
                # parts[6] = 标志位2
                # parts[7] = d
                # parts[8] = DLC
                # parts[9:] = 数据
                if len(parts) < 10:
                    return None
                
                channel = parts[2]
                can_id = parts[3]
                direction = parts[4]
                dlc = int(parts[8])
                data_bytes = parts[9:9 + dlc]
                
                return ASCSignal(
                    channel=channel,
                    name=f"0x{can_id.upper()}",
                    value=' '.join(data_bytes).upper(),
                    absolute_time=self._calculate_absolute_time(relative_time),
                    relative_time=relative_time,
                    frame_type="CANFD",
                    dlc=dlc,
                    direction=direction
                )
            
            elif parts[1].startswith('L'):
                # LIN格式: 0.003030 L19 29 Rx 8 00 00 00 30 00 91 C0 00 checksum = 00
                # parts[0] = 时间
                # parts[1] = L19 (通道)
                # parts[2] = LIN ID
                # parts[3] = Rx/Tx
                # parts[4] = DLC
                # parts[5:] = 数据和checksum
                if len(parts) < 6:
                    return None
                
                channel = parts[1]
                lin_id = parts[2]
                direction = parts[3]
                dlc = int(parts[4])
                
                # 提取数据字节（排除checksum）
                data_bytes = []
                for i in range(5, len(parts)):
                    if parts[i].lower() == 'checksum':
                        break
                    if re.match(r'^[0-9A-Fa-f]{2}$', parts[i]):
                        data_bytes.append(parts[i])
                
                # 补齐长度
                while len(data_bytes) < dlc:
                    data_bytes.append('00')
                data_bytes = data_bytes[:dlc]
                
                return ASCSignal(
                    channel=channel,
                    name=f"0x{lin_id.upper()}",
                    value=' '.join(data_bytes).upper(),
                    absolute_time=self._calculate_absolute_time(relative_time),
                    relative_time=relative_time,
                    frame_type="LIN",
                    dlc=dlc,
                    direction=direction
                )
            
            else:
                # CAN格式: 0.000090 2 112 Rx d 8 65 E5 28 34 0D 54 03 7D
                # parts[0] = 时间
                # parts[1] = 通道号
                # parts[2] = CAN ID
                # parts[3] = Rx/Tx
                # parts[4] = d
                # parts[5] = DLC
                # parts[6:] = 数据
                if len(parts) < 7 or parts[4] != 'd':
                    return None
                
                channel = parts[1]
                can_id = parts[2]
                direction = parts[3]
                dlc = int(parts[5])
                data_bytes = parts[6:6 + dlc]
                
                # 补齐长度
                while len(data_bytes) < dlc:
                    data_bytes.append('00')
                data_bytes = data_bytes[:dlc]
                
                return ASCSignal(
                    channel=channel,
                    name=f"0x{can_id.upper()}",
                    value=' '.join(data_bytes).upper(),
                    absolute_time=self._calculate_absolute_time(relative_time),
                    relative_time=relative_time,
                    frame_type="CAN",
                    dlc=dlc,
                    direction=direction
                )
        
        except (ValueError, IndexError):
            return None
    
    def parse_all(self) -> List[ASCSignal]:
        """解析所有信号并返回列表"""
        return list(self)
    
    def to_dict_list(self) -> List[Dict[str, Any]]:
        """将解析结果转换为字典列表"""
        return [
            {
                "channel": sig.channel,
                "name": sig.name,
                "value": sig.value,
                "absolute_time": sig.absolute_time,
                "relative_time": sig.relative_time,
                "frame_type": sig.frame_type,
                "dlc": sig.dlc,
                "direction": sig.direction
            }
            for sig in self.parse_all()
        ]


def parse_asc_file(file_path: str, base_time_str: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    解析ASC文件的便捷函数
    
    Args:
        file_path: ASC文件路径
        base_time_str: 固定的起始时间（格式：YYYY-MM-DD HH:MM:SS.mmm）
    
    Returns:
        解析结果字典列表
    """
    reader = ASCReader(file_path, base_time_str)
    return reader.to_dict_list()


if __name__ == "__main__":
    import json
    
    # 测试demo01.asc
    print("=" * 80)
    print("解析 demo01.asc")
    print("=" * 80)
    
    demo01_path = "/Users/mac/2026/ai_coding_project/can_tools/src/asc_decoder/demo01.asc"
    results01 = parse_asc_file(demo01_path, "2026-04-04 00:13:08.043")
    
    print(f"总帧数: {len(results01)}")
    print("\n前5帧数据:")
    for i, sig in enumerate(results01[:5], 1):
        print(f"  {i}. 通道:{sig['channel']:>3} | 名称:{sig['name']:>6} | "
              f"时间:{sig['absolute_time']} | 类型:{sig['frame_type']:>5} | "
              f"数据:{sig['value']}")
    
    # 测试demo02.asc
    print("\n" + "=" * 80)
    print("解析 demo02.asc")
    print("=" * 80)
    
    demo02_path = "/Users/mac/2026/ai_coding_project/can_tools/src/asc_decoder/demo02.asc"
    results02 = parse_asc_file(demo02_path, "2026-02-21 16:20:00.965")
    
    print(f"总帧数: {len(results02)}")
    print("\n前5帧数据:")
    for i, sig in enumerate(results02[:5], 1):
        print(f"  {i}. 通道:{sig['channel']:>3} | 名称:{sig['name']:>6} | "
              f"时间:{sig['absolute_time']} | 类型:{sig['frame_type']:>5} | "
              f"数据:{sig['value']}")
    
    # 保存结果到JSON文件
    output_dir = Path("/Users/mac/2026/ai_coding_project/can_tools/src/asc_decoder")
    
    with open(output_dir / "demo01_result.json", 'w', encoding='utf-8') as f:
        json.dump(results01, f, ensure_ascii=False, indent=2)
    
    with open(output_dir / "demo02_result.json", 'w', encoding='utf-8') as f:
        json.dump(results02, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 结果已保存到:")
    print(f"   - {output_dir / 'demo01_result.json'}")
    print(f"   - {output_dir / 'demo02_result.json'}")
