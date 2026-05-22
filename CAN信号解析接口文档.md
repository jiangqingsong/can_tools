# CAN 信号解析接口文档

## 服务信息

- 服务名：CAN Data Parser Service
- 版本：2.0.0
- 启动端口：8000
- 支持格式：ASC / BLF / CSV
- 并发上限：最多 **4 个**任务同时解析，超出限制的任务排队等待（状态为 `pending`）

---

## 1. 提交解析任务

**POST** `/api/v1/parse`

Content-Type: `multipart/form-data`

### 请求参数

| 参数 | 类型 | 必填 | 说明                                              |
|------|------|------|-------------------------------------------------|
| parser_type | string | 是 | 解析类型：`asc` / `blf` / `csv`                      |
| batch_id | string | 是 | 批次标识，直接用作写入的表名/文件名                              |
| data_file | file | 是 | 数据文件（.asc / .blf / .csv / .xlsx）                |
| dbc_file | file | 否 | DBC 描述文件，仅针对ASC/BLF解析，csv 类型不需要                 |
| batch_size | int | 否 | 每批写入条数，默认 500000                                |
| signal_filter_list | string | 否 | JSON 数组，如 `["VehicleSpeed"]`，仅针对ASC/BLF解析过滤指定信号 |

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

## 3. 健康检查

**GET** `/health`

```json
{
  "status": "ok",
  "supported_types": ["asc", "blf", "csv"]
}
```
