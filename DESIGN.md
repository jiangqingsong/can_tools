# 技术设计文档（DESIGN.md）

## 1. 项目概述

**项目名称：** CAN Tools — CAN 总线信号解析与数据入库服务

**项目目标：** 将车辆 CAN 总线日志文件（ASC、BLF、CSV/Excel）解码为结构化信号数据，写入 StarRocks 分析数据库，供下游数据分析使用。

**技术栈：** Python 3.12 / FastAPI / cantools / python-can / pandas / StarRocks

---

## 2. 系统架构

```
┌──────────────────────────────────────────────────┐
│                    客户端                         │
│         HTTP multipart/form-data 上传             │
└──────────────────────┬───────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────┐
│              API Layer (FastAPI)                  │
│  api_server.py                                   │
│  - 接收文件上传，参数校验                           │
│  - 异步任务管理（Semaphore 并发控制）                │
│  - 3 个端点：POST /parse, GET /tasks/{id},        │
│    GET /health                                    │
└──────────────────────┬───────────────────────────┘
                       │ (后台 daemon 线程)
                       ▼
┌──────────────────────────────────────────────────┐
│              Parser Layer                         │
│  parsers/                                        │
│  ├── asc_parser.py   ASC 格式解析 (cantools)       │
│  ├── blf_parser.py   BLF 格式解析 (cantools)       │
│  └── csv_parser.py   CSV/Excel 解析 (pandas)      │
│  - 解码 CAN 报文 / 提取信号列                      │
│  - 批量写入 Writer                                │
└──────────────────────┬───────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────┐
│              Writer Layer                         │
│  writer/                                         │
│  ├── can_2_sr.py    CAN 数据 → StarRocks          │
│  └── csv_2_sr.py    CSV 数据 → StarRocks          │
│  - HTTP Stream Load 批量写入                       │
│  - 自动建表（DDL via pymysql）                     │
│  - 重试机制（最多 5 次，退避延迟）                    │
└──────────────────────┬───────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────┐
│           StarRocks (OLAP Database)               │
│  - ods_mkt_analysis_can_signal (CAN 信号)         │
│  - ods_csv_signal_data (CSV 信号)                 │
│  - 协议：MySQL (DDL) + HTTP Stream Load (写入)     │
└──────────────────────────────────────────────────┘
```

**分层职责：**
- **API Layer：** 对外暴露 HTTP 接口，负责请求校验、任务调度、状态追踪
- **Parser Layer：** 专注数据解码逻辑，不感知 HTTP 和存储细节
- **Writer Layer：** 专注 StarRocks 写入，封装连接、建表、重试逻辑

---

## 3. API 设计

### 3.1 POST /api/v1/parse — 提交解析任务

**请求：** `multipart/form-data`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| parser_type | string | 是 | `asc` / `blf` / `csv` |
| batch_id | string | 是 | 批次标识，用于 StarRocks 数据分组 |
| data_file | file | 是 | 数据文件 (.asc / .blf / .csv / .xlsx) |
| dbc_file | file | 否 | DBC 描述文件，asc/blf 必传，csv 不需要 |
| batch_size | int | 否 | 每批写入条数，默认 500000 |
| signal_filter_list | string | 否 | JSON 数组，如 `["VehicleSpeed"]`，仅 asc/blf |

**响应 (200)：**
```json
{
  "task_id": "a1b2c3d4",
  "parser_type": "asc",
  "status": "accepted"
}
```

**错误响应 (400)：** parser_type 无效、必传文件缺失、signal_filter_list JSON 格式错误

### 3.2 GET /api/v1/tasks/{task_id} — 查询任务状态

**响应 (200)：**
```json
{
  "task_id": "a1b2c3d4",
  "batch_id": "batch001",
  "parser_type": "asc",
  "status": "pending|running|success|failed",
  "created_at": "2025-01-15 10:30:00",
  "completed_at": "2025-01-15 10:35:20",
  "result": { "total_written": 123456 }
}
```

**状态机：** `pending → running → success | failed`

**错误响应 (404)：** task_id 不存在

### 3.3 GET /health — 健康检查

```json
{ "status": "ok", "supported_types": ["asc", "blf", "csv"] }
```

---

## 4. 数据模型

### 4.1 StarRocks 表结构

**CAN 信号表 `ods_mkt_analysis_can_signal`：**

