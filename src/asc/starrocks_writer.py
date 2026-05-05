import json
import base64
from datetime import datetime
import logging
import requests
import pymysql
from typing import List, Dict, Optional


logger = logging.getLogger("rc")


class StarRocksConfig:
    """StarRocks连接配置"""
    HOST = ""
    FE_HOST = ""
    QUERY_PORT = 9
    STREAM_HTTP_PORT = 9
    USER = ""
    PASSWORD = ""
    DATABASE = ""
    TABLE = ""
    
    STREAM_BATCH_SIZE = 300000


class StarRocksStreamLoader:
    """StarRocks Stream Load高性能写入器"""
    
    def __init__(self, config: StarRocksConfig):
        self.config = config
        self.stream_load_url = (
            f"http://{config.FE_HOST}:{config.STREAM_HTTP_PORT}"
            f"/api/{config.DATABASE}/{config.TABLE}/_stream_load"
        )
    
    def _create_table(self) -> bool:
        """建表"""
        try:
            conn = pymysql.connect(
                host=self.config.HOST,
                port=self.config.QUERY_PORT,
                user=self.config.USER,
                password=self.config.PASSWORD,
                database=self.config.DATABASE,
                charset='utf8mb4',
            )
            cursor = conn.cursor()
            
            create_table_sql = f"""
            CREATE TABLE IF NOT EXISTS `{self.config.TABLE}` (
                `item_batch_id` VARCHAR(100) NOT NULL COMMENT '批次标识',
                `item_dt` VARCHAR(30) NOT NULL COMMENT '时间戳',
                `item_channel` VARCHAR(10) NOT NULL COMMENT 'CAN通道编号',
                `item_name` VARCHAR(255) NOT NULL COMMENT '信号名称',
                `item_value` VARCHAR(255) NOT NULL COMMENT '信号值',
                `insert_time` DATETIME NOT NULL COMMENT '写入时间'
            ) ENGINE=OLAP
            DUPLICATE KEY(`item_batch_id`, `item_dt`, `item_channel`, `item_name`)
            COMMENT 'CAN信号数据表'
            DISTRIBUTED BY HASH(`item_batch_id`) BUCKETS 16
            PROPERTIES (
                "replication_num" = "3",
                "enable_persistent_index" = "true"
            )
            """
            cursor.execute(create_table_sql)
            conn.commit()
            cursor.close()
            conn.close()
            logger.info(f"[StreamLoad] 建表成功: {self.config.TABLE}")
            return True
        except Exception as e:
            logger.error(f"[StreamLoad] 建表失败: {e}")
            return False
    
    def _send_stream_load(self, csv_data: str, label: str) -> int:
        """执行单次Stream Load请求"""
        auth_str = f"{self.config.USER}:{self.config.PASSWORD}"
        auth_b64 = base64.b64encode(auth_str.encode('utf-8')).decode('ascii')
        
        headers = {
            "Content-Type": "text/plain; charset=utf-8",
            "Authorization": f"Basic {auth_b64}",
            "Expect": "100-continue",
            "label": label,
            "columns": "item_batch_id,item_dt,item_channel,item_name,item_value,insert_time",
            "column_separator": "\\x01",
            "format": "csv",
            "skip_header": "0",
            "strict_mode": "false",
            "max_filter_ratio": "1.0",
            "timeout": "600",
        }
        
        try:
            no_proxy = {"http": None, "https": None}
            url = self.stream_load_url
            
            for redirect_count in range(5):
                response = requests.put(
                    url,
                    headers=headers,
                    data=csv_data.encode('utf-8'),
                    timeout=600,
                    proxies=no_proxy,
                    allow_redirects=False
                )
                
                if response.status_code != 307:
                    break
                location = response.headers.get('Location')
                logger.debug(f"  ↪️ 307重定向到BE: {location}")
                url = location
            else:
                raise Exception("重定向次数超过5次，放弃")
                
        except requests.exceptions.RequestException as e:
            logger.error(f"请求异常: {type(e).__name__}: {str(e)}")
            raise
        
        if response.status_code not in (200, 201):
            logger.error(f"❌ StreamLoad HTTP错误: {response.status_code}")
            logger.error(f"响应内容: {response.text[:2000]}")
            raise Exception(f"HTTP {response.status_code}")
        
        try:
            result = response.json()
        except Exception as e:
            logger.error(f"JSON解析失败: {response.text[:2000]}")
            raise
        
        if result.get("Status") == "Success":
            return int(result.get("NumberLoadedRows", 0))
        
        msg = result.get("Message", "")
        if "No partitions have data available" in msg or "empty" in msg.lower():
            return 0
        
        logger.error(f"❌ StreamLoad错误: {msg}")
        raise Exception(f"StreamLoad失败: {msg}")
    def load_batch(self, batch_data: List[Dict], batch_idx: int) -> int:
        """加载一批数据"""
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        timestamp = int(datetime.now().timestamp())
        label = f"can_{timestamp}_{batch_idx}"
        
        sep = "\x01"
        csv_lines = []
        for item in batch_data:
            csv_lines.append(
                f'{item.get("item_batch_id", "unknown")}{sep}'
                f'{item.get("item_dt")}{sep}'
                f'{item.get("item_channel", "0")}{sep}'
                f'{item.get("item_name")}{sep}'
                f'{item.get("item_value")}{sep}'
                f'{current_time}'
            )
        csv_data = "\n".join(csv_lines)
        
        max_retries = 5
        retry_delays = [5, 10, 30, 60]

        for retry in range(max_retries):
            try:
                loaded = self._send_stream_load(csv_data, label)
                logger.info(f"✅ 批次 {batch_idx}: 写入成功 {loaded:,} 条")
                return loaded
            except Exception as e:
                if retry < max_retries - 1:
                    delay = retry_delays[min(retry, len(retry_delays) - 1)]
                    logger.warning(f"⚠️ 批次 {batch_idx}: 第 {retry+1} 次失败, {delay}秒后重试")
                    import time
                    time.sleep(delay)
                else:
                    logger.error(f"❌ 批次 {batch_idx}: 经过 {max_retries} 次尝试最终失败!")
                    raise


