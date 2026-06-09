"""配置模块 — 数据库路径"""
from app.utils import (
    _load_env_file,
    get_app_db_path,
    get_schema_db_path,
    get_extra_db_path,
    get_llm_db_path,
    get_conversation_db_path
)

_load_env_file()

APP_DB_PATH = get_app_db_path()
SCHEMA_DB_PATH = get_schema_db_path()
EXTRA_DB_PATH = get_extra_db_path()
LLM_DB_PATH = get_llm_db_path()
CONVERSATION_DB_PATH = get_conversation_db_path()
