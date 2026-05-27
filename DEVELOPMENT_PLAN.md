# 开发计划（DEVELOPMENT_PLAN.md）

## 版本说明

本文档覆盖项目从初始开发到当前状态的完整路线。已完成 Phase 标记为 ✅，待实施 Phase 标记为 ⬜。

---

## Phase 1：基础框架搭建 ✅

| 编号 | 任务 | 产出物 | 验证方式 | 状态 |
|------|------|--------|----------|------|
| 1.1 | 项目初始化，建立目录结构 | `src/` 目录树 | `ls src/` 确认目录存在 | ✅ |
| 1.2 | 配置依赖管理 | `requirements.txt` | `pip install -r requirements.txt` 无报错 | ✅ |
| 1.3 | 配置 .gitignore | `.gitignore` | `git status` 不显示 venv/IDE 文件 | ✅ |

---

## Phase 2：StarRocks Writer 实现 ✅

| 编号 | 任务 | 产出物 | 验证方式 | 状态 |
|------|------|--------|----------|------|
| 2.1 | 实现 CAN 数据 Stream Load 写入器 | `writer/can_2_sr.py` | 调用 `write_data()` 写入测试数据，StarRocks 中可查询 | ✅ |
| 2.2 | 实现 CSV 数据 Stream Load 写入器 | `writer/csv_2_sr.py` | 调用 `write_data()` 写入测试数据，StarRocks 中可查询 | ✅ |
| 2.3 | 实现 DDL 自动建表 | `can_2_sr.py` / `csv_2_sr.py` 中的 `_create_table()` | 空库中首次写入自动建表成功 | ✅ |
| 2.4 | 实现重试机制（5 次退避） | `_send_stream_load()` 重试逻辑 | 模拟网络异常，确认重试生效 | ✅ |

---

## Phase 3：Parser 实现 ✅

| 编号 | 任务 | 产出物 | 验证方式 | 状态 |
|------|------|--------|----------|------|
| 3.1 | 实现 ASC 解析器 | `parsers/asc_parser.py` | 传入 .asc + .dbc 文件，输出解码后的信号记录 | ✅ |
| 3.2 | 实现 BLF 解析器 | `parsers/blf_parser.py` | 传入 .blf + .dbc 文件，输出解码后的信号记录 | ✅ |
| 3.3 | 实现 CSV/Excel 解析器 | `parsers/csv_parser.py` | 传入 .csv/.xlsx 文件，输出展开后的信号记录 | ✅ |
| 3.4 | 实现信号过滤功能 | asc_parser / blf_parser 中的 `signal_filter_list` 参数 | 传入过滤列表，仅返回指定信号 | ✅ |

---

## Phase 4：API 服务实现 ✅

| 编号 | 任务 | 产出物 | 验证方式 | 状态 |
|------|------|--------|----------|------|
| 4.1 | 实现 POST /api/v1/parse 端点 | `api_server.py` | `curl -F` 上传文件，返回 task_id | ✅ |
| 4.2 | 实现 GET /api/v1/tasks/{task_id} 端点 | `api_server.py` | 查询 task_id 返回状态和结果 | ✅ |
| 4.3 | 实现 GET /health 端点 | `api_server.py` | `curl /health` 返回 `{"status": "ok"}` | ✅ |
| 4.4 | 实现异步任务管理（线程池 + 状态追踪） | `api_server.py` 中的 `_task_store` + Semaphore | 提交多个任务，并发数不超过 4，状态正确流转 | ✅ |
| 4.5 | 实现参数校验和错误处理 | `api_server.py` | 无效参数返回 400，缺失文件返回 400 | ✅ |
| 4.6 | 编写 API 接口文档 | `CAN信号解析接口文档.md` | 文档覆盖所有端点、参数、响应格式 | ✅ |

---

## Phase 5：文档补齐 ✅

| 编号 | 任务 | 产出物 | 验证方式 | 状态 |
|------|------|--------|----------|------|
| 5.1 | 补写需求文档 | `REQUIREMENTS.md` | 覆盖全部已实现功能需求、验收标准、优先级、追溯矩阵 | ✅ |
| 5.2 | 补写技术设计文档 | `DESIGN.md` | 覆盖架构、接口、数据模型、模块设计 | ✅ |
| 5.3 | 补写开发计划文档 | `DEVELOPMENT_PLAN.md`（本文档） | 覆盖全部 Phase，每个任务可验证 | ✅ |
| 5.4 | 更新协作流程规范 | `人机协作开发流程规范.md` | Phase 1 产物改为 REQUIREMENTS.md，文档体系包含三层 | ✅ |