class StarRocksDataWriter:
    """StarRocks数据写入入口"""
    
    def __init__(self, config: Optional[StarRocksConfig] = None):
        self.config = config or StarRocksConfig()
        self.loader = StarRocksStreamLoader(self.config)
        self.total_written = 0
    
    def _batch_iterator(self, data: List[Dict]):
        """数据分批迭代器"""
        batch_size = self.config.STREAM_BATCH_SIZE
        for i in range(0, len(data), batch_size):
            yield data[i:i + batch_size]
    
    def write_data(self, data: List[Dict]) -> int:
        """写入所有数据"""
        if not data:
            logger.info("无数据可写入")
            return 0
        
        logger.info("=" * 70)
        logger.info(f"准备使用StreamLoad写入 {len(data)} 条数据")
        logger.info("=" * 70)
        
        if not self.loader._create_table():
            raise Exception("建表失败")
        
        self.total_written = 0
        total_batches = (len(data) + self.config.STREAM_BATCH_SIZE - 1) // self.config.STREAM_BATCH_SIZE
        
        logger.info(f"分 {total_batches} 批写入，每批约 {self.config.STREAM_BATCH_SIZE} 条")
        
        for batch_idx, batch_data in enumerate(self._batch_iterator(data), 1):
            logger.info(f"写入第 {batch_idx}/{total_batches} 批...")
            self.total_written += self.loader.load_batch(batch_data, batch_idx)
        
        logger.info("=" * 70)
        logger.info(f"✅ StreamLoad全部完成，共写入: {self.total_written} 条")
        logger.info("=" * 70)
        
        return self.total_written        