# QueryForge 智能数据查询平台

QueryForge 是一款基于自然语言的数据查询工具，通过大模型技术将自然语言转换为 SQL 查询语句。支持任意 OpenAI 兼容 API 的大模型、数据库 Schema 管理、SQL 生成与查询等功能，适用于企业数据分析和快速查询场景。

---

## 技术亮点

### 1. 灵活的模型配置
- **任意模型支持**：支持所有 OpenAI 兼容 API 的大模型，自由输入供应商、模型名称和 API 地址
- **前端灵活配置**：通过前端界面配置供应商、模型、API 密钥、API 地址及参数（Max Tokens、Temperature、Timeout）
- **连接测试验证**：支持 API 连接测试，确保配置正确
- **调用记录追踪**：自动记录每次 LLM 调用的系统提示词、供应商、模型、Token 消耗、成本、耗时、状态

### 2. 智能 SQL 生成流程
- **字段级索引 + 按表聚合**：业界领先的 RAG 方案，兼顾精确检索与上下文完整性
- **关键词提取**：自动从用户问题中抽取关键词，提升检索准确性
- **向量语义搜索**：基于 BGE-M3 embedding 模型，支持中英文语义理解
- **降级机制**：向量索引构建失败时自动降级到数据库查询，确保服务可用
- **维度层级规则**：系统提示词内置维度层级过滤，自动处理父子节点汇总避免数据翻倍
- **多轮对话**：支持连续对话式 SQL 生成，知识库内容在后续轮次自动携带

### 3. 高性能向量存储
- **纯 Python 实现**：NumPy 向量索引，无需 FAISS 依赖，降低部署复杂度
- **本地模型支持**：支持从 ModelScope 下载 BGE-M3 embedding 模型
- **智能缓存**：模型路径和就绪状态持久化到数据库，避免每次扫描目录
- **索引元数据管理**：向量索引构建状态、字段数、表数、文件路径存入数据库，查询优先读库
- **并发安全**：构建期间新数据导入自动标记过期，支持最多 3 次重试

### 4. 强大的数据库管理
- **规范结构导入**：支持规范 CSV（中文表头）与 JSON（Spider/自定义格式）导入，数据库类型与数据源必填
- **元数据同步**：MySQL、PostgreSQL、SQLite 定时同步表结构并自动比对变更（新增自动应用、删除待审批）
- **Spider 数据集兼容**：支持 Spider 数据集 JSON 格式解析
- **库/表/字段搜索**：支持按数据库名、表名、字段名、描述模糊搜索
- **自动向量索引**：字段数量 >= 50 时自动后台构建向量索引

### 5. 完善的数据管理
- **多数据库分离存储**：用户、LLM配置、Schema、知识库、LLM调用记录、对话记录、向量索引元数据分别存储
- **对话记录持久化**：多轮对话和消息自动保存，知识库按 ID 关联，后续轮次自动复用
- **权限管理**：支持管理员/普通用户角色，Schema 和知识库可分配可见权限

---

## 目录结构

