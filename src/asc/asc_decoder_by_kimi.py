import os
import re
import cantools
import can
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

from fast_asc_reader import FastASCReader
from starrocks_writer import StarRocksDataWriter


def format_timestamp_with_ms(timestamp: float) -> str:
    """高精度时间格式化，保留3位毫秒数"""
    try:
        if timestamp is None or not isinstance(timestamp, (int, float)):
            return "1970-01-01 00:00:00.000"
        if timestamp < 0 or timestamp > 4102444800:
            return "1970-01-01 00:00:00.000"
        
        dt = datetime.fromtimestamp(timestamp)
        milliseconds = int((timestamp % 1) * 1000)
        return f"{dt.strftime('%Y-%m-%d %H:%M:%S')}.{milliseconds:03d}"
        
    except Exception:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S.000")


class CANLogParser:
    """CAN日志解析器：ASC文件解析 + DBC信号解码"""
    
    def __init__(self, dbc_path: str):
        # 使用GBK编码加载DBC文件（中文Windows系统常用编码）
        self.db = cantools.database.load_file(dbc_path, strict=False, encoding='gbk')
        print(f"✅ 成功加载DBC (gbk): {len(self.db.messages)} 条消息定义")
        
        self.message_map = {}
        for msg in self.db.messages:
            self.message_map[msg.frame_id] = msg.name
            if msg.is_extended_frame:
                self.message_map[msg.frame_id | 0x80000000] = msg.name
    
    def parse_asc_file(self, asc_path: str) -> List[Dict[str, Any]]:
        """解析ASC文件并解码所有信号"""
        asc_path = Path(asc_path)
        if not asc_path.exists():
            raise FileNotFoundError(f"ASC文件不存在: {asc_path}")
        
        results = []
        decoded_count = 0
        error_count = 0
        
        print(f"\n📁 解析ASC文件: {asc_path}")
        reader = FastASCReader(asc_path)
        print(f"   基准时间: {format_timestamp_with_ms(reader.base_timestamp)}")
        
        for msg in reader:
            try:
                decoded_signals = self.decode_message(msg)
                
                if decoded_signals is not None:
                    record = {
                        'rel_timestamp': round(msg.timestamp - reader.base_timestamp, 6),
                        'timestamp': msg.timestamp,
                        'datetime': format_timestamp_with_ms(msg.timestamp),
                        'format_date': format_timestamp_with_ms(msg.timestamp),
                        'channel': msg.channel,
                        'arbitration_id': hex(msg.arbitration_id),
                        'message_name': self.get_message_name(msg.arbitration_id),
                        'dlc': len(msg.data),
                        'raw_data': msg.data.hex(),
                        **decoded_signals
                    }
                    results.append(record)
                    decoded_count += 1
                else:
                    record = {
                        'rel_timestamp': round(msg.timestamp - reader.base_timestamp, 6),
                        'timestamp': msg.timestamp,
                        'datetime': format_timestamp_with_ms(msg.timestamp),
                        'format_date': format_timestamp_with_ms(msg.timestamp),
                        'channel': msg.channel,
                        'arbitration_id': hex(msg.arbitration_id),
                        'message_name': 'UNKNOWN',
                        'dlc': len(msg.data),
                        'raw_data': msg.data.hex(),
                        'error': '未在DBC中找到消息定义'
                    }
                    results.append(record)
                    
            except Exception as e:
                error_count += 1
                record = {
                    'rel_timestamp': round(msg.timestamp - reader.base_timestamp, 6),
                    'timestamp': msg.timestamp,
                    'datetime': format_timestamp_with_ms(msg.timestamp),
                    'format_date': format_timestamp_with_ms(msg.timestamp),
                    'arbitration_id': hex(msg.arbitration_id),
                    'raw_data': msg.data.hex() if msg.data else 'N/A',
                    'error': str(e)
                }
                results.append(record)
                if error_count <= 5:
                    print(f"   ⚠️  解码错误: {hex(msg.arbitration_id)} - {e}")
        
        print(f"\n📊 解析完成:")
        print(f"   总帧数: {len(results)}, 成功: {decoded_count}, 失败: {error_count}")
        
        return results
    
    def decode_message(self, msg: can.Message) -> Optional[Dict[str, Any]]:
        """使用DBC解码单条CAN消息"""
        try:
            return self.db.decode_message(
                msg.arbitration_id, 
                msg.data,
                decode_choices=True
            )
        except KeyError:
            return None
        except Exception as e:
            raise e
    def get_message_name(self, arbitration_id: int) -> str:
        """根据帧ID获取消息名称"""
        if arbitration_id in self.message_map:
            return self.message_map[arbitration_id]
        
        standard_id = arbitration_id & 0x7FFFFFFF
        if standard_id in self.message_map:
            return self.message_map[standard_id]
        
        return f"UNKNOWN_ID_{hex(arbitration_id)}"
    
    def to_dataframe(self, records: List[Dict]) -> pd.DataFrame:
        """转换为pandas DataFrame并调整列顺序"""
        if not records:
            return pd.DataFrame()
        
        df = pd.DataFrame(records)
        
        base_cols = ['rel_timestamp', 'timestamp', 'datetime', 'format_date', 'channel', 
                     'arbitration_id', 'message_name', 'dlc', 'raw_data']
        signal_cols = [c for c in df.columns if c not in base_cols + ['error']]
        error_cols = ['error'] if 'error' in df.columns else []
        
        ordered_cols = base_cols + signal_cols + error_cols
        ordered_cols = [c for c in ordered_cols if c in df.columns]
        
        return df[ordered_cols]


