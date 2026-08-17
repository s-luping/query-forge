# QueryForge AI 记忆文档

> 给后续 AI 开发者/维护者的项目速查手册。改动前先读本文，避免踩已知的坑。
> 最后更新：2026-08-17（分支 `feature/admin-console-upgrade`）

## 1. 项目是什么

QueryForge = **自然语言 → SQL** 的智能数据查询平台（内部系统）。
FastAPI + SQLAlchemy 2.0 + SQLite（双库）+ sentence-transformers（BGE-M3 向量检索）。

- 面向用户：`/`（home.html，SQL 对话工作台）；管理员后台：`/admin`（index.html，左侧菜单驱动）
- 端口：8188；**不使用 Docker**，本地 venv 部署（`start_server.bat`）

## 2. 如何运行 / 验证

```bash
# 启动（日志统一进 logs/，app.log/server.log/sqlalchemy.log 等自动轮转）
start_server.bat            # 或 .venv\Scripts\python.exe main.py
```
- **必须用项目 venv**（`.venv\Scripts\python.exe`，SQLAlchemy 2.0.50）。系统 Python 的 SQLAlchemy 1.4 跑不起来（无 DeclarativeBase）。
- Python 改动需重启服务（reload 默认关闭）；静态文件（static/）改完即生效。
- 默认管理员：admin / REDACTED；`ALLOW_REGISTER=false`（注册关闭，账号由管理员建）。
- 冒烟：`GET /api/system/site-branding`（公开）、admin 登录后 `GET /api/user/list`、`GET /api/driver/list`。

## 3. 数据库布局（双库，SQLite WAL）

| 库 | 内容 | 关键表 |
|---|---|---|
| `db/queryforge.db`（主库，FK 约束**开启**） | 用户/配置/Schema/知识/对话/统计/设置 | users, db_schemas→db_tables→db_columns, data_sources→sync_job_configs→sync_run_logs→schema_change_logs, system_settings, llm_configs, conversations, knowledge_items, user_*_grants, row_scope_rules, query_audit_logs, vector_index_meta |
| `db/llm_telemetry.db`（遥测库） | LLM 调用明细 | llm_calls, llm_prompts |

- 四层结构：**数据源(data_sources) → 库(db_schemas.datasource_id) → 表 → 字段**。
  手动导入的库 datasource_id 为空（前端归入「未关联数据源」）；同步自动关联。
- 新增列用 `models/database.py` 的 `_migrate_columns()` 加 ALTER 迁移（create_all 不改已有表）。
- **外键约束开启**：删除父表数据必须按依赖顺序清子表，否则 IntegrityError→500（历史教训：delete_datasource / delete_job / delete_user 都已做级联清理）。

## 4. 目录速览

- `main.py`：应用入口 + 安全响应头（CSP frame-ancestors 可配置）+ 页面访问守卫（template_auth_guard，未登录跳 /login，非 admin 访问管理页 403）+ uvicorn 日志轮转
- `app/`：auth（JWT+HttpOnly cookie，`AdminUser`/`CurrentUser` 依赖）、routers/、config.py（环境变量）、logger.py、limiter.py
- `models/`：SQLAlchemy 模型（MainBase/TelemetryBase 双基类）
- `services/`：schema（解析器 csv/json + service）、sync（connectors/engine/diff）、sql（权限网关 gateway）、llm（遥测）
- `core/`：llm/client、generation（pipeline/chat/audit）、retrieval（向量/索引）
- `static/`：纯 HTML+JS（Bootstrap5），`app_common.js`（公共 apiRequest/e()/QF 框架/分页组件）、`branding.js`、按页 JS 文件
- `docs/`：本文 + SYSTEM_DESCRIPTION.md（系统说明）+ 历史分析文档
- `logs/`：app/server/sqlalchemy/llm/pipeline/audit 日志（轮转）

## 5. 关键约定（改动前必读）

- **认证**：token 为 **HttpOnly cookie**，前端 JS 读不到 → 取用户一律走 `GET /api/user/profile`；前端解码 JWT 的做法是错的（曾导致菜单不显示 bug）。
- **权限**：接口层 `user: AdminUser`（自动 401/403）；页面层 template_auth_guard（system/ 模板仅 admin）+ 前端 `data-admin-only` 属性（app_common.js 对非 admin 移除）。
- **敏感等级**：DB 存英文（public/internal/sensitive/confidential），前端显示中文（`QF.levelLabel`）；徽标 CSS 类 `badge.bg-*` 必须带底色（`common.css`），否则白字不可见（历史 bug）。
- **数据库类型必填**：所有结构导入（CSV/JSON/上传）必须带 `db_type` + `datasource_id`（后端校验）。
- **导入格式**：仅规范 CSV（表头中文别名兼容：库名/表名/字段名/…）与 JSON（Spider/自定义）；DDL 解析已移除。
- **apiRequest**：FormData 上传时不要强制 `Content-Type: application/json`（app_common.js 已处理）；401 统一跳 /login。
- **分页**：通用组件 `QF.renderPager(容器id, {total, page, pageSize, onPage})`；超过 50 行的列表都要分页。
- **子页签**：同步/安全审计页的子页签已下沉到左侧菜单，通过 URL `#hash` 直达（switchTab + history.replaceState）；权限管理保留页内层级页签（数据源→库→表→字段→知识库）。
- **日志**：统一写 `logs/`；sqlalchemy 仅 WARNING 级；uvicorn 日志按天轮转保留 30 天。
- **服务进程**：以后台任务托管时可能因端口被占/日志文件锁失败；正规做法是用户自己的实例或 `start_server.bat`。

## 6. 近期大改动（2026-08）

1. 权限管理重写：搜索+分页+跨页保留勾选/修改；字段权限归口权限管理（移除安全审计重复页签）
2. 用户管理模块：管理员 CRUD + 级联清理；关闭自助注册（ALLOW_REGISTER）
3. 驱动管理：11 项驱动目录 + 一键 pip 安装（`/api/driver/*`）
4. Schema 重构：仅 CSV/JSON 导入；四层数据源关联；数据浏览级联筛选 + 模板下载/上传 + 库表字段删除
5. 全站分页、品牌自定义（SITE_LOGO/SITE_NAME）、CSP frame-ancestors 可配置、HTML 禁缓存
6. 移除：结构维护页、DDL 方言解析器（git 历史可找回）、Docker 文件（不使用 Docker）、旧架构遗留 db 文件
7. 修复：数据源/任务/用户删除的外键 500、徽标白字不可见、同步历史 Schema 列显示

## 7. 已知坑 / 提醒

- 手动用数据库工具删表 = 灾难（ORM 映射坏、重启重建空表）。删数据走界面。
- 删除由数据源同步维护的库前，先停用/删除对应同步任务（调度器每 10 分钟自动同步，删了会回来）。
- 服务器日志文件锁：后台任务 `*> file` 重定向可能因文件被占用失败并连带杀进程；用唯一文件名或交给 start_server.bat。
- `db/`、`logs/`、`.venv` 在 .gitignore，勿提交。
