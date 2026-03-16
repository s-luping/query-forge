# QueryForge 项目部署文档

## 项目概述
QueryForge 是一款基于自然语言的数据查询工具，通过大模型技术将自然语言转换为 SQL 查询语句，支持多种主流大模型、Schema 管理、表数据管理、SQL 生成与查询等功能。

## 部署前准备

### 环境要求
- Docker 和 Docker Compose 已安装
- 服务器具有网络访问权限（用于连接大模型 API）
- 至少 1GB 内存
- 至少 10GB 磁盘空间

### 所需文件
- `Dockerfile` - 用于构建 Docker 镜像
- `docker-compose.yml` - 用于定义和运行 Docker 服务
- `.env` - 环境变量配置文件

## 部署步骤

### 1. 克隆项目
```bash
git clone <项目仓库地址>
cd QueryForge
```

### 2. 配置环境变量
编辑 `.env` 文件，设置以下环境变量：

```env
# TOKEN 配置
SECRET_KEY=your_secret_key
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

### 3. 构建和启动服务
```bash
docker-compose up -d
```

### 4. 验证部署
打开浏览器，访问 `http://服务器IP:8188`，应该能看到登录页面。

默认管理员账号：
- 用户名：admin
- 密码：MyAdmin123

### 5. 配置大模型
登录系统后，需要在前端配置大模型 API：

1. 点击左侧菜单「大模型管理」→「模型配置管理」
2. 选择模型提供商（GLM/Qwen/DeepSeek/Doubao/OpenAI）
3. 输入 API 密钥和模型名称
4. 可配置参数：Max Tokens、Temperature、Timeout
5. 点击「测试连接」验证配置
6. 保存配置并设为默认

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
- 查看调用记录了解详细错误信息

### 3. 数据库连接失败
- 确保 `db` 目录具有正确的权限
- 检查 Docker 卷是否正确挂载

### 4. 登录失败
- 检查默认管理员账号是否已创建：`docker-compose logs | grep "默认管理员用户创建成功"`
- 确保 `SECRET_KEY` 已正确配置

## 性能优化

### 1. 增加内存
- 如果服务运行缓慢，考虑增加服务器内存

### 2. 优化数据库
- 定期清理历史数据
- 考虑使用更强大的数据库系统（如 PostgreSQL）

### 3. 配置负载均衡
- 如果需要处理大量请求，考虑配置负载均衡

## 安全建议

### 1. 更改默认密码
- 登录后立即更改默认管理员密码

### 2. 配置 HTTPS
- 在生产环境中配置 HTTPS 以加密传输

### 3. 限制访问
- 使用防火墙限制只允许特定 IP 访问

### 4. 定期备份
- 定期备份 `db` 目录以防止数据丢失

## 数据库说明

项目使用多个 SQLite 数据库分离存储不同类型的数据：

| 数据库 | 说明 |
|--------|------|
| sys_app.db | 用户数据、LLM配置 |
| sys_history.db | SQL生成历史记录 |
| sys_schema.db | Schema数据 |
| sys_extra.db | 补充知识数据 |
| sys_llm.db | LLM调用记录 |

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

## 联系方式

如果遇到问题，请联系项目维护者。
