# QueryForge AI 记忆文档

> 给后续 AI 开发者/维护者的项目速查手册。改动前先读本文，避免踩已知的坑。
> 最后更新：2026-08-28（分支 `master`，架构已扁平化重构）

## 1. 项目是什么

QueryForge = **自然语言 → SQL** 的智能数据查询平台（内部系统）。
FastAPI + SQLAlchemy 2.0 + SQLite（双库，WAL）+ sentence-transformers（BGE-M3 向量检索）。

- 面向用户：`/`（首页，SQL 对话工作台）；管理员后台：`/admin`（index.html，左侧菜单驱动）
- 端口：8888（`app/config.py` 的 `PORT`）；**不使用 Docker**，本地 venv 部署（`start_server.bat`）

## 2. 如何运行 / 验证

```bash
# 启动（日志统一进 logs/，app/llm/audit/server.log 自动轮转）
start_server.bat            # 或 .venv\Scripts\python.exe main.py
```
- **必须用项目 venv**（`.venv\Scripts\python.exe`）。系统 Python 缺 slowapi 等依赖，且 SQLAlchemy 版本可能不兼容。
- Python 改动需重启服务（reload 默认关闭）；静态文件（static/）改完即生效。
- 默认管理员：admin / REDACTED；`ALLOW_REGISTER` 默认开启，企业内部建议关闭（管理员建账号）。
- 冒烟：`GET /api/system/site-branding`（公开）、admin 登录后 `GET /api/user/list`、`GET /api/driver/list`。

## 3. 数据库布局（双库，SQLite WAL）

| 库 | 内容 | 关键表 |
|---|---|---|
| `db/queryforge.db`（主库，FK 约束**开启**） | 用户/配置/Schema/知识/对话/统计/设置 | users, roles, user_roles, role_permissions, db_schemas→db_tables→db_columns, db_table_relations, data_sources→sync_job_configs→sync_run_logs→schema_change_logs, system_settings, llm_configs, conversations, conversation_messages, knowledge_items, query_audit_logs, llm_usage_stats, vector_index_meta |
| `db/llm_telemetry.db`（遥测库） | LLM 调用明细 | llm_calls, llm_prompts |

- 四层结构：**数据源(data_sources) → 库(db_schemas.datasource_id) → 表 → 字段**。
  手动导入的库 datasource_id 为空（前端归入「未关联数据源」）；同步自动关联。
- 权限模型（角色化）：users → user_roles → roles → role_permissions（resource_type: route/page/schema/table/column/datasource/knowledge/row/metric）。
- 新增列/索引用 `db/sqlite_hooks.py` 的 `_ensure_column_sqlite` / `_ensure_indexes_sqlite` 加迁移（create_all 不改已有表）。
- **外键约束开启**：删除父表数据必须按依赖顺序清子表，否则 IntegrityError→500（历史教训：delete_datasource / delete_job / delete_user 都已做级联清理）。
- **数据保留策略**（scheduler 每日执行）：
  - 遥测库 llm_calls/llm_prompts：保留 90 天（03:00）
  - 主库 query_audit_logs / sync_run_logs / schema_change_logs：保留 90 天（03:30）
  - conversation_messages.result_data（查询结果 JSON）：保留 30 天自动清空（04:00 前后）
  - SQLite WAL checkpoint：每日 04:00 回收 WAL 体积

## 4. 目录速览

- `main.py`：应用入口（路由注册 + 中间件 + 调度器 + 向量预热后台线程 + uvicorn 日志轮转）
- `app/`：routers/（14 个路由模块）、auth.py（JWT+HttpOnly cookie，CurrentUser/AdminUser 依赖）、permissions.py（四层权限 + TTL 缓存）、middleware.py（安全响应头/访问日志/页面守卫/CORS）、logger.py（app/llm/audit/server 四日志）、crypto.py（Fernet 加解密）、config.py（全部配置唯一初始值）
- `core/`：**扁平化**（无子目录）——gen_chat.py（ChatSession）、gen_sql.py、gen_audit.py、llm_client.py、ret_retriever.py、ret_keywords.py、ret_vector_store.py、ret_index_meta.py
- `crud/`：数据访问层（base 泛型 CRUD + 按模块）
- `services/`：schema_service.py、schema_parsers.py、sql_executor.py、sql_gateway.py、sync_engine.py、sync_connectors.py、sync_diff.py、sync_classify.py、telemetry.py、vector_service.py
- `models/`：SQLAlchemy 模型（base.py 双基类 MainBase/TelemetryBase + 各表）
- `db/`：engine.py（方言自适应）、database.py（初始化编排）、sqlite_hooks.py（PRAGMA + 迁移）、seed.py
- `scheduler/`：scheduler.py + jobs/（usage_stats / retention / schema_sync）
- `static/`：纯 HTML+JS（Bootstrap5），`app_common.js`（公共 apiRequest/e()/QF 框架/分页组件），CSS/JS 已按页抽离（css/<page>.css + js/<page>.js）
- `docs/`：本文 + SYSTEM_DESCRIPTION.md + chatsql_flow.md + VECTOR_INDEX.md + 系统诊断与优化报告.md
- `logs/`：app/llm/audit/server 日志（RotatingFileHandler 10MB × 5 份；server 按天轮转保留 30 天）