---

## Phase 6：分析场景模型（待开发）⬜

参考文档：`分析场景模型优化方案.md`

| 编号 | 任务 | 产出物 | 验证方式 | 状态 |
|------|------|--------|----------|------|
| 6.1 | 创建配置目录和模型配置文件（dbc_files 为数组） | `config/models_config.json` | JSON 格式合法，至少包含 1 个车型 + 1 个模型（关联多个 DBC 文件） | ⬜ |
| 6.2 | 创建 DBC 文件目录（按车型分子目录） | `dbc_files/{vehicle_model}/` | 目录存在，每个车型目录下至少 1 个 DBC 文件 | ⬜ |
| 6.3 | api_server.py 启动时加载模型配置 | `api_server.py` 新增 `load_models_config()` | 启动日志打印已加载的车型和模型列表 | ⬜ |
| 6.4 | POST /api/v1/parse 新增 vehicle_model + model_name 参数 | `api_server.py` | 传入 vehicle_model + model_name 后自动加载关联的一组 DBC 文件和 signal_filter_list，解析成功 | ⬜ |
| 6.5 | model_name 逻辑：从 dbc_files/{vehicle_model}/ 读取多个 DBC 文件 | `api_server.py` 中的解析线程逻辑 | 不传 dbc_file 参数，仅靠 vehicle_model + model_name 加载多个 DBC 完成 asc/blf 解析 | ⬜ |
| 6.6 | CSV 类型兼容 model_name | `api_server.py` | CSV + model_name 自动获取 signal_filter_list | ⬜ |
| 6.7 | 向后兼容：不传 model_name 走原有逻辑 | `api_server.py` | 原有调用方式不受影响，所有参数行为不变 | ⬜ |
| 6.8 | 新增 GET /api/v1/models 端点 | `api_server.py` | 返回所有车型及其模型概览 | ⬜ |
| 6.9 | 新增 GET /api/v1/models/{vehicle_model} 端点 | `api_server.py` | 返回某车型下所有模型的 dbc_files 列表和 signal_filter_list | ⬜ |
| 6.10 | 端到端验证 | — | 使用 vehicle_model + model_name 完整走通 asc/blf/csv 三种解析流程 | ⬜ |

---

## Phase 7：技术债清理（待排期）⬜

| 编号 | 任务 | 说明 | 状态 |
|------|------|------|------|
| 7.1 | 抽取 ASC/BLF 解析器共用基类 | asc_parser 和 blf_parser 仅 Reader 类型不同，其余逻辑完全一致 | ⬜ |
| 7.2 | 抽取 Writer 共用 Stream Load 组件 | can_2_sr 和 csv_2_sr 的 Stream Load + 重试逻辑几乎完全一致 | ⬜ |
| 7.3 | 补充单元测试 | parser 和 writer 缺少测试覆盖 | ⬜ |
| 7.4 | 清理 main.py 无用桩代码 | 实际入口为 api_server.py，main.py 无实际功能 | ⬜ |
| 7.5 | 任务持久化 | 当前任务存储在内存 dict 中，服务重启后历史丢失 | ⬜ |
| 7.6 | 修复 parser 模块中的 sys.path hack | 通过 sys.path.insert 导入 writer，应改为相对导入 | ⬜ |

---

## 当前进度总览

| Phase | 名称 | 状态 |
|-------|------|------|
| Phase 1 | 基础框架搭建 | ✅ 已完成 |
| Phase 2 | StarRocks Writer 实现 | ✅ 已完成 |
| Phase 3 | Parser 实现 | ✅ 已完成 |
| Phase 4 | API 服务实现 | ✅ 已完成 |
| Phase 5 | 文档补齐 | ✅ 已完成 |
| Phase 6 | 分析场景模型 | ⬜ 待开发 |
| Phase 7 | 技术债清理 | ⬜ 待排期 |

**下一优先事项：** Phase 6 — 分析场景模型功能开发（方案已评审通过）
