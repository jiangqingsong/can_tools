# Phase 7 技术债清理实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 清理 Phase 7 技术债：抽取 ASC/BLF 共用基类、Writer 共用 Stream Load 组件、删除 main.py 桩代码、修复 sys.path hack

**Architecture:** 纯重构，行为不变。新增 `parsers/can_parser.py`（共用解码逻辑）和 `writer/stream_loader.py`（Stream Load 通用基类），原有文件缩为薄壳继承。外部接口（函数签名、类名、方法）完全兼容。

**Tech Stack:** Python 3.12, cantools, python-can

---

## 文件结构

| 文件 | 操作 | 职责 |
|------|------|------|
| `src/can_parser_server/parsers/can_parser.py` | 新增 | ASC/BLF 共用解码逻辑 `decode_can()` |
| `src/writer/stream_loader.py` | 新增 | Stream Load 通用基类 `BaseStreamLoader` |
| `src/can_parser_server/parsers/asc_parser.py` | 修改 | 薄壳，调 `decode_can(reader_class=can.ASCReader, ...)` |
| `src/can_parser_server/parsers/blf_parser.py` | 修改 | 薄壳，调 `decode_can(reader_class=can.BLFReader, ...)` |
| `src/can_parser_server/parsers/__init__.py` | 修改 | 删除 `sys.path.insert` hack，新增 `can_parser` 导出 |
| `src/can_parser_server/api_server.py` | 修改 | 入口文件加 `sys.path.insert`（从 `__init__.py` 挪过来） |
| `src/writer/can_2_sr.py` | 修改 | 继承 `BaseStreamLoader`，仅保留 CAN 特有配置 |
| `src/writer/csv_2_sr.py` | 修改 | 继承 `BaseStreamLoader`，仅保留 CSV 特有配置 |
| `main.py` | 删除 | Hello World 桩代码 |

---

### Task 1: 创建 Writer 共用基类 `stream_loader.py`

**Files:**
- Create: `src/writer/stream_loader.py`

- [ ] **Step 1: 创建 `stream_loader.py`**

```python
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
```

- [ ] **Step 2: 验证文件语法正确**

```bash
python -c "import sys; sys.path.insert(0, 'src'); from writer.stream_loader import BaseStreamLoader; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: 提交**

```bash
git add src/writer/stream_loader.py
git commit -m "writer: 抽取 Stream Load 通用基类 BaseStreamLoader"
```

---

### Task 2: 重构 `can_2_sr.py` 继承基类

**Files:**
- Modify: `src/writer/can_2_sr.py`

- [ ] **Step 1: 重写 `can_2_sr.py`**

```python
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
```

- [ ] **Step 2: 验证导入**

```bash
python -c "import sys; sys.path.insert(0, 'src'); from writer.can_2_sr import StarRocksDataWriter, StarRocksConfig, StarRocksStreamLoader; w = StarRocksDataWriter(); print('OK')"
```

Expected: `OK`

- [ ] **Step 3: 提交**

```bash
git add src/writer/can_2_sr.py
git commit -m "writer: can_2_sr 继承 BaseStreamLoader，删除重复代码"
```

---

### Task 3: 重构 `csv_2_sr.py` 继承基类

**Files:**
- Modify: `src/writer/csv_2_sr.py`

- [ ] **Step 1: 重写 `csv_2_sr.py`**

```python
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
```

- [ ] **Step 2: 验证导入**

```bash
python -c "import sys; sys.path.insert(0, 'src'); from writer.csv_2_sr import CsvDataWriter; w = CsvDataWriter(); print('OK')"
```

Expected: `OK`

- [ ] **Step 3: 提交**

```bash
git add src/writer/csv_2_sr.py
git commit -m "writer: csv_2_sr 继承 BaseStreamLoader，删除重复代码"
```

---

### Task 4: 创建 ASC/BLF 共用解码逻辑 `can_parser.py`

**Files:**
- Create: `src/can_parser_server/parsers/can_parser.py`

- [ ] **Step 1: 创建 `can_parser.py`**

```python
import cantools
import can
from datetime import datetime
import logging
from typing import List, Dict

from writer.can_2_sr import StarRocksDataWriter

logger = logging.getLogger("rc")
logger.setLevel(logging.INFO)