## 5. 关键约定（改动前必读）

- **认证**：token 为 **HttpOnly cookie**，前端 JS 读不到 → 取用户一律走 `GET /api/user/profile`；前端解码 JWT 的做法是错的（曾导致菜单不显示 bug）。
- **权限**：接口层 `user: AdminUser`（自动 401/403）；页面层 page_auth_guard（system/ 模板仅 admin）+ 前端 `data-admin-only` 属性（app_common.js 对非 admin 移除）。
- **权限缓存**：`app/permissions.py` 有进程级 TTL 缓存（5s），改角色/权限后调 `invalidate_permission_cache()` 立即失效（`crud/role.py` 已接入）。
- **敏感等级**：DB 存英文（public/internal/sensitive/confidential），前端显示中文（`QF.levelLabel`）；徽标 CSS 类 `badge.bg-*` 必须带底色（`common.css`），否则白字不可见（历史 bug）。
- **数据库类型必填**：所有结构导入（CSV/JSON/上传）必须带 `db_type`（后端校验）。
- **导入格式**：仅规范 CSV（表头中文别名兼容：库名/表名/字段名/…）与 JSON（Spider/自定义）；DDL 解析已移除。
- **apiRequest**：FormData 上传时不要强制 `Content-Type: application/json`（app_common.js 已处理）；401 统一跳 /login。
- **分页**：列表接口统一 `{items, total}` 返回 + `limit/offset` 参数；前端可配 `QF.renderPager` 或"加载更多"。
- **SQL 执行器**：`services/sql_executor.py` 按数据源 id 缓存引擎（连接指纹变化自动重建），不要每次 create_engine + dispose。
- **日志**：统一写 `logs/`；SQL 生成链路追踪写入 DB（QueryAuditLog.pipeline_log），不再输出 pipeline.log 文件。
- **服务进程**：以后台任务托管时可能因端口被占/日志文件锁失败；正规做法是用户自己的实例或 `start_server.bat`。
- **前端分页**：对话列表接口 `GET /api/conversation` 已分页（默认 20/页），响应结构为 `{items, total}`。

## 6. 近期大改动（2026-08）

1. 权限模型重构：角色化 RBAC（role_permissions 多资源类型），权限管理页按 数据源→库→表→字段→知识 分层配置
2. 用户管理模块：管理员 CRUD + 级联清理；注册开关 ALLOW_REGISTER 可配
3. 驱动管理：驱动目录 + 一键 pip 安装（`/api/driver/*`）
4. Schema 重构：三层模型（db_schemas→db_tables→db_columns）替代旧"一行一字段"；数据源四层关联
5. 对话全库模式：创建对话无需选库，schema_name=None 按权限自动决定数据范围；跨库召回/执行
6. 日志系统瘦身：移除 pipeline_logger / sqlalchemy_logger（pipeline 链路已入库）
7. 系统优化（2026-08-28）：主库保留策略 + WAL checkpoint + 补索引 + 权限 TTL 缓存 + 知识召回 SQL 下推 + SQL 引擎复用 + 对话分页 + usage_stats 范围比较
8. 移除：结构维护页、DDL 方言解析器（git 历史可找回）、Docker 文件、旧架构遗留 db 文件、chat_to_sql_router / gen_pipeline（已合并进 conversation_router → ChatSession 单链路）

## 7. 已知坑 / 提醒

- 手动用数据库工具删表 = 灾难（ORM 映射坏、重启重建空表）。删数据走界面。
- 删除由数据源同步维护的库前，先停用/删除对应同步任务（调度器每 10 分钟自动同步，删了会回来）。
- 服务器日志文件锁：后台任务 `*> file` 重定向可能因文件被占用失败并连带杀进程；用唯一文件名或交给 start_server.bat。
- `db/`、`logs/`、`.venv`、`.workbuddy` 在 .gitignore，勿提交。
- `conversation_messages` 外键引用 `knowledge_items` 等表：测试脚本直接 import 部分模型会报 NoReferencedTableError，需先注册全部模型（`from models import ...` 全量导入）再操作。
- 权限相关 SQL（get_visible_schema_ids 等）有 5s TTL 缓存：排查权限问题时若刚改过配置，注意缓存失效时间或手动调 invalidate。