```
QueryForge/
├── app/                    # 应用核心模块
│   ├── routers/            # API 路由
│   │   ├── auth_router.py           # 基础认证路由（登录/注册）
│   │   ├── chat_to_sql_router.py   # SQL生成核心路由（旧版单次生成）
│   │   ├── schema_router.py        # Schema 管理 + 向量索引路由
│   │   ├── knowledge_router.py      # 知识库路由
│   │   ├── llm_router.py           # 大模型配置 + 调用记录路由
│   │   ├── conversation_router.py  # 多轮对话路由（新版 Chat SQL）
│   │   ├── system_router.py        # 系统配置路由
│   │   └── user_router.py          # 用户管理路由
│   ├── config.py           # 配置管理
│   ├── auth.py             # 用户认证 (JWT)
│   ├── permissions.py      # 权限校验
│   ├── logger.py           # 日志管理
│   ├── limiter.py          # 限流配置
│   └── utils.py            # 工具函数
├── core/                   # 核心业务模块（按功能域分包）
│   ├── llm/                 # LLM 调用域
│   │   └── client.py         # LLMClient（通用 OpenAI 兼容 API）
│   ├── retrieval/           # 检索召回域
│   │   ├── keywords.py       # 关键词提取（jieba 分词）
│   │   ├── vector_store.py   # 向量存储（EmbeddingModel + VectorIndex + SchemaVectorStore）
│   │   ├── index_meta.py     # 向量索引构建 + 元数据读写
│   │   └── retriever.py      # SchemaRetriever 共享检索器（召回→表聚合→CSV）
│   └── generation/          # SQL 生成编排域
│       ├── sql_generator.py  # SQL prompt 构建 + 安全校验
│       ├── pipeline.py       # SQLPipeline 单轮流水线编排
│       ├── chat.py           # ChatSession 多轮对话
│       └── audit.py          # 查询审计日志写入
├── models/                 # SQLAlchemy 数据模型
│   ├── __init__.py         # 数据库初始化、迁移、种子数据
│   ├── user.py             # 用户 + 权限关联模型
│   ├── schema.py           # Schema 模型
│   ├── knowledge.py        # 知识库模型
│   ├── conversation.py     # 多轮对话模型（含 knowledge_id）
│   ├── llm.py              # LLM 配置 + 调用记录模型（含 system_prompt）
│   ├── system.py           # 系统配置模型（键值对）
│   └── vector_index.py     # 向量索引元数据模型（新建）
├── static/                 # 静态资源
│   ├── css/ / js/ / webfonts/
│   └── template/
│       ├── index.html              # 主页面（含侧边栏菜单）
│       ├── login.html / change_password.html
│       ├── chatSQL/chat.html       # Chat SQL 多轮对话
│       ├── llm/
│       │   ├── llm_config.html     # 模型配置
│       │   └── llm_logs.html       # 调用记录（含 system_prompt 展示）
│       ├── schema/
│       │   ├── schema_view.html    # 数据库查看/浏览（级联筛选、CSV 导入、删除）
│       │   └── vector_index.html   # 向量索引管理（新建）
│       └── system/
│           ├── system_settings.html # 系统设置
│           ├── user_manage.html    # 用户管理（管理员 CRUD）
│           ├── permission_manage.html # 权限管理（数据源→库→表→字段→知识库）
│           ├── sync_manage.html    # 元数据同步（数据源/任务/历史/变更）
│           ├── security_manage.html # 安全审计（日志/敏感字段/行级规则）
│           └── driver_manage.html  # 数据库驱动管理
├── db/                     # SQLite 双库存储（运行时自动创建）
│   ├── queryforge.db        # 主库：用户/配置/Schema/知识/对话/统计/设置
│   ├── llm_telemetry.db     # 遥测库：LLM 调用明细
│   └── vectors/             # 向量索引 pickle 文件
├── logs/                   # 日志文件（app/server/sqlalchemy 等，自动轮转）
├── main.py                 # 项目入口
├── download_model.py        # 模型下载脚本（含路径缓存写入）
├── requirements.txt
├── start_server.bat         # 启动脚本（日志统一写入 logs/）
└── docs/VECTOR_INDEX.md    # 向量索引技术文档
```

---

## 主要功能模块

### 1. 大模型管理

- **任意模型支持**：支持所有 OpenAI 兼容 API，自由输入供应商名称、模型名称和 API 地址
- **前端配置**：通过前端界面配置供应商、API 密钥、模型名称、API 地址及参数
- **配置管理**：支持多配置管理，可设置默认、启用/禁用、公开共享
- **连接测试**：支持 API 连接测试验证
- **调用记录**：记录所有 LLM 调用详情，包括系统提示词、Token 消耗、成本、耗时、状态

### 2. SQL 生成与查询

