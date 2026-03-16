# QueryForge 智能数据查询平台

QueryForge 是一款基于自然语言的数据查询工具，通过大模型技术将自然语言转换为 SQL 查询语句。支持多种主流大模型、Schema 管理、表数据管理、SQL 生成与查询等功能，适用于企业数据分析和快速查询场景。

---

## 目录结构

```
QueryForge/
├── app/                    # 应用核心模块
│   ├── routers/            # API 路由
│   │   ├── base_router.py          # 基础认证路由
│   │   ├── chat_to_sql_router.py   # SQL生成核心路由
│   │   ├── schema_router.py        # Schema 管理路由
│   │   ├── history_router.py       # 历史记录路由
│   │   ├── extra_router.py         # 补充知识路由
│   │   ├── table_data_router.py    # 表数据管理路由
│   │   ├── llm_config_router.py    # 大模型配置路由
│   │   └── llm_router.py           # LLM调用记录路由
│   ├── config.py           # 配置管理
│   ├── auth.py            # 用户认证
│   ├── logger.py          # 日志管理
│   ├── limiter.py         # 限流配置
│   └── utils.py           # 工具函数
├── core/                  # 核心业务模块
│   ├── LLMClient.py       # 大模型客户端（支持GLM/Qwen/DeepSeek/Doubao/OpenAI）
│   ├── SQLGenerator.py    # SQL 生成器
│   ├── DatabaseManager.py  # 数据库管理器
│   └── models.py          # 数据模型
├── models/                # 数据模型定义
│   ├── user.py            # 用户模型
│   ├── schema.py          # Schema 解析模型
│   ├── historical_sql.py  # SQL 历史记录模型
│   ├── extra_knowledge.py # 补充知识模型
│   ├── llm_config.py      # 大模型配置模型
│   ├── llm_log.py         # LLM调用记录模型
│   └── __init__.py        # 数据库初始化
├── scheduler/             # 定时任务模块
│   ├── scheduler.py      # 调度器管理
│   └── jobs.py           # 定时任务定义
├── static/                # 静态资源
│   ├── css/              # 样式文件
│   ├── js/               # JavaScript 文件
│   ├── webfonts/         # 字体文件
│   └── template/         # HTML 模板
│       ├── index.html            # 主页面
│       ├── login.html            # 登录页面
│       ├── chatSQL/             # SQL生成页面
│       ├── llm/                 # 大模型管理页面
│       ├── schema/              # Schema管理页面
│       └── table_data/          # 表数据管理页面
├── utils/                # 工具模块
│   └── DBSchemaUtil.py   # 数据库 Schema 工具
├── db/                   # SQLite 数据库存储
│   ├── sys_app.db        # 应用数据库（用户、LLM配置）
│   ├── sys_history.db    # 历史记录数据库
│   ├── sys_schema.db     # Schema数据库
│   ├── sys_extra.db      # 补充知识数据库
│   └── sys_llm.db        # LLM调用记录数据库
├── main.py               # 项目入口
├── requirements.txt      # Python 依赖
├── Dockerfile           # Docker 构建文件
├── docker-compose.yml   # Docker Compose 配置
├── .env                 # 环境变量配置
└── DEPLOYMENT.md        # 部署文档
```

---

## 主要功能模块

### 1. 大模型管理

- **多模型支持**：支持 GLM、Qwen、DeepSeek、Doubao、OpenAI 等主流大模型
- **前端配置**：通过前端界面配置 API 密钥、模型参数（Max Tokens、Temperature、Timeout）
- **配置管理**：支持多配置管理，可设置默认配置
- **连接测试**：支持 API 连接测试验证
- **调用记录**：记录所有 LLM 调用详情，包括问题、模型、条件、结果、耗时、Token 消耗

### 2. SQL 生成与查询

- **自然语言转 SQL**：通过自然语言描述生成 SQL 查询语句
- **大模型集成**：支持多种主流大模型，智能理解查询意图
- **SQL 验证**：自动验证生成的 SQL 安全性，只允许 SELECT 查询
- **历史记录**：保存查询历史，支持评分和复用
- **补充知识**：支持字段示例值、表间关系、领域知识等补充信息

### 3. Schema 管理

