import cantools
import can
from datetime import datetime
import logging
from typing import List, Dict

from writer.can_2_sr import StarRocksDataWriter

logger = logging.getLogger("rc")
# 设置 logger 级别为 INFO
logger.setLevel(logging.INFO)


def decode(batch_id: str, data_file: str, dbc_files: List[str],
           batch_size: int = 5000, signal_filter_list: List[str] = None):
    """
    解码ASC文件为StarRocks数据表

    Args:
        batch_id: 批次ID
        data_file: ASC文件路径
        dbc_files: DBC文件路径列表（支持多个DBC文件）
        batch_size: 每批写入 StarRocks 的条数, 默认 5000
        signal_filter_list: 需要解析的信号列表, None 或空列表表示解析所有信号
    """

    start = datetime.now()
    start_fmt = start.strftime('%Y-%m-%d %H:%M:%S')
    print(f"asc decode开始:{start_fmt}, asc: {data_file}, dbc_files: {dbc_files}")

    # 信号过滤配置
    signal_filter_set = set(signal_filter_list) if signal_filter_list else None
    if signal_filter_set:
        print(f"🎯 信号过滤已启用，将解析 {len(signal_filter_set)} 个信号:")
        for sig in sorted(signal_filter_set):
            print(f"    - {sig}")
    else:
        print(f"ℹ️  信号过滤未启用，将解析全量信号")

    dbc_db = cantools.database.load_file(dbc_files[0], encoding='gb2312')
    for dbc_file in dbc_files[1:]:
        dbc_db.add_dbc_file(dbc_file, encoding='gb2312')
    asc_data = can.ASCReader(data_file, relative_timestamp=False, encoding='utf8')
    print("读取dbc、ASC文件成功！")

    writer = StarRocksDataWriter()

    undecoded = []
    msg_start_time = 0
    msg_end_time = 0
    total_written = 0
    total_parsed = 0
    total_filtered = 0  # 被过滤掉的信号数量

    # 当前批次缓冲区
    current_batch: List[Dict] = []

    batch_idx = 1
    for msg in asc_data:
        msg_id = msg.arbitration_id
        msg_data = msg.data
        msg_channel = getattr(msg, 'channel', '0')

        try:
            message = dbc_db.decode_message(msg_id, msg_data)
        except Exception as e:
            undecoded.append(msg)
            continue

        # 记录消息时间范围
        if msg_start_time == 0 or msg_start_time > msg.timestamp:
            msg_start_time = msg.timestamp
        if msg_end_time == 0 or msg_end_time < msg.timestamp:
            msg_end_time = msg.timestamp

        dt = datetime.fromtimestamp(msg.timestamp)
        item_dt = dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        for item in message.items():
            item_name = item[0]

            # 信号过滤: 如果启用了过滤且信号不在列表中，则跳过
            if signal_filter_set and item_name not in signal_filter_set:
                total_filtered += 1
                continue

            if type(item[1]) is float or type(item[1]) is int:
                item_value = str(item[1])
            else:
                item_value = str(item[1].value)

            item_data = {
                "item_batch_id": batch_id,
                "item_dt": item_dt,
                "item_channel": str(msg_channel),
                "item_name": item_name,
                "item_value": item_value
            }
            current_batch.append(item_data)
            total_parsed += 1

            # ===== 达到批次大小，立即写入 =====
            if len(current_batch) >= batch_size:
                total_written += writer.loader.load_batch(current_batch, batch_idx)
                # total_written += write_batch_to_starrocks(current_batch, batch_idx)
                batch_idx += 1
                current_batch = []  # 清空缓冲区
                print(f"  ✅ 累计写入 {total_written:,} 条")

    # ===== 写入剩余未达批次大小的数据 =====
    if current_batch:
        total_written += writer.loader.load_batch(current_batch, batch_idx)

    error_ids = set(map(lambda m: m.arbitration_id, undecoded))
    if error_ids:
        logger.info("The following IDs caused errors: " + str(error_ids))

    end = datetime.now()
    end_fmt = end.strftime('%Y-%m-%d %H:%M:%S')
    msg_start_time_f = datetime.fromtimestamp(msg_start_time).strftime("%Y-%m-%d %H:%M:%S.%f")[
                       :-3] if msg_start_time else "N/A"
    msg_end_time_f = datetime.fromtimestamp(msg_end_time).strftime("%Y-%m-%d %H:%M:%S.%f")[
                     :-3] if msg_end_time else "N/A"
    spend = end - start

    print(
        f"asc decode结束:{end_fmt}, 耗时: {spend}秒, "
        f"解析成功: {total_parsed}, 解析失败: {len(undecoded)}, "
        f"过滤信号: {total_filtered}, "
        f"写入成功: {total_written}, "
        f"消息开始时间:{msg_start_time_f}, 消息结束时间:{msg_end_time_f}"
    )

    return total_written