- **多轮对话（Chat SQL）**：支持连续对话式 SQL 生成，基于上下文迭代优化
- **单次生成**：自然语言描述 → SQL，支持向量/关键词字段召回
- **智能流程优化**：
  - 关键词提取：jieba 分词 + TF 统计
  - 向量语义搜索：BGE-M3 编码 → 余弦相似度检索 top-K 字段
  - 按表聚合：获取完整表结构作为上下文
- **SQL 验证**：自动验证安全性，只允许 SELECT/WITH 查询
- **知识库**：支持字段示例值、表间关系、领域知识，生成 SQL 时注入提示词，多轮对话自动携带
- **维度层级保护**：系统提示词内置层级过滤规则，防止父节点汇总导致数据翻倍

### 3. 数据库管理

- **规范 CSV 导入**：中文表头模板（库名/表名/字段名/字段类型/…），仅支持 .csv / .json 文件
- **JSON 解析**：Spider 格式和自定义格式
- **数据源关联**：导入时必选数据源与数据库类型，库→表→字段四层结构，数据源→库→表级联筛选
- **搜索功能**：按数据库名、表名、字段名、描述模糊搜索，300ms 防抖
- **Schema/表级联筛选**：选择数据库后自动加载表列表
- **自动向量索引**：字段数 >= 50 时后台自动构建，支持重试和并发保护

### 4. 向量索引管理（管理员）

- **元数据持久化**：索引状态、字段数、表数、文件路径、构建时间存入 `vector_index_meta` 表
- **独立管理页面**：查看所有数据库的索引状态，支持手动重建
- **自动过期检测**：数据导入时标记 stale，构建完成检测冲突自动重试

### 5. 知识库

- **领域知识**：添加业务领域相关知识（业务口径、计算规则等），生成 SQL 时以【领域知识】段落注入提示词，帮助大模型理解业务逻辑
- **字段示例值**：提供字段的常见值，帮助生成更准确的 WHERE 条件
- **表间关系**：描述表之间的关联关系（如维度层级架构）
- **公共/私有**：支持设为公开（所有用户可见）或私有（按用户授权）

### 6. 用户认证与权限

- **JWT Token 认证**：基于 Token 的用户认证，支持过期时间配置；token 以 HttpOnly Cookie 下发（防 XSS 窃取），也支持 `Authorization: Bearer <token>` 头调用 API
- **角色权限**：管理员和普通用户角色；未登录访问页面/模板一律跳转登录页，非管理员访问管理页面/接口返回 403
- **类型化依赖注入**：路由统一使用 `user: CurrentUser` / `user: AdminUser`（`Annotated[dict, Depends(...)]`）写法，角色校验下沉到依赖层
- **用户管理**（管理员）：系统管理 →「用户管理」，支持创建用户、编辑资料/角色、启用/禁用、重置密码（重置后该用户所有旧 token 立即失效）、删除用户（含关联授权/对话/知识清理）；自带保护规则（不能删除/禁用自己、系统至少保留一名管理员）
- **注册开关**：系统设置中 `ALLOW_REGISTER` 控制是否开放自助注册（企业内部建议关闭，改为管理员创建账号）；自助注册的账号需管理员激活后方可登录
- **资源权限**：Schema 和知识库可按用户分配可见权限，另有字段级（SELECT/FILTER/NONE）与行级过滤权限
- **四层权限模型**：数据源 → 库(Schema) → 表 → 字段。权限管理页按层配置：数据源可一键授权其同步出的全部库；库级勾选可见；表级白名单（同一库内配置后仅名单内表可见，未配置默认全可见）；字段级 SELECT/FILTER/NONE（可按敏感等级默认推导）。表级权限在查询列表、Schema 检索(LLM prompt)与 SQL 权限网关三层强制执行
- **密钥脱敏**：SECRET_KEY 在管理页面脱敏显示

---

## 运行说明

### 1. 环境要求

- Python >= 3.9, < 3.12（推荐 3.10.x）
- SQLite
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

