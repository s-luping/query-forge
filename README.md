# QueryForge 智能数据查询平台

QueryForge 是一款基于自然语言的数据查询工具，通过大模型技术将自然语言转换为 SQL 查询语句。支持任意 OpenAI 兼容 API 的大模型、数据库 Schema 管理、SQL 生成与执行、多轮对话、权限审计等功能，适用于企业数据分析和快速查询场景。

---

## 技术亮点

### 1. 灵活的模型配置
- **任意模型支持**：支持所有 OpenAI 兼容 API 的大模型，自由输入供应商、模型名称和 API 地址
- **前端灵活配置**：通过前端界面配置供应商、模型、API 密钥、API 地址及参数（Max Tokens、Temperature、Timeout）
- **连接测试验证**：支持 API 连接测试，确保配置正确
- **调用记录追踪**：自动记录每次 LLM 调用的系统提示词、供应商、模型、Token 消耗、成本、耗时、状态
- **SSRF 防护**：API 地址校验禁止指向内网 IP，防止服务器端请求伪造

### 2. 智能 SQL 生成流程
- **字段级召回 + 按表聚合**：业界领先的 RAG 方案，兼顾精确检索与上下文完整性
- **关键词提取**：自动从用户问题中抽取关键词，提升检索准确性
- **向量语义搜索**：基于 BGE-M3 embedding 模型，支持中英文语义理解；向量失败自动降级数据库关键词查询
- **知识库召回**：typed 知识（业务口径/术语/计算规则/表关系/取值域等）按关键词召回注入提示词，relation 知识自动跨库扩表
- **可行性判断**：生成前先让 LLM 判断信息是否充足，不足时返回缺失项与建议，避免无效生成
- **维度层级规则**：系统提示词内置维度层级过滤，自动处理父子节点汇总避免数据翻倍
- **多轮对话**：支持连续对话式 SQL 生成，追问轮复用首轮表集合累积召回

### 3. 高性能向量存储
- **纯 Python 实现**：NumPy 向量索引，无需 FAISS 依赖，降低部署复杂度
- **本地模型支持**：支持从 ModelScope 下载 BGE-M3 embedding 模型
- **索引元数据管理**：向量索引构建状态、字段数、表数、文件路径存入数据库，查询优先读库
- **并发安全**：构建期间新数据导入自动标记过期，支持最多 3 次重试

### 4. 强大的数据库管理
- **规范结构导入**：支持规范 CSV（中文表头）与 JSON（Spider/自定义格式）导入
- **元数据同步**：MySQL、PostgreSQL、SQLite 定时同步表结构并自动比对变更（新增自动应用、删除待审批）
- **库/表/字段搜索**：支持按数据库名、表名、字段名、描述模糊搜索
- **自动向量索引**：字段数量 >= 50 时自动后台构建向量索引
- **数据源管理**：外部数据库连接配置（密码加密存储），数据源 → 库 → 表 → 字段四层结构

### 5. 完善的权限与安全
- **四层权限模型**：数据源 → 库(Schema) → 表 → 字段（SELECT/FILTER/NONE 三级）
- **行级过滤**：可配置表级行过滤规则（如"销售只能看自己大区"），SQL 网关自动注入 WHERE
- **SQL 权限网关**：AST 解析 + 字段级权限校验，`SELECT *` 自动展开为授权字段，敏感字段命中留痕
- **敏感字段分级**：公开/内部/敏感/机密四级，默认推导（公开内部→SELECT、敏感→FILTER、机密→NONE）
- **查询审计**：每次查询记录问题、SQL、命中的表/字段、是否拦截、耗时、完整链路追踪
- **JWT 认证**：HttpOnly Cookie 下发 + Bearer 头双通道，密码修改后旧 token 立即失效
- **密钥加密**：密码 bcrypt 哈希，API Key / 数据源密码 Fernet 加密存储

---

## 目录结构

