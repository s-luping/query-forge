# -*- coding: UTF-8 -*-
import logging
from logging.handlers import RotatingFileHandler
import os

LOG_DIR = "logs"
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s -%(module)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S %p",
    level=logging.INFO,
)

logger = logging.getLogger("app_logger")
logger.setLevel(logging.DEBUG)

console_handler = logging.StreamHandler()
file_handler = RotatingFileHandler(
    os.path.join(LOG_DIR, "app.log"),
    maxBytes=1024*1024*1024,
    encoding="utf-8",
)

formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s -%(module)s: %(message)s"
)
console_handler.setFormatter(formatter)
file_handler.setFormatter(formatter)

logger.addHandler(file_handler)

llm_logger = logging.getLogger("llm_logger")
llm_logger.setLevel(logging.DEBUG)
llm_file_handler = RotatingFileHandler(
    os.path.join(LOG_DIR, "llm.log"),
    maxBytes=1024*1024*1024,
    encoding="utf-8",
)
llm_formatter = logging.Formatter(
    "%(asctime)s - %(levelname)s\n%(message)s\n" + "="*80
)
llm_file_handler.setFormatter(llm_formatter)
llm_logger.addHandler(llm_file_handler)

db_logger = logging.getLogger("sqlalchemy_logger")
db_logger.setLevel(logging.DEBUG)
db_file_handler = RotatingFileHandler(
    os.path.join(LOG_DIR, "sqlalchemy.log"),
    maxBytes=1024*1024*1024,
    encoding="utf-8",
)
db_formatter = logging.Formatter(
    "%(asctime)s - %(levelname)s - %(message)s"
)
db_file_handler.setFormatter(db_formatter)
db_logger.addHandler(db_file_handler)

logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
logging.getLogger('sqlalchemy.engine').addHandler(db_file_handler)
