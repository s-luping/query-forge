# -*- coding: UTF-8 -*-
"""数据库连接器注册表 — 与 DDL 解析器的 PARSER_REGISTRY 模式一致

新增方言：
    1. 新建 connectors/<dialect>.py，实现 Connector 类
    2. 在下方 CONNECTOR_REGISTRY 注册一行
"""
from services.sync.connectors.base import BaseConnector, TableMetadata, ColumnMetadata
from services.sync.connectors import mysql, postgresql, sqlite_conn

# db_type → 连接器类
CONNECTOR_REGISTRY = {
    'mysql': mysql.MySQLConnector,
    'mariadb': mysql.MySQLConnector,
    'postgresql': postgresql.PostgreSQLConnector,
    'postgres': postgresql.PostgreSQLConnector,
    'sqlite': sqlite_conn.SQLiteConnector,
    'sqlite3': sqlite_conn.SQLiteConnector,
}


def get_connector(db_type: str, **conn_kwargs) -> BaseConnector:
    """获取连接器实例"""
    db_type = (db_type or 'mysql').lower()
    cls = CONNECTOR_REGISTRY.get(db_type)
    if cls is None:
        raise ValueError(f"不支持的数据库类型: {db_type}，支持: {list(CONNECTOR_REGISTRY.keys())}")
    return cls(**conn_kwargs)


__all__ = ['BaseConnector', 'TableMetadata', 'ColumnMetadata',
           'CONNECTOR_REGISTRY', 'get_connector']
