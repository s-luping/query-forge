# -*- coding: UTF-8 -*-
"""
工具函数模块
"""
import os


def _load_env_file():
    """加载.env文件"""
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    if key and key not in os.environ:
                        os.environ[key] = value


def get_app_db_path() -> str:
    """获取应用数据库路径"""
    path = os.getenv('APP_DB_PATH', 'db/sys_app.db')
    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), path)
    return path


def get_history_db_path() -> str:
    """获取历史记录数据库路径"""
    path = os.getenv('HISTORY_DB_PATH', 'db/sys_history.db')
    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), path)
    return path


def get_sql_db_path() -> str:
    """获取SQL Schema数据库路径"""
    path = os.getenv('SQL_DB_PATH', 'db/sys_sql.db')
    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), path)
    return path


def get_extra_db_path() -> str:
    """获取补充知识数据库路径"""
    path = os.getenv('EXTRA_DB_PATH', 'db/sys_extra.db')
    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), path)
    return path


def get_zhipu_api_key() -> str:
    """获取智谱AI API密钥"""
    return os.getenv('ZHIPU_API_KEY', '')


def get_temp_db_path() -> str:
    """获取临时数据库目录路径"""
    path = os.getenv('TEMP_DB_PATH', 'db/temp/')
    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), path)
    path = os.path.normpath(path)
    if not path.endswith(os.sep):
        path = path + os.sep
    return path