| 字段 | 类型 | 说明 |
|------|------|------|
| item_batch_id | VARCHAR(100) | 批次标识 |
| item_dt | DECIMAL(20, 6) | CAN 消息时间戳 |
| item_channel | VARCHAR(50) | CAN 通道 |
| item_name | VARCHAR(200) | 信号名称 |
| item_value | DOUBLE | 信号值 |
| insert_time | DATETIME | 写入时间（默认 CURRENT_TIMESTAMP） |

- 模型：DUPLICATE KEY (item_batch_id, item_dt, item_channel, item_name)
- 分桶：HASH(item_batch_id) BUCKETS 2，3 副本

**CSV 信号表 `ods_csv_signal_data`：**

| 字段 | 类型 | 说明 |
|------|------|------|
| file_name | VARCHAR(200) | 文件名 |
| collect_time | DATETIME | 采集时间 |
| platform_time | DATETIME | 平台接收时间 |
| signal_name | VARCHAR(200) | 信号名称 |
| signal_value | DOUBLE | 信号值 |
| insert_time | DATETIME | 写入时间（默认 CURRENT_TIMESTAMP） |

- 模型：DUPLICATE KEY (file_name, collect_time, signal_name)
- 分桶：HASH(file_name) BUCKETS 1，3 副本

### 4.2 内存任务模型

```python
_task_store: Dict[str, dict] = {
    "task_id": {
        "task_id": str,
        "batch_id": str,
        "parser_type": str,
        "status": "pending|running|success|failed",
        "created_at": str,
        "completed_at": str | None,
        "result": dict | None,
        "thread": Thread | None
    }
}
```

**线程安全：** `_threading.Lock()` 保护 `_task_store` 读写

---

## 5. 模块设计

### 5.1 api_server.py

- **职责：** HTTP 接口、参数校验、任务生命周期管理、并发控制
- **并发策略：** `threading.Semaphore(4)` 限制同时解析的任务数
- **文件管理：** 上传文件保存到 `./temp_uploads/{uuid}_{filename}`，任务完成后清理
- **配置：** 通过环境变量获取 StarRocks 连接信息

### 5.2 asc_parser.py

- **接口：** `decode(batch_id, data_file, dbc_file, batch_size=5000, signal_filter_list=None) -> int`
- **流程：** 加载 DBC → 读取 ASC → 逐帧解码 → 可选信号过滤 → 批量写入 StarRocks
- **DBC 编码：** 使用 `gb2312` 编码加载（支持中文信号名）
- **未解码 ID 追踪：** 记录所有未能通过 DBC 解码的 CAN ID

### 5.3 blf_parser.py

- **接口：** 同 asc_parser
- **差异点：** 使用 `can.BLFReader` 替代 `can.ASCReader`，其余逻辑完全一致

### 5.4 csv_parser.py

- **接口：** `decode(batch_id, data_file, batch_size=5000) -> int`
- **流程：** pandas 读取 CSV/Excel → 逐行展开信号列 → 批量写入 StarRocks
- **编码兼容：** 依次尝试 utf-8、gbk、gb2312、gb18030、latin-1
- **信号名处理：** 去除列名中括号内容 `col_name.split("(")[0]`
- **无 DBC 依赖：** CSV 列名即信号名

### 5.5 can_2_sr.py

- **StarRocksConfig：** 从环境变量读取连接配置
- **StarRocksStreamLoader：** HTTP Stream Load 底层实现
  - `_create_table()` — DDL 建表（pymysql）
  - `_send_stream_load()` — 发送 CSV 数据（HTTP PUT，`\x01` 分隔）
  - `load_batch()` — 格式化批次数据并发送，含 5 次重试
- **StarRocksDataWriter：** 对外入口，`write_data()` 建表 + 分批写入
- **重试策略：** 延迟 [5s, 10s, 30s, 60s]，最多 5 次
- **Stream Load 参数：** timeout=600s, max_filter_ratio=1.0, 307 重定向最多 5 跳

### 5.6 csv_2_sr.py

- 与 can_2_sr.py 结构相同，差异点：表名、表结构、分桶策略
- **CsvStarRocksConfig：** 额外使用 `SR_CSV_TABLE` 环境变量

---

## 6. 数据流

### 6.1 ASC/BLF 数据流

```
ASC/BLF 文件 + DBC 文件
  → cantools 加载 DBC 数据库
  → python-can 逐帧读取 CAN 消息
  → cantools 解码每帧信号 (arbitration_id + payload → signal_name + value)
  → 可选 signal_filter_list 过滤
  → 组装为 [{item_batch_id, item_dt, item_channel, item_name, item_value}]
  → \x01 分隔的 CSV 文本行
  → HTTP PUT → StarRocks Stream Load
```

