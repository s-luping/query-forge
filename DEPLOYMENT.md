# QueryForge 部署文档（本地 venv 部署，不使用 Docker）

## 项目概述

QueryForge 是一款基于自然语言的数据查询工具，通过大模型技术将自然语言转换为 SQL 查询语句。
支持所有 OpenAI 兼容 API 的大模型、Schema 管理（规范 CSV/JSON 导入）、SQL 生成与多轮对话、
元数据同步、权限管理（数据源→库→表→字段四层）与安全审计等功能。

### 技术亮点

- **智能 SQL 生成**：字段级索引 + 按表聚合的 RAG 方案
- **灵活模型配置**：支持所有 OpenAI 兼容 API，前端自由配置供应商和模型
- **多轮对话**：支持连续对话式 SQL 生成
- **高性能向量存储**：纯 Python 实现，基于 BGE-M3 embedding 模型
- **多数据库支持**：MySQL、PostgreSQL、SQLite 等（元数据同步）；结构导入支持规范 CSV/JSON

## 部署前准备

### 环境要求

- Windows 10+ 或 Linux
- Python **3.10.x**（项目 venv 使用；系统 Python 若为其他版本请勿混用）
- 至少 2GB 内存（推荐 4GB，用于加载 embedding 模型）
- 至少 10GB 磁盘空间（包含模型存储）

### 所需文件

- `requirements.txt` — Python 依赖
- `start_server.bat` — Windows 启动脚本
- `download_model.py` — 向量模型下载脚本（可选）

## 部署步骤

### 1. 克隆项目

```bash
git clone <项目仓库地址>
cd QueryForge
```

### 2. 创建虚拟环境并安装依赖

```bash
# Windows
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# Linux
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 3. 配置环境变量（安全必填）

编辑 `.env` 或设置系统环境变量（推荐 `.env`，应用启动时自动加载）：

```env
# JWT 签名密钥（必填；两处都没有时应用拒绝启动）
QUERYFORGE_SECRET_KEY=your_secret_key_here
# 数据源密码加密密钥（可选，缺省从 SECRET_KEY 派生）
QUERYFORGE_FERNET_KEY=
# 数据库路径（默认即可）
QUERYFORGE_MAIN_DB=db/queryforge.db
QUERYFORGE_TELEMETRY_DB=db/llm_telemetry.db
# iframe 嵌入白名单（默认仅同源；需被外部页面嵌入时配置，见 FAQ）
QUERYFORGE_FRAME_ANCESTORS=
```

### 4. 下载向量模型（推荐）

```bash
python download_model.py
```

模型下载到 `models/embeddings/bge-m3` 目录，约 2GB。

### 5. 启动服务

```bash
# Windows
start_server.bat
# 或前台运行
.venv\Scripts\python.exe main.py

# Linux
.venv/bin/python main.py
```

服务监听 `0.0.0.0:8188`，日志统一写入 `logs/` 目录（app/server/sqlalchemy 等，自动轮转）。

### 6. 验证部署

打开浏览器访问 `http://服务器IP:8188`，应看到登录页面。

默认管理员账号：
- 用户名：admin
- 密码：REDACTED（登录后请立即修改，或在用户管理中重置）

### 7. 配置大模型

1. 登录后进入「模型管理 → 模型配置」
2. 输入模型供应商名称、模型名称（如 gpt-4、deepseek-chat）、API 密钥
3. 填写 API 地址（OpenAI 兼容端点）、可配置 Max Tokens / Temperature / Timeout
4. 点击「测试连接」，保存并设为默认

### 8. 导入数据库结构（规范 CSV / JSON）

数据浏览页提供「模板下载 / CSV 上传」，仅支持规范格式：

- **CSV**：表头必须含 `表名`、`字段名`，支持 `库名/字段类型/字段描述/表描述/可空/默认值/键类型/外键/示例值`
- **JSON**：Spider 数据集格式或自定义格式
- 上传时必须选择**数据源**与**数据库类型**（均必填）

## 启动和停止服务

### 启动

```bash
start_server.bat
```

### 停止

在运行服务的终端按 `Ctrl+C`；后台运行时结束对应 Python 进程即可。

### 查看日志

```bash
# 应用日志（请求、认证、业务）
tail -f logs/app.log
# 服务日志（uvicorn 启动/访问，按天轮转保留30天）
tail -f logs/server.log
# 审计日志（写操作、权限变更）
tail -f logs/audit.log
# SQL 异常日志（WARNING 以上）
tail -f logs/sqlalchemy.log
```

## 常见问题和解决方案

### 1. 服务无法启动

- 检查端口 8188 是否被占用：`netstat -ano | findstr 8188`
- 确认使用了项目 venv 的 Python（`.venv\Scripts\python.exe`），系统 Python 的 SQLAlchemy 版本可能不兼容
- 确认 `QUERYFORGE_SECRET_KEY` 已配置（缺失会拒绝启动）
- 查看 `logs/server.log` 获取错误详情

### 2. 大模型 API 调用失败

- 检查前端配置的 API 密钥是否正确
- 检查服务器是否可以访问大模型 API 地址
- 查看 `logs/llm.log` 了解调用详情

### 3. 向量索引构建失败

- 确保已下载 BGE-M3 模型：`python download_model.py`
- 检查 `models/embeddings/bge-m3` 目录是否存在
- 查看 `logs/pipeline.log`

### 4. 数据库连接失败（元数据同步）

- 在「数据源管理」中测试连接；缺驱动时到「驱动管理」一键安装（MySQL→pymysql、PostgreSQL→psycopg2）
- 确认目标库账号为只读且有查询权限
- 查看 `logs/app.log` 中的同步错误

### 5. 登录失败

- 检查默认管理员账号是否创建成功
- 确认 `QUERYFORGE_SECRET_KEY` 已正确配置
- 注册功能默认关闭（ALLOW_REGISTER=false），账号由管理员在「用户管理」中创建

### 6. 将系统嵌入到其他页面（iframe）

默认只允许**同源** iframe 嵌入。如需放行外部来源，设置环境变量：

```env
QUERYFORGE_FRAME_ANCESTORS=http://127.0.0.1:3000,http://portal.example.com
```

- 重启服务后生效；允许任意站点可设为 `*`（不推荐）
- 若控制台仍提示旧 `frame-ancestors 'none'`，强制刷新（Ctrl+F5）清缓存

## 数据与备份

- 主库 `db/queryforge.db`（用户/配置/Schema/知识/对话/统计/设置）
- 遥测库 `db/llm_telemetry.db`（LLM 调用明细）
- 定期备份：直接复制上述两个文件即可（建议先停止服务再复制）

## 安全建议

1. **更改默认密码**：登录后立即修改 admin 密码
2. **配置 HTTPS**：生产环境在 Nginx 反向代理配置 SSL
3. **限制访问**：防火墙仅允许特定 IP 访问 8188
4. **定期备份**：备份 `db/` 目录
5. **禁用注册**：系统设置中 `ALLOW_REGISTER` 保持关闭，账号统一由管理员创建
