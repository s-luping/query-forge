# QueryForge 项目部署文档

## 项目概述

QueryForge 是一款基于自然语言的数据查询工具，通过大模型技术将自然语言转换为 SQL 查询语句。支持多种主流大模型（GLM、Qwen、DeepSeek、Doubao、OpenAI）、Schema 管理、表数据管理、SQL 生成与查询等功能。

### 技术亮点

- **智能 SQL 生成**：字段级索引 + 按表聚合的 RAG 方案，兼顾精确检索与上下文完整性
- **多模型支持**：支持 5 种主流大模型，前端灵活配置
- **高性能向量存储**：纯 Python 实现，基于 BGE-M3 embedding 模型
- **多数据库解析**：支持 MySQL、PostgreSQL、Oracle、SQL Server、Hive、Doris、ClickHouse 等 DDL 解析

## 部署前准备

### 环境要求

- Docker 和 Docker Compose 已安装
- 服务器具有网络访问权限（用于连接大模型 API）
- 至少 2GB 内存（推荐 4GB，用于加载 embedding 模型）
- 至少 10GB 磁盘空间（包含模型存储）

### 所需文件

- `Dockerfile` - 用于构建 Docker 镜像
- `docker-compose.yml` - 用于定义和运行 Docker 服务
- `.env` - 环境变量配置文件（可选，主要配置在前端完成）

## 部署步骤

### 1. 克隆项目

```bash
git clone <项目仓库地址>
cd QueryForge
```

### 2. 配置环境变量（可选）

编辑 `.env` 文件，设置以下环境变量：

```env
# TOKEN 配置
SECRET_KEY=your_secret_key_here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# 数据库路径配置（默认值即可）
APP_DB_PATH=db/sys_app.db
HISTORY_DB_PATH=db/sys_history.db
SCHEMA_DB_PATH=db/sys_schema.db
EXTRA_DB_PATH=db/sys_extra.db
TEMP_DB_PATH=db/temp/
LLM_DB_PATH=db/sys_llm.db
```

### 3. 下载向量模型（推荐）

首次部署前建议下载 BGE-M3 embedding 模型：

```bash
python download_model.py
```

模型将下载到 `models/embeddings/bge-m3` 目录，约 2GB。

### 4. 构建和启动服务

```bash
docker-compose up -d
```

### 5. 验证部署

打开浏览器，访问 `http://服务器IP:8188`，应该能看到登录页面。

默认管理员账号：
- 用户名：admin
- 密码：REDACTED

### 6. 配置大模型

登录系统后，需要在前端配置大模型 API：

1. 点击左侧菜单「大模型管理」→「模型配置管理」
2. 选择模型提供商（GLM/Qwen/DeepSeek/Doubao/OpenAI）
3. 输入 API 密钥和模型名称（可自定义输入）
4. 可配置参数：Max Tokens、Temperature、Timeout
5. 点击「测试连接」验证配置
6. 保存配置并设为默认

### 7. 配置 Schema

1. 进入「Schema 管理」页面
2. 选择输入方式：
   - **DDL 文本**：输入 CREATE TABLE 语句
   - **JSON 文本**：输入 Spider 格式或自定义格式 JSON
   - **文件上传**：上传 .sql 或 .json 文件
3. 选择数据库类型或自动检测
4. Schema 名称可选（留空则自动从内容中提取）
5. 点击解析，系统自动提取表结构信息

## 启动和停止服务

### 启动服务

```bash
docker-compose up -d
```

### 停止服务

```bash
docker-compose down
```

### 查看服务状态

```bash
docker-compose ps
```

### 查看服务日志

```bash
docker-compose logs -f
```

## 常见问题和解决方案

### 1. 服务无法启动

- 检查 Docker 和 Docker Compose 是否已正确安装
- 检查端口 8188 是否已被占用
- 查看日志以获取详细错误信息：`docker-compose logs -f`

### 2. 大模型 API 调用失败

- 检查前端配置的 API 密钥是否正确
- 检查服务器是否可以访问大模型 API 地址
- 查看 LLM 调用记录了解详细错误信息

### 3. 向量索引构建失败

- 确保已下载 BGE-M3 模型：`python download_model.py`
- 检查 `models/embeddings/bge-m3` 目录是否存在
- 查看日志：`tail -f logs/pipeline.log`

### 4. 数据库连接失败

- 确保 `db` 目录具有正确的权限
- 检查 Docker 卷是否正确挂载

### 5. 登录失败

- 检查默认管理员账号是否已创建：`docker-compose logs | grep "默认管理员用户创建成功"`
- 确保 `SECRET_KEY` 已正确配置

### 6. Schema 解析失败

- 检查 DDL 语句格式是否正确
- 尝试选择正确的数据库类型
- 查看 `logs/app.log` 获取详细错误信息

### 7. SQL 生成问题