### 6.2 CSV/Excel 数据流

```
CSV/Excel 文件
  → pandas 读取为 DataFrame
  → 逐行遍历，每个信号列展开为一条记录
  → 组装为 [{file_name, collect_time, platform_time, signal_name, signal_value}]
  → \x01 分隔的 CSV 文本行
  → HTTP PUT → StarRocks Stream Load
```

---

## 7. 配置管理

所有运行环境配置通过环境变量注入：

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| SR_HOST | "" | StarRocks 主机 |
| SR_FE | "" | StarRocks FE 地址（HTTP） |
| SR_QUERY_PORT | 9030 | MySQL 协议端口 |
| SR_STREAM_HTTP_PORT | 8010 | Stream Load HTTP 端口 |
| SR_USER | "" | 用户名 |
| SR_PASSWORD | "" | 密码 |
| SR_DATABASE | "" | 数据库名 |
| SR_CAN_TABLE | ods_mkt_analysis_can_signal | CAN 信号目标表 |
| SR_CSV_TABLE | ods_csv_signal_data | CSV 信号目标表 |
| SR_STREAM_BATCH_SIZE | 300000 | 每批写入条数 |

**安全策略：** 凭据仅通过环境变量注入，不写入代码或配置文件，不打印日志。

---

## 8. 异常处理

| 场景 | 处理方式 |
|------|----------|
| 无效 parser_type | 返回 400 |
| 必传文件缺失 | 返回 400 |
| DBC 文件编码问题 | 尝试 gb2312 编码，失败则抛异常（任务标记 failed） |
| CSV 编码问题 | 依次尝试 utf-8/gbk/gb2312/gb18030/latin-1 |
| StarRocks 连接失败 | 重试 5 次（退避延迟 5/10/30/60s），最终失败则任务标记 failed |
| 部分行写入失败 | max_filter_ratio=1.0，容忍错误行 |
| 未解码 CAN ID | 记录日志，不阻塞流程 |

---

## 9. 已知技术债

1. **asc_parser 与 blf_parser 代码高度重复** — 仅 Reader 类型不同，应抽取共用基类
2. **can_2_sr 与 csv_2_sr 代码高度重复** — Stream Load 逻辑可抽取共用组件
3. **无单元测试** — 缺少对 parser 和 writer 的自动化测试覆盖
4. **任务存储为内存 dict** — 服务重启后任务历史丢失
5. **main.py 为无用桩代码** — 实际入口是 api_server.py
6. **DBC 文件每次请求上传** — 应支持本地 DBC 文件管理（见待开发功能）

---

## 10. 待开发功能（分析场景模型）

详见 `分析场景模型优化方案.md`，核心改造点：

- 新增 `config/models_config.json` — 预定义车型 → 模型 → DBC 文件列表 + 信号列表的二级映射
- 新增 `dbc_files/` 目录 — 按车型组织本地 DBC 文件
- `POST /api/v1/parse` 新增 `vehicle_model` + `model_name` 可选参数 — 传入后自动加载该模型关联的一组 DBC 文件，无需上传
- 新增 `GET /api/v1/models` — 列出所有车型及可用模型
- 新增 `GET /api/v1/models/{vehicle_model}` — 查看某车型下的模型列表
- **向后兼容：** 不传 model_name 走原有逻辑

---

## 11. 项目文件结构

```
can_tools/
├── requirements.txt
├── .gitignore
├── src/
│   ├── can_parser_server/
│   │   ├── api_server.py          # FastAPI 服务入口
│   │   └── parsers/
│   │       ├── __init__.py         # 解析器导出
│   │       ├── asc_parser.py       # ASC 格式解析
│   │       ├── blf_parser.py       # BLF 格式解析
│   │       └── csv_parser.py       # CSV/Excel 解析
│   └── writer/
│       ├── can_2_sr.py             # CAN 数据 → StarRocks
│       └── csv_2_sr.py             # CSV 数据 → StarRocks
└── 文档/
    ├── REQUIREMENTS.md              # 需求基线（功能需求、验收标准）
    ├── DESIGN.md                    # 本文档（技术方案）
    ├── DEVELOPMENT_PLAN.md          # 开发计划
    ├── CAN信号解析接口文档.md         # API 接口文档
    ├── 分析场景模型优化方案.md         # 待开发功能设计
    └── 人机协作开发流程规范.md         # 协作流程规范
```
