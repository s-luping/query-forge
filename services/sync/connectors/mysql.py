# -*- coding: UTF-8 -*-
"""MySQL 连接器 — 读取 information_schema

安全要求：
    同步账号只需 SELECT on information_schema 的权限，
    不需要访问业务数据的权限。
"""
from typing import List, Optional
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.engine import Engine

from services.sync.connectors.base import BaseConnector, TableMetadata, ColumnMetadata


class MySQLConnector(BaseConnector):
    """MySQL / MariaDB 元数据读取"""

    def _build_engine(self) -> Engine:
        url = URL.create(
            'mysql+pymysql',
            username=self.username,
            password=self.password,
            host=self.host,
            port=self.port,
            database=self.database,
            query={'charset': 'utf8mb4'},
        )
        return create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=3)

    def read_metadata(self, include_tables: Optional[List[str]] = None,
                      exclude_tables: Optional[List[str]] = None) -> List[TableMetadata]:
        engine = self._get_engine()
        sql = text("""
            SELECT
                t.TABLE_NAME,
                t.TABLE_COMMENT,
                c.COLUMN_NAME,
                c.COLUMN_TYPE,
                c.COLUMN_COMMENT,
                c.IS_NULLABLE,
                c.COLUMN_DEFAULT,
                c.COLUMN_KEY,
                c.ORDINAL_POSITION,
                fk.REFERENCED_TABLE_NAME,
                fk.REFERENCED_COLUMN_NAME
            FROM information_schema.TABLES t
            JOIN information_schema.COLUMNS c
                ON t.TABLE_SCHEMA = c.TABLE_SCHEMA
                AND t.TABLE_NAME = c.TABLE_NAME
            LEFT JOIN information_schema.KEY_COLUMN_USAGE fk
                ON c.TABLE_SCHEMA = fk.TABLE_SCHEMA
                AND c.TABLE_NAME = fk.TABLE_NAME
                AND c.COLUMN_NAME = fk.COLUMN_NAME
                AND fk.REFERENCED_TABLE_NAME IS NOT NULL
            WHERE t.TABLE_SCHEMA = :db_name
                AND t.TABLE_TYPE = 'BASE TABLE'
            ORDER BY t.TABLE_NAME, c.ORDINAL_POSITION
        """)

        tables_dict: dict[str, TableMetadata] = {}

        with engine.connect() as conn:
            rows = conn.execute(sql, {"db_name": self.database}).fetchall()

        for r in rows:
            table_name = r[0]
            if not self._should_include(table_name, include_tables, exclude_tables):
                continue

            if table_name not in tables_dict:
                tables_dict[table_name] = TableMetadata(
                    name=table_name,
                    description=r[1] or ''
                )

            col = ColumnMetadata(
                name=r[2],
                data_type=r[3] or '',
                description=r[4] or '',
                is_nullable=(r[5] != 'NO'),
                default_value=str(r[6]) if r[6] is not None else '',
                column_key=r[7] or '',
                ordinal=r[8] or 0,
            )

            # 外键引用
            if r[9] and r[10]:
                col.foreign_key = f"{r[9]}.{r[10]}"

            tables_dict[table_name].columns.append(col)

        return list(tables_dict.values())