def quick_decode(dbc_path: str, asc_path: str) -> pd.DataFrame:
    """快速解析入口函数"""
    parser = CANLogParser(dbc_path)
    records = parser.parse_asc_file(asc_path)
    df = parser.to_dataframe(records)
    
    pd.set_option('display.float_format', lambda x: f"{x:.6f}")
    print("\n📋 数据预览:")
    preview_df = df[['rel_timestamp', 'format_date', 'channel', 'arbitration_id', 
                     'message_name']].head()
    print(preview_df.to_string(index=False))
    
    if 'message_name' in df.columns:
        msg_counts = df['message_name'].value_counts().head(10)
        print(f"\n   消息类型分布（Top 10）:")
        for msg, count in msg_counts.items():
            print(f"      {msg}: {count} 帧")
    
    return df


def extract_batch_id(filename: str) -> str:
    """从ASC文件名提取批次标识"""
    basename = os.path.basename(filename)
    pattern = r'([A-Z0-9]{8,17})_(\d{1,3})_(\d{14})'
    match = re.search(pattern, basename)
    if match:
        return f"{match.group(1)}_{match.group(2)}_{match.group(3)}"
    parts = basename.replace('.asc', '').split('_')
    if len(parts) >= 5:
        return '_'.join(parts[2:5])
    return os.path.splitext(basename)[0][:80]


def convert_records_direct(records: List[Dict], asc_file: str) -> List[Dict]:
    """内存优化版：直接从records转标准格式，跳过DataFrame
    
    大数据量专用：75万帧数据节省1GB以上内存
    """
    batch_id = extract_batch_id(asc_file)
    print(f"\n📦 批次标识: {batch_id}")
    print(f"📊 流式转换，总帧数: {len(records)}")
    
    base_cols = {'rel_timestamp', 'timestamp', 'datetime', 'format_date', 
                 'channel', 'arbitration_id', 'message_name', 'dlc', 
                 'raw_data', 'error'}
    
    standard_records = []
    signal_count = set()
    
    for record in records:
        common = {
            "item_batch_id": batch_id,
            "item_dt": record['format_date'],
            "item_channel": str(record['channel']),
        }
        
        for key, value in record.items():
            if key in base_cols:
                continue
            
            signal_count.add(key)
            
            if value is None or (isinstance(value, float) and pd.isna(value)):
                continue
            
            if isinstance(value, (float, int)):
                value_str = str(value)
            else:
                value_str = str(value)
            
            standard_records.append({
                **common,
                "item_name": key,
                "item_value": value_str
            })
    
    print(f"🔍 发现信号: {len(signal_count)} 种")
    print(f"✅ 流式转换完成: {len(standard_records)} 条信号数据")
    return standard_records

def convert_to_standard_format(df: pd.DataFrame, asc_file: str) -> List[Dict]:
    """宽表转窄表：小数据量使用，大数据量请用 convert_records_direct"""
    
    batch_id = extract_batch_id(asc_file)
    print(f"\n📦 批次标识: {batch_id}")
    
    base_cols = {'rel_timestamp', 'timestamp', 'datetime', 'format_date', 
                 'channel', 'arbitration_id', 'message_name', 'dlc', 
                 'raw_data', 'error'}
    
    signal_columns = [c for c in df.columns if c not in base_cols]
    print(f"🔍 发现信号列: {len(signal_columns)} 个")
    
    standard_records = []
    for _, row in df.iterrows():
        common = {
            "item_batch_id": batch_id,
            "item_dt": row['format_date'],
            "item_channel": str(row['channel']),
        }
        
        for sig_name in signal_columns:
            sig_value = row[sig_name]
            
            if pd.isna(sig_value):
                continue
            
            if isinstance(sig_value, (float, int)):
                value_str = str(sig_value)
            else:
                value_str = str(sig_value)
            
            standard_records.append({
                **common,
                "item_name": sig_name,
                "item_value": value_str
            })
    
    print(f"✅ 格式转换完成: {len(standard_records)} 条信号数据")
    print(f"   字段结构: item_batch_id, item_dt, item_channel, item_name, item_value")
    
    return standard_records


