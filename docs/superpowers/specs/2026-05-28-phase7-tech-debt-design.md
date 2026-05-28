# Phase 7 技术债清理设计文档

## 概述

Phase 7 技术债清理，包含 4 项任务：抽取 ASC/BLF 解析器共用基类（7.1）、抽取 Writer 共用 Stream Load 组件（7.2）、清理 main.py 无用桩代码（7.4）、修复 parser 模块 sys.path hack（7.6）。

排除 7.3（单元测试）和 7.5（任务持久化），后续单独处理。

## 7.1 ASC/BLF 解析器抽取共用基类

### 现状

`asc_parser.py` 和 `blf_parser.py` 的 `decode()` 函数几乎完全一致（135 行 vs 137 行），唯一差异：

- ASC: `can.ASCReader(data_file, relative_timestamp=False, encoding='utf8')`
- BLF: `can.BLFReader(data_file)`
- 日志前缀 "asc" vs "blf"

### 方案

新增 `parsers/can_parser.py`，将共用逻辑抽取为 `decode_can()` 函数。通过参数 `reader_class` 和 `reader_kwargs` 让调用方注入 Reader 类型。

**函数签名：**
```python
def decode_can(
    parser_type: str,          # "asc" | "blf"，仅用于日志
    batch_id: str,
    data_file: str,
    dbc_files: List[str],
    reader_class,              # can.ASCReader | can.BLFReader
    reader_kwargs: dict,       # Reader 构造参数
    batch_size: int = 5000,
    signal_filter_list: List[str] = None,
) -> int:
```

**asc_parser.py / blf_parser.py** 的 `decode()` 缩为一行调用：
```python
def decode(batch_id, data_file, dbc_files, batch_size=5000, signal_filter_list=None):
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

### 影响范围

- 新增 `parsers/can_parser.py`
- 修改 `asc_parser.py`、`blf_parser.py` — 缩减为薄壳
- `parsers/__init__.py` 导出不变（`decode_asc` / `decode_blf` 仍指向各自 decode）
- `api_server.py` 无需改动

## 7.2 Writer 抽取共用 Stream Load 组件

### 现状

`can_2_sr.py` 和 `csv_2_sr.py` 的 Stream Load 底层（`_send_stream_load`、`load_batch`）几乎完全一致，重试逻辑重复。差异仅在：

| 差异点 | can_2_sr | csv_2_sr |
|--------|----------|----------|
| 表名默认值 | ods_mkt_analysis_can_signal | ods_csv_signal_data |
| DDL SQL | CAN 表结构 | CSV 表结构 |
| columns header | item_batch_id,item_dt,... | file_name,collect_time,... |
| label 前缀 | can | csv |
| 行数据字段 | item_batch_id, item_dt, item_channel, item_name, item_value | file_name, collect_time, platform_time, signal_name, signal_value |

### 方案

新增 `writer/stream_loader.py`，抽取通用基类：

**`BaseStarRocksConfig`** — 通用配置，TABLE 通过子类覆盖默认值

**`StreamLoader`** — 通用 Stream Load 实现：
- `_create_table()` → 接收 `ddl_sql` 参数
- `_send_stream_load()` → 接收 `columns` 参数
- `load_batch()` → 接收 `label_prefix` + `row_formatter` 回调

**`can_2_sr.py`** 保留：
- `StarRocksConfig(BaseStarRocksConfig)` — 仅覆盖 TABLE 默认值
- `StarRocksStreamLoader(StreamLoader)` — 注入 CAN 特有的 DDL、columns、label_prefix、row_formatter
- `StarRocksDataWriter` — 保留类名和接口，内部使用 StarRocksStreamLoader

**`csv_2_sr.py`** 同理。

### 额外清理

`StarRocksDataWriter.write_data()` 和 `CsvDataWriter.write_data()` 当前无调用方（parser 直接调 `writer.loader.load_batch()`），一并删除。

### 影响范围

- 新增 `writer/stream_loader.py`
- 修改 `can_2_sr.py`、`csv_2_sr.py` — 继承基类，删除重复代码
- 调用方（parser 层）无需改动，因为 `StarRocksDataWriter` / `CsvDataWriter` 类名和 `loader.load_batch()` 接口不变

## 7.4 清理 main.py 无用桩代码

### 现状

根目录 `main.py` 仅包含 Hello World 桩代码，实际入口为 `api_server.py`。

### 方案

直接删除 `/main.py`（注意：不是 `src/` 下的，是项目根目录的）。

### 影响范围

- 删除 `main.py`
- 无其他文件引用此文件

## 7.6 修复 parser 模块 sys.path hack

### 现状

`parsers/__init__.py` 通过 `sys.path.insert(0, ...)` 将 `src/` 加入 path，以便 `from writer.can_2_sr import ...`。

Python 只会把当前脚本所在目录加入 sys.path，所以 `api_server.py` 运行时 `src/can_parser_server/` 在路径里，但 `src/` 不在。sys.path.insert 的作用是把 `src/` 加进去，让 parser 能导入 writer。

### 方案

把路径设置从 `__init__.py`（隐式副作用）挪到 `api_server.py`（入口文件），这是设置路径的正确位置。

**`parsers/__init__.py`** — 删除 `import os`、`import sys`、`sys.path.insert(...)` 三行

**`api_server.py`** — 顶部加入 `sys.path.insert(0, str(BASE_DIR.parent))`，利用已有的 `BASE_DIR = Path(__file__).parent`（即 `src/can_parser_server/`），parent 就是 `src/`

parser 文件中的 `from writer.can_2_sr import ...` 无需改动，因为入口文件已把 `src/` 加入路径。

### 影响范围

- 修改 `parsers/__init__.py` — 删除 sys.path hack 行
- 修改 `api_server.py` — 入口处加 sys.path.insert
- parser 文件中的 import 语句无需修改

## 文件变更汇总

| 文件 | 操作 | 说明 |
|------|------|------|
| `parsers/can_parser.py` | 新增 | ASC/BLF 共用解码逻辑 |
| `writer/stream_loader.py` | 新增 | Stream Load 通用基类 |
| `parsers/asc_parser.py` | 修改 | 缩为薄壳，调 can_parser.decode_can |
| `parsers/blf_parser.py` | 修改 | 同上 |
| `parsers/__init__.py` | 修改 | 删除 sys.path hack |
| `writer/can_2_sr.py` | 修改 | 继承 stream_loader 基类 |
| `writer/csv_2_sr.py` | 修改 | 同上 |
| `main.py` | 删除 | 无用桩代码 |

## 向后兼容

- `decode_asc` / `decode_blf` / `decode_csv` 导出和函数签名不变
- `StarRocksDataWriter` / `CsvDataWriter` 类名和 `loader.load_batch()` 接口不变
- `api_server.py` 无需任何改动
- `csv_parser.py` 无需任何改动