```
QueryForge/
├── main.py                 # 应用入口（路由注册 + 中间件 + 调度器 + 向量预热）
├── app/                    # 应用核心
│   ├── routers/            # API 路由（auth/user/schema/knowledge/llm/conversation/
│   │                       #   system/permission/security/sync/driver/scheduler/docs/page）
│   ├── auth.py             # JWT 认证 + CurrentUser/AdminUser 依赖
│   ├── permissions.py      # 四层权限校验（数据源→库→表→字段，含 TTL 缓存）
│   ├── middleware.py       # 安全响应头 / 访问日志 / 页面访问守卫 / CORS
│   ├── logger.py           # 日志系统（app/llm/audit/server 分离，自动轮转）
│   ├── config.py           # 全部配置唯一初始值来源
│   ├── crypto.py           # Fernet 加解密
│   ├── limiter.py          # 限流配置
│   └── timezone.py / utils.py
├── core/                   # 核心业务（扁平化按功能文件）
│   ├── gen_chat.py         # ChatSession 多轮对话生成链路
│   ├── gen_sql.py          # SQL prompt 构建 + 安全校验
│   ├── gen_audit.py        # 查询审计日志写入
│   ├── llm_client.py       # LLMClient（OpenAI 兼容 API，SSRF 防护，连接池复用）
│   ├── ret_retriever.py    # SchemaRetriever 共享检索器（召回→聚合→CSV→知识召回）
│   ├── ret_keywords.py     # 关键词提取（jieba 分词）
│   ├── ret_vector_store.py # 向量存储（EmbeddingModel + SchemaVectorStore）
│   └── ret_index_meta.py   # 向量索引构建 + 元数据读写
├── crud/                   # 数据访问层（base 泛型 CRUD + 各模块）
├── services/               # 业务服务
│   ├── sql_executor.py     # SQL 执行器（仅 SELECT，按库路由数据源，引擎缓存复用）
│   ├── sql_gateway.py      # SQL 权限网关（AST 解析 + 字段校验 + 行级注入）
│   ├── schema_service.py   # Schema 三层模型读写 + 平铺视图
│   ├── schema_parsers.py   # CSV/JSON 结构解析
│   ├── sync_engine.py      # 元数据同步引擎（读源库→diff→应用→记录）
│   ├── sync_connectors.py / sync_diff.py / sync_classify.py
│   ├── telemetry.py        # LLM 调用遥测（llm_calls + llm_prompts 去重）
│   └── vector_service.py   # 向量索引自动构建服务
├── models/                 # SQLAlchemy 数据模型（MainBase/TelemetryBase 双基类）
├── db/                     # 数据库引擎与初始化
│   ├── engine.py           # 方言自适应引擎（SQLite/MySQL/PostgreSQL）
│   ├── database.py         # 初始化编排 + 种子数据
│   ├── sqlite_hooks.py     # SQLite PRAGMA 钩子 + 轻量迁移
│   └── seed.py             # 种子数据
├── scheduler/              # 定时任务
│   ├── scheduler.py        # 调度器注册
│   └── jobs/               # usage_stats(用量聚合) / retention(数据清理) / schema_sync(自动同步)
├── static/                 # 前端（纯 HTML+JS，Bootstrap5）
│   ├── css/ js/ img/ vendor/ webfonts/
│   └── template/           # login/home/index/chatSQL/knowledge/schema/llm/system 页面
├── scripts/                # 运维脚本（reset_admin_password / verify_db_split 等）
├── docs/                   # 文档（见下方"文档"一节）
├── logs/                   # 日志文件（自动轮转）
├── download_model.py       # BGE-M3 模型下载脚本
├── requirements.txt
└── start_server.bat        # 启动脚本（Windows）
```

---

## 主要功能模块

### 1. 大模型管理
- **任意模型支持**：支持所有 OpenAI 兼容 API，自由输入供应商名称、模型名称和 API 地址
- **配置管理**：支持多配置管理，可设置默认、启用/禁用、公开共享
- **调用记录**：记录所有 LLM 调用详情，包括系统提示词、Token 消耗、成本、耗时、状态
- **用量统计**：按 天×用户×模型 聚合展示（scheduler 定时刷新）