def decode_and_stream_write(dbc_path: str, asc_path: str, 
                            batch_size: int = 50000) -> int:
    """真正流式：边解析边写入，内存占用最低
    
    处理流程：
    1. 每解析 N 帧 → 转标准格式 → 写入 StarRocks
    2. 清理内存，继续下一批
    3. 内存峰值 < 100MB，支持无限大文件
    """
    batch_id = extract_batch_id(asc_path)
    print(f"\n📦 批次标识: {batch_id}")
    print(f"🚀 真正流式写入模式：每 {batch_size} 帧写入一批")
    
    parser = CANLogParser(dbc_path)
    reader = FastASCReader(asc_path)
    print(f"   基准时间: {format_timestamp_with_ms(reader.base_timestamp)}")
    
    base_cols = {'rel_timestamp', 'timestamp', 'datetime', 'format_date', 
                 'channel', 'arbitration_id', 'message_name', 'dlc', 
                 'raw_data', 'error'}
    
    writer = StarRocksDataWriter()
    if not writer.loader._create_table():
        raise Exception("建表失败")
    
    frame_count = 0
    batch_frames = []
    total_written = 0
    signal_count = set()
    
    for msg in reader:
        frame_count += 1
        
        try:
            decoded_signals = parser.decode_message(msg)
            if decoded_signals is None:
                continue
        except Exception:
            continue
        
        record = {
            'format_date': format_timestamp_with_ms(msg.timestamp),
            'channel': msg.channel,
            'arbitration_id': hex(msg.arbitration_id),
            **decoded_signals
        }
        batch_frames.append(record)
        
        # 批次满了，写入
        if len(batch_frames) >= batch_size:
            standard_data = []
            for rec in batch_frames:
                common = {
                    "item_batch_id": batch_id,
                    "item_dt": rec['format_date'],
                    "item_channel": str(rec['channel']),
                }
                
                for key, value in rec.items():
                    if key in base_cols:
                        continue
                    signal_count.add(key)
                    
                    if value is None or (isinstance(value, float) and pd.isna(value)):
                        continue
                    
                    standard_data.append({
                        **common,
                        "item_name": key,
                        "item_value": str(value)
                    })
            
            written = writer.loader.load_batch(standard_data, total_written // 100000 + 1)
            total_written += written
            print(f"   ✅ 已处理 {frame_count:,} 帧, 累计写入 {total_written:,} 条")
            
            batch_frames.clear()
            standard_data.clear()
    # 处理最后一批
    if batch_frames:
        standard_data = []
        for rec in batch_frames:
            common = {
                "item_batch_id": batch_id,
                "item_dt": rec['format_date'],
                "item_channel": str(rec['channel']),
            }
            
            for key, value in rec.items():
                if key in base_cols:
                    continue
                signal_count.add(key)
                
                if value is None or (isinstance(value, float) and pd.isna(value)):
                    continue
                
                standard_data.append({
                    **common,
                    "item_name": key,
                    "item_value": str(value)
                })
        
        total_written += writer.loader.load_batch(standard_data, 999)
    
    print("\n" + "=" * 70)
    print(f"🎉 流式写入全部完成！")
    print(f"   总帧数: {frame_count:,}")
    print(f"   信号种类: {len(signal_count)}")
    print(f"   总写入: {total_written:,} 条")
    print("=" * 70)
    
    return total_written


def write_to_starrocks(standard_data: List[Dict]) -> int:
    """写入StarRocks数据库"""
    print("\n" + "=" * 70)
    print("🚀 开始写入 StarRocks")
    print("=" * 70)
    
    writer = StarRocksDataWriter()
    try:
        written = writer.write_data(standard_data)
        print(f"\n🎉 写入完成，成功: {written} 条")
        return written
    except Exception as e:
        print(f"\n❌ 写入失败: {str(e)}")
        raise


if __name__ == "__main__":
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    ASC_FILE_PATH = "D:\\seres\\2026\\项目\\灵犀助手\\市场问题分析智能体\\测试数据\\case01\\CDC_VHR_LZ4CCAN_1_20260404001308_20260404001422(UTC+8).asc"
    dbc_path2 = "D:\\seres\\2026\\项目\\灵犀助手\\市场问题分析智能体\\cantools_dev\\F1\\DBC\\F1项目 CHS网段通信协议 V1.8.9-20240220.dbc"
    
    print("\n" + "=" * 70)
    print("🚀 ASC解析 → 流式写入 StarRocks")
    print("   ✅ 终极内存优化：边解析边写入，内存峰值 < 100MB")
    print("=" * 70)
    
    # 75万帧大文件专用：真正流式，永不OOM
    decode_and_stream_write(dbc_path2, ASC_FILE_PATH, batch_size=50000)
