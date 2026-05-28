
## 项目背景

这是一个 CAN 总线信号解析与数据入库服务，未来将部署运行在linux服务器上，Python 3.12 + FastAPI。

**核心能力：** 接收车辆 CAN 日志文件（ASC/BLF/CSV），用 DBC 文件解码为结构化信号数据，写入 StarRocks 分析数据库。

**项目结构：**
- `src/can_parser_server/api_server.py` — FastAPI 入口，5 个端点
- `src/can_parser_server/parsers/` — asc_parser / blf_parser / csv_parser
- `src/writer/` — can_2_sr.py / csv_2_sr.py（StarRocks Stream Load 写入）
- `src/can_parser_server/config/models_config.json` — 车型→模型→DBC+信号列表配置
- `src/can_parser_server/dbc_files/{车型}/` — 本地 DBC 文件目录

**关键端点和接口文档：**
- POST /api/v1/parse — 提交解析任务（异步）
- GET /api/v1/tasks/{task_id} — 查询任务状态
- GET /api/v1/models — 列出车型及模型
- GET /api/v1/models/{vehicle_model} — 模型详情
- GET /health — 健康检查

**两种调用方式：**
- 传统模式：手动上传 dbc_file + signal_filter_list
- 模型模式：传 vehicle_model + model_name，自动查找 DBC 文件和信号列表

**外部依赖：**
- StarRocks（MySQL 协议 9030 + HTTP Stream Load 8010）
- python-can 库需要打补丁：`.venv/.../can/io/asc.py` 的 `_datetime_to_timestamp` 方法，`datetime_formats` 最前面加 `%H` + `%p` 两行格式，修复部分工具导出的 ASC 文件日期兼容问题。每次 pip install 后需重新打补丁。

**文档体系：**
- REQUIREMENTS.md — 需求基线
- DESIGN.md — 技术方案（架构、接口、数据模型）
- DEVELOPMENT_PLAN.md — 开发计划（Phase 1-6 已完成，Phase 7 待排期）
- DEPLOY.md — 部署文档
- CAN信号解析接口文档.md — API 接口文档
- 分析场景模型优化方案.md — 车型+模型方案设计
- 人机协作开发流程规范.md — 协作流程规范

**当前状态：** Phase 1-6 已完成并通过测试，代码在 main 分支。

---

## 安全规则

- 禁止读取任何 .env / credentials / secrets / keys 类型的文件
- 禁止读取文件名包含 password、token、secret、api_key、private_key 的文件
- 读取配置文件（如 config.yaml、settings.json）前，先确认其不包含敏感信息
- 如需使用密钥或凭证，提示用户通过环境变量方式注入，不要写入代码或文档
- 提交代码前确认暂存区不包含敏感文件

---

## 沟通

- 始终使用中文回复
- 说话接地气，像朋友聊天一样，不要 AI 腔
- 改动完成后用 1-2 句话总结变更内容，简短即可
- 每次对话结束，显性告诉用户：”搞定了，还有事没？”

## Git 规则

- 只在明确说"提交""commit""推送"时才操作 git，不要主动提交
- 当我说"你懂的"，意味着：把本次新增/修改的内容提交并推送到远端 git
- commit message 使用中文，格式：`模块: 简述做了什么`

## 编码规则

- 优先编辑已有文件，避免不必要的创建新文件
- 不要主动创建文档（README、设计文档等），除非明确要求
- 代码不加注释，除非 WHY 非显而易见

