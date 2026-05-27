# 部署文档

## 1. 环境要求

| 项目 | 版本/说明 |
|------|----------|
| Python | 3.12+ |
| StarRocks | 需开通 MySQL 协议（9030）和 HTTP Stream Load（8010）端口 |
| 操作系统 | macOS / Linux |

## 2. 安装步骤

### 2.1 克隆代码

```bash
git clone <仓库地址>
cd can_tools
```

### 2.2 创建虚拟环境

```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

### 2.3 安装依赖

```bash
pip install -r requirements.txt
```

### 2.4 打 python-can 补丁（必须）

项目依赖的 `python-can` 库对部分 CAN 工具导出的 ASC 文件日期格式不兼容，需要手动打补丁修复。

**补丁文件：** `.venv/lib/python3.12/site-packages/can/io/asc.py`

**补丁内容：** 在 `_datetime_to_timestamp` 方法的 `datetime_formats` 元组最前面新增两行格式（约第 141 行），支持 24 小时制 + AM/PM 的日期格式（如 `16:20:00.965 PM`）：

```python
datetime_formats = (
    "%m %d %H:%M:%S.%f %p %Y",   # 新增：24小时制 + AM/PM + 毫秒
    "%m %d %H:%M:%S %p %Y",      # 新增：24小时制 + AM/PM
    "%m %d %I:%M:%S.%f %p %Y",
    "%m %d %I:%M:%S %p %Y",
    "%m %d %H:%M:%S.%f %Y",
    "%m %d %H:%M:%S %Y",
)
```

> **说明：** 部分工具导出的 ASC 文件日期行格式为 `date Tue Feb 21 16:20:00.965 PM 2026`（24 小时制同时带 PM 标识），python-can 原生不支持此格式。每次 `pip install` 重新安装 python-can 后都需要重新打补丁。

### 2.5 配置 StarRocks 连接

设置以下环境变量：

```bash
export SR_HOST="your-starrocks-host"
export SR_FE="your-starrocks-fe:8010"        # FE HTTP 地址
export SR_QUERY_PORT="9030"
export SR_STREAM_HTTP_PORT="8010"
export SR_USER="your-username"
export SR_PASSWORD="your-password"
export SR_DATABASE="your-database"
```

可选覆盖默认表名：

```bash
export SR_CAN_TABLE="ods_mkt_analysis_can_signal"    # CAN 信号目标表（默认值）
export SR_CSV_TABLE="ods_csv_signal_data"             # CSV 信号目标表（默认值）
export SR_STREAM_BATCH_SIZE="300000"                   # 每批写入条数（默认值）
```

### 2.6 配置分析场景模型

编辑 `src/can_parser_server/config/models_config.json`，按车型 → 模型 → DBC 文件 + 信号过滤列表的结构定义：

```json
{
  "vehicles": {
    "C01": {
      "description": "C01 车型",
      "models": {
        "chassis_analysis": {
          "dbc_files": ["vehicle_chassis.dbc", "vehicle_powertrain.dbc"],
          "signal_filter_list": ["VehicleSpeed", "SteeringAngle", "BrakePressure"],
          "description": "底盘分析场景"
        }
      }
    }
  }
}
```

将对应的 DBC 文件放入 `src/can_parser_server/dbc_files/{vehicle_model}/` 目录下。

### 2.7 启动服务

```bash
cd src/can_parser_server
uvicorn api_server:app --host 0.0.0.0 --port 8000 --reload
```

启动日志中会打印已加载的车型和模型：

```
[INFO] 已加载模型配置，车型数: 2
  - C01: ['chassis_analysis', 'body_electronics']
  - C11: ['chassis_analysis']
```

### 2.8 验证

```bash
# 健康检查
curl http://localhost:8000/health

# 查询可用模型
curl http://localhost:8000/api/v1/models

# 提交解析任务（传统模式）
curl -X POST http://localhost:8000/api/v1/parse \
  -F "parser_type=asc" \
  -F "batch_id=batch001" \
  -F "data_file=@data.asc" \
  -F "dbc_file=@vehicle.dbc"

# 提交解析任务（模型模式）
curl -X POST http://localhost:8000/api/v1/parse \
  -F "parser_type=asc" \
  -F "batch_id=batch001" \
  -F "data_file=@data.asc" \
  -F "vehicle_model=C01" \
  -F "model_name=chassis_analysis"

# 查询任务状态
curl http://localhost:8000/api/v1/tasks/{task_id}
```

## 3. 项目结构

```
can_tools/
├── requirements.txt
├── .gitignore
├── src/
│   ├── can_parser_server/
│   │   ├── api_server.py              # FastAPI 服务入口
│   │   ├── config/
│   │   │   └── models_config.json     # 车型→模型→DBC+信号列表配置
│   │   ├── dbc_files/                 # 本地 DBC 文件（按车型分子目录）
│   │   │   ├── C01/
│   │   │   │   └── .gitkeep
│   │   │   └── C11/
│   │   │       └── .gitkeep
│   │   └── parsers/
│   │       ├── __init__.py
│   │       ├── asc_parser.py          # ASC 格式解析
│   │       ├── blf_parser.py          # BLF 格式解析
│   │       └── csv_parser.py          # CSV/Excel 解析
│   └── writer/
│       ├── can_2_sr.py                # CAN 数据 → StarRocks
│       └── csv_2_sr.py                # CSV 数据 → StarRocks
└── 文档/
    ├── REQUIREMENTS.md                # 需求文档
    ├── DESIGN.md                      # 技术设计文档
    ├── DEVELOPMENT_PLAN.md            # 开发计划
    ├── DEPLOY.md                      # 本文档
    ├── CAN信号解析接口文档.md           # API 接口文档
    ├── 分析场景模型优化方案.md           # 分析场景模型设计
    └── 人机协作开发流程规范.md           # 协作流程规范
```

## 4. 关键注意事项

| 事项 | 说明 |
|------|------|
| **python-can 补丁** | 每次 `pip install` 后必须重新打补丁，否则部分 ASC 文件解析会报 `Incompatible datetime string` 错误 |
| **DBC 文件编码** | 解析器使用 `gb2312` 编码加载 DBC 文件（支持中文信号名），DBC 文件需确保为 gb2312 或兼容编码 |
| **DBC 文件 .gitignore** | `dbc_files/` 下的 DBC 文件已配置 .gitignore，不会被 git 跟踪。部署时需手动将 DBC 文件放入对应车型目录 |
| **StarRocks 表自动创建** | 首次写入时 Writer 会自动建表，无需手动 DDL。建表 SQL 分别在 `writer/can_2_sr.py` 和 `writer/csv_2_sr.py` 的 `_create_table()` 方法中 |
| **临时文件清理** | 上传的文件保存在 `./temp_uploads/` 目录，任务完成后自动清理 |
| **并发限制** | 最多 4 个任务同时解析，Semaphore 控制。如需调整，修改 `api_server.py` 中 `_semaphore = threading.Semaphore(4)` 的值 |