- **DDL 解析**：上传或输入 DDL 语句，自动解析表结构信息
- **字段信息管理**：管理表名、字段名、类型、注释、主键等信息
- **单库支持**：DDL 解析仅支持单数据库，表名不可重复

### 4. 表数据管理

- **数据预览**：查看表数据，支持分页
- **数据编辑**：支持增删改查操作
- **历史查询**：使用历史 SQL 进行查询

### 5. 补充知识

- **领域知识**：添加业务领域相关知识，帮助大模型理解业务逻辑
- **字段示例值**：提供字段的常见值，帮助生成更准确的 WHERE 条件
- **表间关系**：描述表之间的关联关系，帮助优化 JOIN 操作

### 6. 用户认证

- **JWT Token 认证**：基于 Token 的用户认证
- **角色权限**：支持管理员和普通用户角色
- **自动登录校验**：前端自动校验 Token 有效性

---

## 运行说明

### 1. 环境要求

- Python 3.12+
- SQLite
- 网络访问（用于调用大模型 API）

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置环境变量

编辑 `.env` 文件，设置以下环境变量：

```env
# TOKEN 配置
SECRET_KEY=your_secret_key
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
```

### 4. 启动服务

```bash
python main.py
```

服务启动后访问 http://localhost:8188

### 5. 配置大模型

1. 登录系统后，点击左侧菜单「大模型管理」→「模型配置管理」
2. 选择模型提供商（GLM/Qwen/DeepSeek/Doubao/OpenAI）
3. 输入 API 密钥和模型名称
4. 点击「测试连接」验证配置
5. 保存配置并设为默认

### 6. 默认管理员账号

- 用户名：`admin`
- 密码：`MyAdmin123`

---

## Docker 部署

### 1. 构建镜像

```bash
docker build -t queryforge .
```

### 2. 使用 Docker Compose

```bash
docker-compose up -d
```

详细部署说明请参考 [DEPLOYMENT.md](DEPLOYMENT.md)

---

## API 文档

项目关闭了 Swagger UI 文档，如需开启请修改 `main.py`：

```python
app = FastAPI(docs_url="/docs", redoc_url="/redoc", lifespan=lifespan)
```

---

## 权限与安全

- 基于 JWT Token 的用户认证
- SQL 查询安全验证，只允许 SELECT 查询
- 防止 SQL 注入攻击
- 支持基于角色的权限控制
- API 密钥加密存储

---

## 技术栈

- **后端**：FastAPI + SQLAlchemy + SQLite
- **大模型**：支持 GLM、Qwen、DeepSeek、Doubao、OpenAI
- **前端**：HTML + JavaScript + Bootstrap 5
- **部署**：Docker + Docker Compose

---

## 数据库说明

项目使用多个 SQLite 数据库分离存储不同类型的数据：

| 数据库 | 说明 |
|--------|------|
| sys_app.db | 用户数据、LLM配置 |
| sys_history.db | SQL生成历史记录 |
| sys_schema.db | Schema数据 |
| sys_extra.db | 补充知识数据 |
| sys_llm.db | LLM调用记录 |

---

## 性能优化建议

1. **缓存优化**：项目已实现 SQL 验证结果缓存
2. **数据库**：生产环境可考虑使用 PostgreSQL 替代 SQLite
3. **限流**：已集成 SlowAPI 限流功能
4. **日志**：分离应用日志和 SQL 日志

---

## 扩展开发

### 添加新的大模型支持

1. 在 `core/LLMClient.py` 的 `MODEL_CONFIGS` 中添加新模型配置
2. 添加对应的默认模型和 API 地址

### 添加新的业务功能

1. 在 `app/routers/` 目录创建新的路由文件
2. 在 `core/` 目录添加业务逻辑
3. 在 `models/` 目录定义数据模型
4. 在 `main.py` 中注册新路由

### 连接外部数据库

修改 `.env` 文件中的数据库连接配置：

```env
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_password
DB_NAME=your_database
```

---

## 更新日志

### v1.0.0

- 支持自然语言转 SQL
- 支持 Schema 管理
- 支持历史记录和评分
- 支持补充知识功能
- 支持多种主流大模型（GLM/Qwen/DeepSeek/Doubao/OpenAI）
- 支持前端配置大模型参数
- 支持 LLM 调用记录追踪
- 支持表数据管理
- 支持 Docker 部署