- 查看 `logs/pipeline.log` 了解生成过程
- 查看 `logs/llm.log` 了解大模型调用详情
- 检查 Schema 是否正确配置

## 性能优化

### 1. 内存优化

- 如果服务运行缓慢，考虑增加服务器内存
- embedding 模型加载需要约 1-2GB 内存

### 2. 向量索引优化

- 字段数量 >= 50 时自动构建向量索引
- 索引存储在 `db/vectors/` 目录
- 可手动触发索引构建：进入 Schema 管理 → 点击「构建索引」

### 3. 数据库优化

- 定期清理历史数据
- 生产环境可考虑使用 PostgreSQL 替代 SQLite

### 4. 限流配置

项目已集成 SlowAPI 限流功能，可在 `app/limiter.py` 中调整限流参数。

## 安全建议

### 1. 更改默认密码

- 登录后立即更改默认管理员密码

### 2. 配置 HTTPS

- 在生产环境中配置 HTTPS 以加密传输
- 可使用 Nginx 反向代理配置 SSL

### 3. 限制访问

- 使用防火墙限制只允许特定 IP 访问
- 修改 `docker-compose.yml` 中的端口映射

### 4. 定期备份

- 定期备份 `db` 目录以防止数据丢失
- 备份命令：`tar -czvf queryforge_backup.tar.gz db/`

## 数据库说明

项目使用多个 SQLite 数据库分离存储不同类型的数据：

| 数据库 | 说明 |
|--------|------|
| sys_app.db | 用户数据、LLM配置 |
| sys_history.db | SQL生成历史记录 |
| sys_schema.db | Schema数据 |
| sys_extra.db | 补充知识数据 |
| sys_llm.db | LLM调用记录 |

向量索引存储在 `db/vectors/` 目录。

## 日志系统

项目采用日志分离策略，不同类型的日志记录到独立文件：

| 日志文件 | 说明 |
|---------|------|
| app.log | 应用日志（API请求、认证、业务操作） |
| sqlalchemy.log | 数据库查询日志（SQL执行记录） |
| llm.log | 大模型请求日志（LLM API调用详情、Token消耗） |
| pipeline.log | SQL生成过程日志（关键词提取、向量召回、表聚合、验证） |

### 日志查看命令

```bash
# 应用日志（API请求、登录、业务操作）
tail -f logs/app.log

# 数据库查询日志（SQL执行记录）
tail -f logs/sqlalchemy.log

# LLM 调用日志（大模型请求详情）
tail -f logs/llm.log

# Pipeline 日志（SQL生成过程）
tail -f logs/pipeline.log
```

### 日志排查建议

- **API 问题**：查看 `app.log`，包含请求路径、状态码、响应时间
- **数据库问题**：查看 `sqlalchemy.log`，包含所有 SQL 执行记录
- **LLM 问题**：查看 `llm.log`，包含请求模型、发送内容、响应、Token消耗
- **SQL生成问题**：查看 `pipeline.log`，包含关键词提取、向量召回、表聚合、验证结果

## 更新项目

### 1. 拉取最新代码

```bash
git pull
```

### 2. 重新构建和启动服务

```bash
docker-compose down
docker-compose up -d --build
```

### 3. 更新向量模型（如有更新）

```bash
python download_model.py
```

## 功能使用指南

### 1. 多数据库 DDL 解析

支持以下数据库类型的 DDL 解析：
- MySQL / MariaDB
- PostgreSQL
- Oracle
- SQL Server
- SQLite
- Hive
- Doris
- ClickHouse

**多数据库支持**：
- DDL 中包含 `CREATE DATABASE` 或 `USE` 语句时，自动提取数据库名
- JSON 中包含 `db_id` 或 `schema_name` 时，自动提取数据库名

### 2. JSON 格式解析

支持两种 JSON 格式：

**Spider 数据集格式**：
```json
{
  "db_id": "database_name",
  "table_names_original": ["table1", "table2"],
  "column_names_original": [[-1, "*"], [0, "id"], [0, "name"]],
  "column_types": ["text", "integer", "text"],
  "primary_keys": [1]
}
```

**自定义格式**：
```json
{
  "schema_name": "database_name",
  "tables": [
    {
      "name": "table1",
      "columns": [
        {"name": "id", "type": "INTEGER", "comment": "主键"}
      ]
    }
  ]
}
```

### 3. SQL 生成流程

1. 进入「生成 SQL 与查询」页面
2. 选择 Schema（必选）
3. 输入自然语言问题
4. 点击「生成 SQL」
5. 查看生成的 SQL 并执行查询

**补充知识**：
- 点击右上角「补充知识」按钮
- 可添加字段示例值、表间关系、领域知识
- 帮助大模型生成更准确的 SQL

## 联系方式

如果遇到问题，请联系项目维护者。