### 2. SQL 生成与查询
- **多轮对话（Chat SQL）**：支持连续对话式 SQL 生成，基于上下文迭代优化；创建对话无需选库，全库模式按权限自动决定数据范围
- **智能流程**：关键词提取 → 向量/关键词字段召回 → 按表聚合 → 知识召回扩表 → 可行性判断 → LLM 生成 → SQL 校验 → 权限网关 → 执行查询
- **SQL 验证**：自动验证安全性，只允许 SELECT/WITH 查询；执行时同样二次校验
- **查询结果**：生成后自动执行并返回结果表格，会话内展示前 10 行，完整结果弹窗查看

### 3. 数据库管理
- **规范 CSV 导入**：中文表头模板（库名/表名/字段名/字段类型/…），支持 .csv / .json 文件
- **元数据同步**：配置数据源 + 同步任务，定时自动同步外部库表结构，变更自动应用或待审批
- **搜索功能**：按数据库名、表名、字段名、描述模糊搜索
- **自动向量索引**：字段数 >= 50 时后台自动构建，支持重试和并发保护

### 4. 知识库
- **typed 知识**：note/terminology/calculation/relation/value_domain/convention/entity_map/sample_qa 八种类型
- **召回增强**：别名（aliases）命中即召回；作用域（scope_schema_id）限定库或全局
- **注入提示词**：生成 SQL 时以【领域知识】段落注入，帮助大模型理解业务逻辑

### 5. 用户认证与权限
- **JWT Token 认证**：HttpOnly Cookie 下发（防 XSS 窃取），支持 Bearer 头；过期时间可配置
- **角色权限**：角色绑定权限（路由/页面/库/表/字段/数据源/知识 多资源类型），权限管理页按层配置
- **类型化依赖注入**：路由统一使用 `user: CurrentUser` / `user: AdminUser`
- **用户管理**：创建/编辑/启停/重置密码/删除用户（级联清理关联数据）；保护规则（不能删/禁用自己、至少保留一名管理员）
- **注册开关**：`ALLOW_REGISTER` 控制是否开放自助注册

### 6. 调度任务
- **用量聚合**：每小时将 llm_calls 聚合到 llm_usage_stats（回溯 7 天幂等覆盖）
- **数据清理**：每日清理过期遥测数据（90 天）、主库审计/同步历史（90 天）、对话结果 JSON（30 天）
- **WAL checkpoint**：每日 04:00 回收 SQLite WAL 文件体积
- **自动同步**：每 10 分钟检查并执行到期的元数据同步任务

---

## 运行说明

### 1. 环境要求
- Python >= 3.9（推荐 3.10.x）
- SQLite（默认）或 MySQL/PostgreSQL（修改 config 切换）
- 网络访问（用于调用大模型 API）

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 下载向量模型（可选）

首次运行前建议下载 BGE-M3 embedding 模型：

```bash
python download_model.py
```

> 向量索引与 NL2SQL 链路的详细设计，请参考 [docs/NL2SQL设计与实现.md](docs/NL2SQL设计与实现.md) 与 [docs/系统架构设计.md](docs/系统架构设计.md)

### 4. 启动服务

```bash
# 方式一：Windows 脚本
start_server.bat

# 方式二：直接运行
.venv\Scripts\python.exe main.py
```

服务启动后访问 http://localhost:8888（端口在 `app/config.py` 的 `PORT` 修改）

### 5. 默认管理员账号

- 用户名：`admin`
- 密码：`REDACTED`

---

## 数据库说明

项目使用 **SQLite 双库**（WAL 模式）存储，也可通过修改 `app/config.py` 的 `DATABASE_URL` 切换 MySQL/PostgreSQL：

| 数据库 | 说明 |
|--------|------|
| queryforge.db（主库） | 用户、系统配置、Schema 三层（库→表→字段）、知识、对话、统计、数据源/同步、权限、审计 |
| llm_telemetry.db（遥测库） | LLM 调用明细（llm_calls / llm_prompts），高频追加写物理隔离 |

