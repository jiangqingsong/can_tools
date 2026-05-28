import os
from typing import Dict

from writer.stream_loader import BaseStarRocksConfig, BaseStreamLoader

CSV_DDL = """
CREATE TABLE IF NOT EXISTS `{table}` (
    `file_name` VARCHAR(500) NOT NULL COMMENT '文件名',
    `collect_time` VARCHAR(30) NOT NULL COMMENT '采集时间',
    `platform_time` VARCHAR(30) NOT NULL COMMENT '平台接收时间',
    `signal_name` VARCHAR(255) NOT NULL COMMENT '信号名',
    `signal_value` VARCHAR(255) NOT NULL COMMENT '信号值',
    `insert_time` DATETIME NOT NULL COMMENT '插入时间'
) ENGINE=OLAP
DUPLICATE KEY(`file_name`, `collect_time`, `signal_name`)
COMMENT 'CSV信号数据表'
DISTRIBUTED BY HASH(`file_name`) BUCKETS 1
PROPERTIES (
    "replication_num" = "3",
    "enable_persistent_index" = "true"
)
"""

CSV_COLUMNS = "file_name,collect_time,platform_time,signal_name,signal_value,insert_time"


class CsvStarRocksConfig(BaseStarRocksConfig):
    TABLE = os.environ.get("SR_CSV_TABLE", "ods_csv_signal_data")


class CsvStreamLoader(BaseStreamLoader):
    label_prefix = "csv"
    columns_header = CSV_COLUMNS

    def __init__(self, config=None):
        if config is None:
            config = CsvStarRocksConfig()
        super().__init__(config)
        self.ddl_sql = CSV_DDL.format(table=self.config.TABLE)

    def _format_row(self, item: Dict, current_time: str) -> str:
        sep = "\x01"
        return (
            f'{item.get("file_name", "unknown")}{sep}'
            f'{item.get("collect_time", "")}{sep}'
            f'{item.get("platform_time", "")}{sep}'
            f'{item.get("signal_name", "")}{sep}'
            f'{item.get("signal_value", "")}{sep}'
            f'{current_time}'
        )


class CsvDataWriter:
    def __init__(self, config=None):
        self.config = config or CsvStarRocksConfig()
        self.loader = CsvStreamLoader(self.config)
