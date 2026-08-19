# -*- coding: UTF-8 -*-
"""
工具函数模块
"""
import os


def get_app_db_path() -> str:
    """获取应用数据库路径"""
    path = os.getenv('APP_DB_PATH', 'db/sys_app.db')
    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), path)
    return path


def get_schema_db_path() -> str:
    """获取模式数据库路径"""
    path = os.getenv('SCHEMA_DB_PATH', 'db/sys_schema.db')
    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), path)
    return path


def get_extra_db_path() -> str:
    """获取知识库数据库路径（旧版独立库，当前已并入主库）"""
    path = os.getenv('EXTRA_DB_PATH', 'db/sys_extra.db')
    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), path)
    return path


def get_llm_db_path() -> str:
    """获取LLM调用记录数据库路径"""
    path = os.getenv('LLM_DB_PATH', 'db/sys_llm.db')
    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), path)
    return path


def get_conversation_db_path() -> str:
    """获取对话记录数据库路径"""
    path = os.getenv('CONVERSATION_DB_PATH', 'db/sys_conversation.db')
    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), path)
    return path
