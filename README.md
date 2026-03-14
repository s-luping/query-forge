# QueryForge 智能数据分析平台

本项目基于 FastAPI 实现，通过自然语言描述生成 SQL 查询并可视化数据。集成了智谱 AI GLM-4.5 大模型，支持 Schema 管理、历史记录查询、补充知识等功能，适用于企业数据分析和 BI 系统的快速搭建。

---

## 目录结构

```
QueryForge/
├── app/                    # 应用核心模块
│   ├── routers/            # API 路由
│   │   ├── base_router.py          # 基础认证路由
│   │   ├── chat_to_sql_router.py   # Chat to SQL 核心路由
│   │   ├── schema_router.py        # Schema 管理路由
│   │   ├── history_router.py       # 历史记录路由
│   │   └── extra_router.py         # 补充知识路由
│   ├── config.py           # 配置管理
│   ├── auth.py            # 用户认证
│   ├── logger.py          # 日志管理
│   ├── limiter.py         # 限流配置
│   └── utils.py           # 工具函数
├── core/                  # 核心业务模块
│   ├── LLMClient.py       # 智谱 AI 大模型客户端
│   ├── SQLGenerator.py    # SQL 生成器
│   ├── DatabaseManager.py  # 数据库管理器
│   └── models.py          # 数据模型
├── models/                # 数据模型定义
│   ├── user.py            # 用户模型
│   ├── schema_parse.py   # Schema 解析模型
│   ├── sql_history.py    # SQL 历史记录模型
│   ├── extra.py          # 补充知识模型
│   └── __init__.py       # 数据库初始化
├── scheduler/             # 定时任务模块
│   ├── scheduler.py      # 调度器管理
│   └── jobs.py           # 定时任务定义
├── static/                # 静态资源
│   ├── css/              # 样式文件
│   ├── js/               # JavaScript 文件
│   └── template/         # HTML 模板
├── utils/                # 工具模块
│   └── DBSchemaUtil.py   # 数据库 Schema 工具
├── db/                   # SQLite 数据库存储
├── main.py               # 项目入口
├── requirements.txt      # Python 依赖
├── Dockerfile           # Docker 构建文件
├── docker-compose.yml   # Docker Compose 配置
├── .env                 # 环境变量配置
└── DEPLOYMENT.md        # 部署文档
```

---

## 主要功能模块

### 1. Chat to SQL（智能数据分析）

- **自然语言转 SQL**：通过自然语言描述生成 MySQL 查询语句
- **大模型集成**：集成智谱 AI GLM-4.5 模型，智能理解查询意图
- **SQL 验证**：自动验证生成的 SQL 安全性，只允许 SELECT 查询
- **结果可视化**：支持表格形式展示查询结果

### 2. Schema 管理

- **DDL 解析**：上传或输入 DDL 语句，自动解析表结构信息
- **字段信息管理**：管理表名、字段名、类型、注释、主键等信息
- **CSV 导出**：支持导出 Schema 信息为 CSV 格式

### 3. 历史记录

- **查询历史**：保存所有查询记录，包含原始查询、生成的 SQL、验证结果
- **评分系统**：用户可以对生成的 SQL 进行评分（1-5 星）
- **参考学习**：历史成功查询可作为后续查询的参考

### 4. 补充知识

- **领域知识**：添加业务领域相关知识，帮助大模型理解业务逻辑
- **字段示例值**：提供字段的常见值，帮助生成更准确的 WHERE 条件
- **表间关系**：描述表之间的关联关系，帮助优化 JOIN 操作

### 5. 用户认证

- **JWT Token 认证**：基于 Token 的用户认证
- **角色权限**：支持管理员和普通用户角色
- **自动登录校验**：前端自动校验 Token 有效性

---

## 运行说明

### 1. 环境要求

- Python 3.12+
- SQLite
- 网络访问（用于调用智谱 AI API）

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置环境变量

编辑 `.env` 文件，设置以下环境变量：

```env
# 智谱AI API密钥（必需）
ZHIPU_API_KEY=your_api_key

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

### 5. 默认管理员账号

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

---

## 技术栈

- **后端**：FastAPI + SQLAlchemy + SQLite
- **大模型**：智谱 AI GLM-4.5
- **前端**：HTML + JavaScript + Bootstrap 5
- **部署**：Docker + Docker Compose

---

## 性能优化建议

1. **缓存优化**：项目已实现 SQL 验证结果缓存
2. **数据库**：生产环境可考虑使用 PostgreSQL 替代 SQLite
3. **限流**：已集成 SlowAPI 限流功能
4. **日志**：分离应用日志和 SQL 日志

---

## 扩展开发

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

- 初始版本
- 支持自然语言转 SQL
- 支持 Schema 管理
- 支持历史记录和评分
- 支持补充知识功能
- 支持 Docker 部署
