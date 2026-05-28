import os
from typing import Dict

from writer.stream_loader import BaseStarRocksConfig, BaseStreamLoader

CAN_DDL = """
CREATE TABLE IF NOT EXISTS `{table}` (
    `item_batch_id` VARCHAR(100) NOT NULL COMMENT '批次标识',
    `item_dt` VARCHAR(30) NOT NULL COMMENT '时间戳',
    `item_channel` VARCHAR(10) NOT NULL COMMENT 'CAN通道编号',
    `item_name` VARCHAR(255) NOT NULL COMMENT '信号名称',
    `item_value` VARCHAR(255) NOT NULL COMMENT '信号值',
    `insert_time` DATETIME NOT NULL COMMENT '写入时间'
) ENGINE=OLAP
DUPLICATE KEY(`item_batch_id`, `item_dt`, `item_channel`, `item_name`)
COMMENT 'CAN信号数据表'
DISTRIBUTED BY HASH(`item_batch_id`) BUCKETS 2
PROPERTIES (
    "replication_num" = "3",
    "enable_persistent_index" = "true"
)
"""

CAN_COLUMNS = "item_batch_id,item_dt,item_channel,item_name,item_value,insert_time"


class StarRocksConfig(BaseStarRocksConfig):
    TABLE = os.environ.get("SR_CAN_TABLE", "ods_mkt_analysis_can_signal")


class StarRocksStreamLoader(BaseStreamLoader):
    label_prefix = "can"
    columns_header = CAN_COLUMNS

    def __init__(self, config=None):
        if config is None:
            config = StarRocksConfig()
        super().__init__(config)
        self.ddl_sql = CAN_DDL.format(table=self.config.TABLE)

    def _format_row(self, item: Dict, current_time: str) -> str:
        sep = "\x01"
        return (
            f'{item.get("item_batch_id", "unknown")}{sep}'
            f'{item.get("item_dt")}{sep}'
            f'{item.get("item_channel", "0")}{sep}'
            f'{item.get("item_name")}{sep}'
            f'{item.get("item_value")}{sep}'
            f'{current_time}'
        )


class StarRocksDataWriter:
    def __init__(self, config=None):
        self.config = config or StarRocksConfig()
        self.loader = StarRocksStreamLoader(self.config)