def decode_can(
    parser_type: str,
    batch_id: str,
    data_file: str,
    dbc_files: List[str],
    reader_class,
    reader_kwargs: dict,
    batch_size: int = 5000,
    signal_filter_list: List[str] = None,
):
    start = datetime.now()
    start_fmt = start.strftime('%Y-%m-%d %H:%M:%S')
    print(f"{parser_type} decode开始:{start_fmt}, {parser_type}: {data_file}, dbc_files: {dbc_files}")

    signal_filter_set = set(signal_filter_list) if signal_filter_list else None
    if signal_filter_set:
        print(f"\U0001F3AF 信号过滤已启用，将解析 {len(signal_filter_set)} 个信号:")
        for sig in sorted(signal_filter_set):
            print(f"    - {sig}")
    else:
        print(f"ℹ️  信号过滤未启用，将解析全量信号")

    dbc_db = cantools.database.load_file(dbc_files[0], encoding='gb2312')
    for dbc_file in dbc_files[1:]:
        dbc_db.add_dbc_file(dbc_file, encoding='gb2312')
    can_data = reader_class(data_file, **reader_kwargs)
    print(f"读取dbc、{parser_type.upper()}文件成功！")

    writer = StarRocksDataWriter()

    undecoded = []
    msg_start_time = 0
    msg_end_time = 0
    total_written = 0
    total_parsed = 0
    total_filtered = 0

    current_batch: List[Dict] = []

    batch_idx = 1
    for msg in can_data:
        msg_id = msg.arbitration_id
        msg_data = msg.data
        msg_channel = getattr(msg, 'channel', '0')

        try:
            message = dbc_db.decode_message(msg_id, msg_data)
        except Exception:
            undecoded.append(msg)
            continue

        if msg_start_time == 0 or msg_start_time > msg.timestamp:
            msg_start_time = msg.timestamp
        if msg_end_time == 0 or msg_end_time < msg.timestamp:
            msg_end_time = msg.timestamp

        dt = datetime.fromtimestamp(msg.timestamp)
        item_dt = dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        for item in message.items():
            item_name = item[0]

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

            if len(current_batch) >= batch_size:
                total_written += writer.loader.load_batch(current_batch, batch_idx)
                batch_idx += 1
                current_batch = []
                print(f"  ✅ 累计写入 {total_written:,} 条")

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
        f"{parser_type} decode结束:{end_fmt}, 耗时: {spend}秒, "
        f"解析成功: {total_parsed}, 解析失败: {len(undecoded)}, "
        f"过滤信号: {total_filtered}, "
        f"写入成功: {total_written}, "
        f"消息开始时间:{msg_start_time_f}, 消息结束时间:{msg_end_time_f}"
    )

    return total_written
```

- [ ] **Step 2: 验证语法**

```bash
python -c "import sys; sys.path.insert(0, 'src'); from can_parser_server.parsers.can_parser import decode_can; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: 提交**

```bash
git add src/can_parser_server/parsers/can_parser.py
git commit -m "parser: 抽取 ASC/BLF 共用解码逻辑 decode_can"
```

---

### Task 5: 缩减 `asc_parser.py` 为薄壳

**Files:**
- Modify: `src/can_parser_server/parsers/asc_parser.py`

- [ ] **Step 1: 重写 `asc_parser.py`**

```python
import can
from typing import List

from .can_parser import decode_can


def decode(batch_id: str, data_file: str, dbc_files: List[str],
           batch_size: int = 5000, signal_filter_list: List[str] = None):
    return decode_can(
        parser_type="asc",
        batch_id=batch_id,
        data_file=data_file,
        dbc_files=dbc_files,
        reader_class=can.ASCReader,
        reader_kwargs={"relative_timestamp": False, "encoding": "utf8"},
        batch_size=batch_size,
        signal_filter_list=signal_filter_list,
    )
```

- [ ] **Step 2: 验证导入**

```bash
python -c "import sys; sys.path.insert(0, 'src'); from can_parser_server.parsers.asc_parser import decode; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: 提交**

```bash
git add src/can_parser_server/parsers/asc_parser.py
git commit -m "parser: asc_parser 缩减为薄壳，调 decode_can"
```

---

### Task 6: 缩减 `blf_parser.py` 为薄壳

**Files:**
- Modify: `src/can_parser_server/parsers/blf_parser.py`

- [ ] **Step 1: 重写 `blf_parser.py`**

```python
import can
from typing import List

