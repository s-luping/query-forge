# 使用Python 3.12作为基础镜像
FROM python:3.12-slim

# 设置工作目录
WORKDIR /app

# 复制项目文件
COPY . /app

# 安装依赖
RUN pip install --no-cache-dir -r requirements.txt

# 创建数据库目录
RUN mkdir -p db/temp

# 暴露端口
EXPOSE 8188

# 启动应用
CMD ["python", "main.py"]