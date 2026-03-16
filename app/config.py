# -*- coding: UTF-8 -*-
"""
配置模块 - 集中管理所有配置变量
"""
import os
from datetime import timedelta
from app.utils import (
    _load_env_file,
    get_app_db_path,
    get_history_db_path,
    get_schema_db_path,
    get_extra_db_path,
    get_zhipu_api_key,
    get_temp_db_path,
    get_llm_db_path
)

_load_env_file()

SECRET_KEY = os.getenv('SECRET_KEY', 'your-secret-key-here')
ALGORITHM = os.getenv('ALGORITHM', 'HS256')
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv('ACCESS_TOKEN_EXPIRE_MINUTES', '1440'))

APP_DB_PATH = get_app_db_path()
HISTORY_DB_PATH = get_history_db_path()
SCHEMA_DB_PATH = get_schema_db_path()
EXTRA_DB_PATH = get_extra_db_path()
TEMP_DB_PATH = get_temp_db_path()
LLM_DB_PATH = get_llm_db_path()
ZHIPU_API_KEY = get_zhipu_api_key()
