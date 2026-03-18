# -*- coding: UTF-8 -*-
"""
日志系统配置

日志文件分离说明：
- app.log: 应用日志（API请求、认证、业务操作等）
- sqlalchemy.log: 数据库查询日志（SQL执行记录）
- llm.log: 大模型请求日志（LLM API调用详情）
- pipeline.log: SQL生成过程日志（关键词提取、向量召回、表聚合等）
"""
import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR = "logs"
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)


def _create_logger(
    name: str,
    filename: str,
    level: int = logging.INFO,
    fmt: str = "%(asctime)s - %(levelname)s - %(message)s",
    max_bytes: int = 1024 * 1024 * 1024,
    add_console: bool = True
) -> logging.Logger:
    """创建独立的日志记录器"""
    log_logger = logging.getLogger(name)
    log_logger.setLevel(level)
    log_logger.propagate = False

    file_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, filename),
        maxBytes=max_bytes,
        encoding="utf-8",
    )
    formatter = logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S %p")
    file_handler.setFormatter(formatter)
    log_logger.addHandler(file_handler)

    if add_console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        log_logger.addHandler(console_handler)

    return log_logger


logger = _create_logger(
    name="app",
    filename="app.log",
    level=logging.INFO,
    fmt="%(asctime)s - %(levelname)s -%(module)s: %(message)s",
    add_console=True
)

llm_logger = _create_logger(
    name="llm",
    filename="llm.log",
    level=logging.DEBUG,
    fmt="%(asctime)s - %(levelname)s\n%(message)s\n" + "=" * 80,
    add_console=False
)

pipeline_logger = _create_logger(
    name="pipeline",
    filename="pipeline.log",
    level=logging.DEBUG,
    fmt="%(asctime)s\n%(message)s\n" + "=" * 80,
    add_console=False
)

sqlalchemy_logger = _create_logger(
    name="sqlalchemy.engine",
    filename="sqlalchemy.log",
    level=logging.INFO,
    fmt="%(asctime)s - %(message)s",
    add_console=False
)
