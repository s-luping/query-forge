# -*- coding: UTF-8 -*-
"""连接器基类 — 标准化元数据结构 + 连接管理

所有方言连接器继承此类，实现 read_metadata() 返回 TableMetadata 列表。
"""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from sqlalchemy import text
from sqlalchemy.engine import Engine


@dataclass
class ColumnMetadata:
    """字段元数据（标准化）"""
    name: str
    data_type: str = ''
    description: str = ''
    is_nullable: bool = True
    default_value: str = ''
    column_key: str = ''           # PRI / UNI / MUL
    foreign_key: str = ''           # table.column
    ordinal: int = 0


@dataclass
class TableMetadata:
    """表元数据（标准化）"""
    name: str
    description: str = ''
    columns: List[ColumnMetadata] = field(default_factory=list)


class BaseConnector:
    """连接器基类 — 子类实现 _build_engine() 和 read_metadata()"""

    def __init__(self, host: str = '', port: int = 0, database: str = '',
                 username: str = '', password: str = '', extra_params: str = '{}'):
        self.host = host
        self.port = port
        self.database = database
        self.username = username
        self.password = password
        self._engine: Optional[Engine] = None

    # ── 子类实现 ──────────────────────────────────────────────────

    def _build_engine(self) -> Engine:
        """构建 SQLAlchemy 引擎 — 子类提供 URL"""
        raise NotImplementedError

    def read_metadata(self, include_tables: Optional[List[str]] = None,
                      exclude_tables: Optional[List[str]] = None) -> List[TableMetadata]:
        """读取所有表和字段的元数据 — 子类实现"""
        raise NotImplementedError

    # ── 公共方法 ──────────────────────────────────────────────────

    def _get_engine(self) -> Engine:
        if self._engine is None:
            self._engine = self._build_engine()
        return self._engine

    def test_connection(self) -> Tuple[bool, str]:
        """测试连接，返回 (成功, 消息)"""
        try:
            engine = self._get_engine()
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True, "连接成功"
        except Exception as e:
            return False, str(e)

    def close(self):
        """关闭引擎"""
        if self._engine:
            self._engine.dispose()
            self._engine = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # ── 表名过滤 ──────────────────────────────────────────────────

    @staticmethod
    def _should_include(table_name: str,
                        include_tables: Optional[List[str]] = None,
                        exclude_tables: Optional[List[str]] = None) -> bool:
        if exclude_tables and table_name.lower() in [t.lower() for t in exclude_tables]:
            return False
        if include_tables and table_name.lower() not in [t.lower() for t in include_tables]:
            return False
        return True