- 主库开启外键约束，遥测库不开启
- 两库均启用 WAL + busy_timeout=5000 + synchronous=NORMAL
- 向量索引 pickle 文件存储在 `db/vectors/` 目录
- 数据保留策略：遥测 90 天、审计/同步历史 90 天、对话结果 JSON 30 天（scheduler 每日清理）

---

## 日志系统

| 日志文件 | 说明 |
|---------|------|
| app.log | 应用日志（请求、认证、业务、异常），10MB 轮转保留 5 份 |
| llm.log | 大模型调用详情（请求/响应内容、Token、耗时），10MB 轮转保留 5 份 |
| audit.log | 审计日志（写操作、权限变更），10MB 轮转保留 5 份 |
| server.log | 服务日志（uvicorn 启动/访问），按天轮转保留 30 天 |

> SQL 生成过程（pipeline）链路追踪已写入数据库 `QueryAuditLog.pipeline_log` 字段，
> 供前端「链路追踪」弹窗展示，不再单独输出文件日志。

---

## 技术栈

- **后端**：FastAPI + SQLAlchemy 2.0 + SQLite（可选 MySQL/PostgreSQL）
- **大模型**：支持所有 OpenAI 兼容 API（通用客户端，自由配置）
- **向量模型**：sentence-transformers + BGE-M3（1024 维）
- **SQL 解析**：sqlglot（权限网关 AST 解析）
- **调度**：APScheduler
- **前端**：HTML + JavaScript + Bootstrap 5
- **部署**：本地 venv + start_server.bat

---

## 文档

| 文档 | 说明 |
|------|------|
| [docs/系统使用文档.md](docs/系统使用文档.md) | 面向业务用户与管理员的使用手册 |
| [docs/系统架构设计.md](docs/系统架构设计.md) | 总体架构、三库分离、权限与安全体系 |
| [docs/NL2SQL设计与实现.md](docs/NL2SQL设计与实现.md) | NL2SQL 全链路（召回/聚合/知识/网关/执行）设计与实现 |
| [docs/部署运维手册.md](docs/部署运维手册.md) | 安装部署、配置项、日常运维、故障排查 |
| [docs/资产总表.md](docs/资产总表.md) | 接口/表/页面/作业登记总表（开发纲领 §5，CI 核对） |
| docs/NL2SQL经典场景测试报告.pdf · docs/NL2SQL验证测试报告.pdf | NL2SQL 测试报告 |

---

## 更新日志

### v1.5.0（2026-08-28）
- **日志系统瘦身**：移除未使用的 pipeline.log / sqlalchemy.log，日志按类型分离（app/llm/audit/server）
- **主库数据保留策略**：新增每日清理任务（审计/同步历史 90 天、对话结果 JSON 30 天）
- **WAL checkpoint**：每日自动回收 SQLite WAL 文件体积
- **补齐关键索引**：审计拦截/敏感字段、同步审批状态/变更类型、敏感等级、遥测状态/目的等高频过滤字段
- **权限 TTL 缓存**：单次请求内权限计算复用，改权限立即失效
- **知识召回 SQL 下推**：从全量加载改为 SQL LIKE 粗筛 + 内存打分
- **SQL 执行引擎复用**：按数据源缓存连接引擎，避免每次新建/销毁
- **对话列表分页**：接口返回 `{items, total}`，前端支持加载更多
- **用量聚合优化**：范围比较替代 func.date()，索引可生效

### v1.4.0
- 数据库搜索、向量索引元数据持久化、模型路径缓存、维度层级规则、并发安全、向量参数可配置

### v1.3.0
- 模型配置重构（支持任意 OpenAI 兼容 API）、多轮对话（Chat SQL）、对话记录持久化

### v1.2.0
- 日志系统重构（按类型分离）

### v1.1.0
- Schema 管理增强、向量搜索优化、BGE-M3 支持

### v1.0.0
- 初始版本：NL→SQL、Schema 管理、知识库
