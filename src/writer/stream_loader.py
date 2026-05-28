import base64
import time
from datetime import datetime
import logging
import os
import requests
import pymysql
from typing import List, Dict

logger = logging.getLogger("rc")
logger.setLevel(logging.INFO)


class BaseStarRocksConfig:
    HOST = os.environ.get("SR_HOST", "")
    FE = os.environ.get("SR_FE", "")
    QUERY_PORT = int(os.environ.get("SR_QUERY_PORT", "9030"))
    STREAM_HTTP_PORT = int(os.environ.get("SR_STREAM_HTTP_PORT", "8010"))
    USER = os.environ.get("SR_USER", "")
    PD = os.environ.get("SR_PASSWORD", "")
    DATABASE = os.environ.get("SR_DATABASE", "")
    TABLE = os.environ.get("SR_CAN_TABLE", "ods_mkt_analysis_can_signal")
    STREAM_BATCH_SIZE = int(os.environ.get("SR_STREAM_BATCH_SIZE", "300000"))


class BaseStreamLoader:
    label_prefix: str = ""
    columns_header: str = ""
    ddl_sql: str = ""

    def __init__(self, config: BaseStarRocksConfig):
        self.config = config
        self.stream_load_url = (
            f"http://{config.FE}:{config.STREAM_HTTP_PORT}"
            f"/api/{config.DATABASE}/{config.TABLE}/_stream_load"
        )

    def _create_table(self) -> bool:
        try:
            conn = pymysql.connect(
                host=self.config.HOST,
                port=self.config.QUERY_PORT,
                user=self.config.USER,
                password=self.config.PD,
                database=self.config.DATABASE,
                charset='utf8mb4'
            )
            cursor = conn.cursor()
            cursor.execute(self.ddl_sql)
            conn.commit()
            cursor.close()
            conn.close()
            logger.info(f"[StreamLoad] 建表成功: {self.config.TABLE}")
            return True
        except Exception as e:
            logger.error(f"[StreamLoad] 建表失败: {e}")
            return False

    def _send_stream_load(self, csv_data: str, label: str) -> int:
        auth_str = f"{self.config.USER}:{self.config.PD}"
        auth_b64 = base64.b64encode(auth_str.encode('utf-8')).decode('ascii')
        headers = {
            "Content-Type": "text/plain; charset=utf-8",
            "Authorization": f"Basic {auth_b64}",
            "Expect": "100-continue",
            "label": label,
            "columns": self.columns_header,
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
                logger.debug(f" ↪ 307重定向到BE: {location}")
                url = location
            else:
                raise Exception("重定向次数超过5次，放弃")
        except requests.exceptions.RequestException as e:
            logger.error(f"请求异常: {type(e).__name__}: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"发送数据异常: {str(e)}")
            raise

        if response.status_code not in (200, 201):
            logger.error(f"✗ StreamLoad HTTP错误: {response.status_code}")
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

        logger.error(f"✗ StreamLoad错误:{msg}")
        raise Exception(f"StreamLoad失败:{msg}")

    def _format_row(self, item: Dict, current_time: str) -> str:
        raise NotImplementedError

    def load_batch(self, batch_data: List[Dict], batch_idx: int) -> int:
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        timestamp = int(datetime.now().timestamp())
        label = f"{self.label_prefix}_{timestamp}_{batch_idx}"
        csv_lines = [self._format_row(item, current_time) for item in batch_data]
        csv_data = "\n".join(csv_lines)

        max_retries = 5
        retry_delays = [5, 10, 30, 60]
        for retry in range(max_retries):
            try:
                loaded = self._send_stream_load(csv_data, label)
                logger.info(f" ✅ 批次{batch_idx}: 写入成功 {loaded:,} 条")
                return loaded
            except Exception as e:
                print(f"写入数据异常: {str(e)}")
                if retry < max_retries - 1:
                    delay = retry_delays[min(retry, len(retry_delays) - 1)]
                    logger.warning(f"⚠ 批次{batch_idx}: 第 {retry+1} 次失败, {delay}秒后重试")
                    time.sleep(delay)
                else:
                    logger.error(f"✗ 批次{batch_idx}: 经过 {max_retries} 次尝试最终失败!")
                    raise