模型将下载到 `models/embeddings/bge-m3` 目录，路径和就绪状态自动写入数据库。
> 向量索引构建的详细原理和流程，请参考 [docs/VECTOR_INDEX.md](docs/VECTOR_INDEX.md)

### 4. 启动服务

```bash
python main.py
```

服务启动后访问 http://localhost:8188

### 5. 配置大模型

1. 登录后点击「大模型管理」→「模型配置」
2. 输入供应商名称（如 OpenAI、DeepSeek 等，自由输入）
3. 输入模型名称和 API 密钥
4. 填写 API 地址（OpenAI 兼容端点）
5. 配置参数并测试连接

### 6. 导入数据库结构

1. 进入「数据浏览」页
2. 点击「模板下载」获取标准 CSV 模板，或使用规范 JSON（Spider/自定义格式）
3. 上传时必须选择**数据源**与**数据库类型**（均必填），支持 .csv / .json 文件

### 7. 默认管理员账号

- 用户名：`admin`
- 密码：`REDACTED`

---

## 数据库说明

项目使用 SQLite **双库**存储：

| 数据库 | 说明 |
|--------|------|
| queryforge.db（主库） | 用户、系统配置、Schema（库→表→字段）、知识、对话、统计、数据源/同步、权限、审计 |
| llm_telemetry.db（遥测库） | LLM 调用明细（llm_calls / llm_prompts） |

向量索引 pickle 文件存储在 `db/vectors/` 目录。

---

## 日志系统

| 日志文件 | 说明 |
|---------|------|
| app.log | 应用日志（API请求、认证、业务操作） |
| server.log | 服务日志（uvicorn 启动/访问，按天轮转保留30天） |
| llm.log | 大模型请求日志（含完整 system prompt 和消息内容） |
| pipeline.log | SQL生成过程日志（关键词提取、向量召回、表聚合） |
| sqlalchemy.log | 数据库异常日志（WARNING 以上，不再逐句记录 SQL） |
| audit.log | 审计日志（写操作、权限变更） |

---

## 技术栈

- **后端**：FastAPI + SQLAlchemy + SQLite
- **大模型**：支持所有 OpenAI 兼容 API（通用客户端，自由配置）
- **向量模型**：sentence-transformers + BGE-M3（1024维）
- **前端**：HTML + JavaScript + Bootstrap 5
- **部署**：本地 venv + start_server.bat（Python 3.10）

---

## 更新日志

### v1.4.0

- **数据库搜索**：数据库查看页新增库/表/字段模糊搜索，300ms 防抖
- **向量索引元数据**：新建 vector_index_meta 表持久化索引状态，独立管理页面
- **模型路径缓存**：EMBEDDING_MODEL_PATH 存入数据库，避免每次扫描目录
- **系统提示词优化**：内置维度层级过滤规则，多轮对话知识库内容自动携带
- **LLM 日志增强**：system_prompt 列记录完整提示词，前端可折叠展示
- **并发安全**：索引构建期间数据导入自动过期检测，最多 3 次重试
- **向量参数可配置**：VECTOR_INDEX_THRESHOLD / FIELD_RECALL_TOP_K / MAX_TABLES 存入 system_config，前端在线编辑实时生效
- **类型安全**：修复 SQLAlchemy Column 类型检查警告
- **前端重命名**：统一将 "Schema" 改为 "数据库"

### v1.3.0

- **模型配置重构**：移除硬编码供应商，支持所有 OpenAI 兼容 API
- **多轮对话（Chat SQL）**：连续对话式 SQL 生成，上下文迭代优化
- **对话记录持久化**：conversations + conversation_messages 表

### v1.2.0

- **日志系统重构**：app/llm/pipeline/sqlalchemy 日志分离

### v1.1.0

- Schema 管理增强、向量搜索优化、BGE-M3 支持

### v1.0.0

- 初始版本：NL→SQL、Schema 管理、知识库
