import os
import pandas as pd
from datetime import datetime
import logging

from writer.csv_2_sr import CsvDataWriter

logger = logging.getLogger("rc")
logger.setLevel(logging.INFO)


def decode(batch_id: str, data_file: str, batch_size: int = 5000):
    """
    解析Excel/CSV文件为StarRocks CSV信号数据表

    文件格式:
        第1列: 采集时间
        第2列: 平台接收时间
        第3列: 数据上报类型
        第4列及以后: 信号数据列 (列名即为信号名, 数量不固定)

    每行数据会扁平化为: 文件名(batch_id), 采集时间, 平台接收时间, 信号名, 信号值, 插入时间

    Args:
        batch_id: 批次标识 (直接用作文件名写入表)
        data_file: Excel/CSV文件路径
        batch_size: 每批写入 StarRocks 的条数, 默认 5000
    """

    start = datetime.now()
    start_fmt = start.strftime('%Y-%m-%d %H:%M:%S')
    file_name = batch_id
    print(f"csv decode开始: {start_fmt}, file: {data_file}")

    # 读取Excel/CSV文件, 自动处理编码
    if data_file.lower().endswith('.csv'):
        # 尝试多种编码, 兼容中文文件
        for enc in ('utf-8', 'gbk', 'gb2312', 'gb18030', 'latin-1'):
            try:
                df = pd.read_csv(data_file, dtype=str, encoding=enc)
                break
            except (UnicodeDecodeError, UnicodeError):
                continue
        else:
            df = pd.read_csv(data_file, dtype=str, encoding='utf-8', errors='replace')
    else:
        df = pd.read_excel(data_file, dtype=str, engine='openpyxl')

    # 第4列及以后为信号列
    signal_cols = df.columns[3:].toList()
    print(f"读取文件成功! 共 {len(df)} 行, {len(signal_cols)} 个信号列")

    writer = CsvDataWriter()
    current_batch = []
    total_written = 0
    total_parsed = 0
    batch_idx = 1

    for _, row in df.iterrows():
        collect_time = str(row.iloc[0]) if pd.notna(row.iloc[0]) else ""
        platform_time = str(row.iloc[1]) if pd.notna(row.iloc[1]) else ""

        for col_name in signal_cols:
            col_idx = df.columns.get_loc(col_name)
            signal_value = str(row.iloc[col_idx]) if pd.notna(row.iloc[col_idx]) else ""

            item_data = {
                "file_name": file_name,
                "collect_time": collect_time,
                "platform_time": platform_time,
                "signal_name": col_name.split("(")[0],
                "signal_value": signal_value
            }
            current_batch.append(item_data)
            total_parsed += 1

            if len(current_batch) >= batch_size:
                total_written += writer.loader.load_batch(current_batch, batch_idx)
                batch_idx += 1
                current_batch = []
                print(f"  ✅ 累计写入 {total_written:,} 条")

    # 写入剩余数据
    if current_batch:
        total_written += writer.loader.load_batch(current_batch, batch_idx)

    end = datetime.now()
    end_fmt = end.strftime('%Y-%m-%d %H:%M:%S')
    spend = end - start

    print(
        f"csv decode结束: {end_fmt}, 耗时: {spend}秒, "
        f"解析成功: {total_parsed}, "
        f"写入成功: {total_written}"
    )

    return total_written