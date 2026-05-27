# CAN 信号解析接口文档

## 服务信息

- 服务名：CAN Data Parser Service
- 版本：2.1.0
- 启动端口：8000
- 支持格式：ASC / BLF / CSV
- 并发上限：最多 **4 个**任务同时解析，超出限制的任务排队等待（状态为 `pending`）

---

## 1. 提交解析任务

**POST** `/api/v1/parse`

Content-Type: `multipart/form-data`

### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| parser_type | string | 是 | 解析类型：`asc` / `blf` / `csv` |
| batch_id | string | 是 | 批次标识，用于 StarRocks 数据分组 |
| data_file | file | 是 | 数据文件（.asc / .blf / .csv / .xlsx） |
| dbc_file | file | 否 | DBC 描述文件，传统模式下 asc/blf 必传；使用 vehicle_model + model_name 时可选 |
| batch_size | int | 否 | 每批写入条数，默认 500000 |
| signal_filter_list | string | 否 | JSON 数组，如 `["VehicleSpeed"]`，仅传统模式 asc/blf 使用 |
| vehicle_model | string | 否 | 车型（如 `C01`、`C11`），配合 `model_name` 使用 |
| model_name | string | 否 | 分析场景模型名称，配合 `vehicle_model` 使用 |

### 两种调用方式

**方式一：传统模式（向后兼容）**

不传 `vehicle_model` / `model_name`，手动上传 DBC 文件和信号过滤列表：

```bash
curl -X POST http://localhost:8000/api/v1/parse \
  -F "parser_type=asc" \
  -F "batch_id=batch001" \
  -F "data_file=@data.asc" \
  -F "dbc_file=@vehicle.dbc" \
  -F 'signal_filter_list=["VehicleSpeed","SteeringAngle"]'
```

**方式二：分析场景模型（推荐）**

传入 `vehicle_model` + `model_name`，系统自动查找对应的 DBC 文件和信号过滤列表，无需手动上传：

```bash
curl -X POST http://localhost:8000/api/v1/parse \
  -F "parser_type=asc" \
  -F "batch_id=batch001" \
  -F "data_file=@data.asc" \
  -F "vehicle_model=C01" \
  -F "model_name=chassis_analysis"
```

**逻辑优先级：**
- 传入 `vehicle_model` + `model_name` → 从配置文件自动获取 `dbc_files` 和 `signal_filter_list`，忽略上传的 `dbc_file`
- 未传入 `model_name` → 走传统模式，手动上传 `dbc_file` + 可选的 `signal_filter_list`
- CSV 类型不需要 DBC 文件，`model_name` 仅用于获取 `signal_filter_list`

### 响应示例

```json
{
  "task_id": "a1b2c3d4",
  "parser_type": "asc",
  "status": "accepted"
}
```

任务为**异步执行**，返回 `task_id` 后可通过查询接口获取进度和结果。

---

## 2. 查询任务状态

**GET** `/api/v1/tasks/{task_id}`

### 路径参数

| 参数 | 说明 |
|------|------|
| task_id | 提交解析任务时返回的任务 ID |

### 响应示例

```json
{
  "task_id": "a1b2c3d4",
  "batch_id": "batch001",
  "parser_type": "asc",
  "status": "success",
  "created_at": "2025-01-15 10:30:00",
  "completed_at": "2025-01-15 10:35:20",
  "result": {
    "total_written": 123456
  }
}
```

### 状态说明

| status | 说明 |
|--------|------|
| pending | 等待中，达到 4 个并发上限后新任务排队 |
| running | 解析中 |
| success | 完成，`result.total_written` 为写入条数 |
| failed | 失败，`result.error` 为错误信息 |

---

## 3. 查询分析场景模型

### 3.1 列出所有车型及模型

**GET** `/api/v1/models`

```json
{
  "C01": {
    "description": "C01 车型",
    "models": {
      "chassis_analysis": "底盘分析场景",
      "body_electronics": "车身电子分析场景"
    }
  },
  "C11": {
    "description": "C11 车型",
    "models": {
      "chassis_analysis": "底盘分析场景"
    }
  }
}
```

### 3.2 查看某车型下模型详情

**GET** `/api/v1/models/{vehicle_model}`

```json
{
  "vehicle_model": "C01",
  "description": "C01 车型",
  "models": {
    "chassis_analysis": {
      "description": "底盘分析场景",
      "dbc_files": ["vehicle_chassis.dbc", "vehicle_powertrain.dbc"],
      "signal_filter_list": ["VehicleSpeed", "SteeringAngle", "BrakePressure", "MotorTorque"]
    },
    "body_electronics": {
      "description": "车身电子分析场景",
      "dbc_files": ["vehicle_body.dbc"],
      "signal_filter_list": ["DoorStatus", "WindowPosition", "LightStatus"]
    }
  }
}
```

---

## 4. 健康检查

**GET** `/health`

```json
{
  "status": "ok",
  "supported_types": ["asc", "blf", "csv"]
}
```
