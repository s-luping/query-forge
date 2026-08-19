# -*- coding: UTF-8 -*-
"""PostgreSQL 连接器 — 读取 information_schema + pg_catalog

PostgreSQL 的注释存储在 pg_description 中，
通过 col_description() / obj_description() 函数读取。
"""
from typing import List, Optional
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.engine import Engine

from services.sync.connectors.base import BaseConnector, TableMetadata, ColumnMetadata


class PostgreSQLConnector(BaseConnector):
    """PostgreSQL 元数据读取"""

    def _build_engine(self) -> Engine:
        url = URL.create(
            'postgresql+psycopg2',
            username=self.username,
            password=self.password,
            host=self.host,
            port=self.port,
            database=self.database,
        )
        return create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=3)

    def read_metadata(self, include_tables: Optional[List[str]] = None,
                      exclude_tables: Optional[List[str]] = None) -> List[TableMetadata]:
        engine = self._get_engine()
        # 用 information_schema 查基础信息，pg_catalog 补注释
        sql = text("""
            SELECT
                c.table_name,
                '' AS table_comment,
                c.column_name,
                c.data_type,
                '' AS column_comment,
                (c.is_nullable = 'YES') AS is_nullable,
                c.column_default,
                '' AS column_key,
                c.ordinal_position
            FROM information_schema.columns c
            JOIN information_schema.tables t
                ON c.table_schema = t.table_schema
                AND c.table_name = t.table_name
            WHERE c.table_schema = :schema_name
                AND t.table_type = 'BASE TABLE'
            ORDER BY c.table_name, c.ordinal_position
        """)

        pk_sql = text("""
            SELECT kcu.table_name, kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'PRIMARY KEY'
                AND tc.table_schema = :schema_name
        """)

        comment_sql = text("""
            SELECT
                c.relname AS table_name,
                obj_description(c.oid) AS table_comment,
                a.attname AS column_name,
                col_description(c.oid, a.attnum) AS column_comment
            FROM pg_class c
            JOIN pg_namespace n ON c.relnamespace = n.oid
            JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
            WHERE n.nspname = :schema_name AND c.relkind = 'r'
        """)

        schema = self.database or 'public'

        with engine.connect() as conn:
            rows = conn.execute(sql, {"schema_name": schema}).fetchall()
            pk_rows = conn.execute(pk_sql, {"schema_name": schema}).fetchall()
            comment_rows = conn.execute(comment_sql, {"schema_name": schema}).fetchall()

        # 构建 PK 集合
        pk_map: dict[str, set[str]] = {}
        for r in pk_rows:
            pk_map.setdefault(r[0], set()).add(r[1])

        # 构建注释映射 {(table, column): comment} + {table: table_comment}
        col_comments: dict[tuple[str, str], str] = {}
        table_comments: dict[str, str] = {}
        for r in comment_rows:
            table_comments[r[0]] = r[1] or ''
            if r[2] and r[3]:
                col_comments[(r[0], r[2])] = r[3]

        # 组装 TableMetadata
        tables_dict: dict[str, TableMetadata] = {}
        for r in rows:
            table_name = r[0]
            if not self._should_include(table_name, include_tables, exclude_tables):
                continue

            if table_name not in tables_dict:
                tables_dict[table_name] = TableMetadata(
                    name=table_name,
                    description=table_comments.get(table_name, '')
                )

            col_name = r[2]
            col = ColumnMetadata(
                name=col_name,
                data_type=r[3] or '',
                description=col_comments.get((table_name, col_name), ''),
                is_nullable=bool(r[5]),
                default_value=str(r[6]) if r[6] is not None else '',
                column_key='PRI' if col_name in pk_map.get(table_name, set()) else '',
                ordinal=r[8] or 0,
            )
            tables_dict[table_name].columns.append(col)

        return list(tables_dict.values())
