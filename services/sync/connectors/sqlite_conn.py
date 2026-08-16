# -*- coding: UTF-8 -*-
"""SQLite 连接器 — 读取 sqlite_master + PRAGMA table_info

SQLite 的元数据相对简单：
    - 表注释不存在（SQLite 不支持原生表/列注释）
    - 主键通过 PRAGMA table_info 的 pk 字段获取
    - 外键通过 PRAGMA foreign_key_list 获取
"""
from typing import List, Optional
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from services.sync.connectors.base import BaseConnector, TableMetadata, ColumnMetadata


class SQLiteConnector(BaseConnector):
    """SQLite 元数据读取"""

    def _build_engine(self) -> Engine:
        # database 字段作为文件路径
        db_path = self.database or ':memory:'
        url = f"sqlite:///{db_path}"
        return create_engine(url, connect_args={'check_same_thread': False})

    def read_metadata(self, include_tables: Optional[List[str]] = None,
                      exclude_tables: Optional[List[str]] = None) -> List[TableMetadata]:
        engine = self._get_engine()

        tables: List[TableMetadata] = []

        with engine.connect() as conn:
            # 获取所有用户表
            rows = conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )).fetchall()

            for (table_name,) in rows:
                if not self._should_include(table_name, include_tables, exclude_tables):
                    continue

                # PRAGMA table_info 返回: cid, name, type, notnull, dflt_value, pk
                col_rows = conn.execute(
                    text(f"PRAGMA table_info('{table_name}')")
                ).fetchall()

                # PRAGMA foreign_key_list 返回: id, seq, table, from, to, ...
                fk_rows = conn.execute(
                    text(f"PRAGMA foreign_key_list('{table_name}')")
                ).fetchall()
                fk_map = {r[3]: f"{r[2]}.{r[4]}" for r in fk_rows}

                tm = TableMetadata(name=table_name)
                for cr in col_rows:
                    col_name = cr[1]
                    pk_val = cr[5]
                    tm.columns.append(ColumnMetadata(
                        name=col_name,
                        data_type=cr[2] or '',
                        description='',  # SQLite 无原生列注释
                        is_nullable=(pk_val == 0 and cr[3] == 0),  # pk 或 notnull=1 时不允许 NULL
                        default_value=str(cr[4]) if cr[4] is not None else '',
                        column_key='PRI' if pk_val > 0 else '',
                        foreign_key=fk_map.get(col_name, ''),
                        ordinal=cr[0] or 0,
                    ))
                tables.append(tm)

        return tables
