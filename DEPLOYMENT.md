# QueryForge 项目部署文档

## 项目概述
QueryForge 是一个智能数据分析平台，允许用户通过自然语言描述生成 SQL 查询并可视化数据。

## 部署前准备

### 环境要求
- Docker 和 Docker Compose 已安装
- 服务器具有网络访问权限（用于连接智谱AI API）
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
# 智谱AI API密钥
ZHIPU_API_KEY=your_zhipu_api_key

# TOKEN 配置
SECRET_KEY=your_secret_key
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# 数据库路径配置（默认值即可）
APP_DB_PATH=db/sys_app.db
HISTORY_DB_PATH=db/sys_history.db
SQL_DB_PATH=db/sys_sql.db
EXTRA_DB_PATH=db/sys_extra.db
TEMP_DB_PATH=db/temp/
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

### 2. 智谱AI API 调用失败
- 检查 `ZHIPU_API_KEY` 是否已正确配置
- 检查服务器是否可以访问智谱AI API 地址

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