from .can_parser import decode_can


def decode(batch_id: str, data_file: str, dbc_files: List[str],
           batch_size: int = 5000, signal_filter_list: List[str] = None):
    return decode_can(
        parser_type="blf",
        batch_id=batch_id,
        data_file=data_file,
        dbc_files=dbc_files,
        reader_class=can.BLFReader,
        reader_kwargs={},
        batch_size=batch_size,
        signal_filter_list=signal_filter_list,
    )
```

- [ ] **Step 2: 验证导入**

```bash
python -c "import sys; sys.path.insert(0, 'src'); from can_parser_server.parsers.blf_parser import decode; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: 提交**

```bash
git add src/can_parser_server/parsers/blf_parser.py
git commit -m "parser: blf_parser 缩减为薄壳，调 decode_can"
```

---

### Task 7: 修复 sys.path hack + 清理 `__init__.py`

**Files:**
- Modify: `src/can_parser_server/parsers/__init__.py`
- Modify: `src/can_parser_server/api_server.py`

- [ ] **Step 1: 重写 `parsers/__init__.py`**

```python
from .asc_parser import decode as decode_asc
from .blf_parser import decode as decode_blf
from .csv_parser import decode as decode_csv

__all__ = ['decode_asc', 'decode_blf', 'decode_csv']
```

- [ ] **Step 2: 在 `api_server.py` 顶部加 sys.path.insert**

在 `api_server.py` 第 1 行之前插入 `import sys`，在 `BASE_DIR = Path(__file__).parent` 之后加 `sys.path.insert(0, str(BASE_DIR.parent))`。

最终 `api_server.py` 前 15 行变为：

```python
import os
import sys
import json
import uuid
import time
import shutil
import threading
from pathlib import Path
from typing import Optional, Dict
from fastapi import FastAPI, File, UploadFile, Form, HTTPException

from parsers import decode_asc, decode_blf, decode_csv

app = FastAPI(title="CAN Data Parser Service", version="2.0.0")

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR.parent))
```

其余部分不变。

- [ ] **Step 3: 验证 api_server 导入正常**

```bash
cd src/can_parser_server && python -c "from api_server import app; print('OK')"
```

Expected: `OK`（会打印模型配置加载日志）

- [ ] **Step 4: 提交**

```bash
git add src/can_parser_server/parsers/__init__.py src/can_parser_server/api_server.py
git commit -m "parser: 修复 sys.path hack，从 __init__.py 移至 api_server.py 入口"
```

---

### Task 8: 删除 `main.py` 桩代码

**Files:**
- Delete: `main.py`

- [ ] **Step 1: 删除 main.py**

```bash
rm main.py
```

- [ ] **Step 2: 确认无引用**

```bash
grep -r "main" --include="*.py" --include="*.md" --include="*.txt" --include="*.json" --include="*.yaml" --include="*.yml" . --exclude-dir=.venv --exclude-dir=.git 2>/dev/null | grep -v "if __name__" | grep -v "from .*main import" | grep -v "uvicorn.main" | grep -v "pydantic.main" | grep -v "pip._internal.main" || echo "无引用"
```

- [ ] **Step 3: 提交**

```bash
git add main.py
git commit -m "chore: 删除 main.py 无用桩代码"
```

---

### Task 9: 端到端验证

**Files:** 无需修改，验证重构后功能正常

- [ ] **Step 1: 启动服务**

```bash
cd src/can_parser_server && python api_server.py &
sleep 3
```

Expected: 服务启动，打印模型配置加载日志

- [ ] **Step 2: 健康检查**

```bash
curl -s http://localhost:8000/health | python -m json.tool
```

Expected: `{"status": "ok", "supported_types": ["asc", "blf", "csv"]}`

- [ ] **Step 3: 模型列表接口**

```bash
curl -s http://localhost:8000/api/v1/models | python -m json.tool
```

Expected: 返回车型和模型列表

- [ ] **Step 4: 停止服务**

```bash
kill %1 2>/dev/null || true
```

- [ ] **Step 5: 提交（如有微调）**

```bash
git diff --exit-code || (git add -A && git commit -m "chore: 端到端验证后微调")
```
