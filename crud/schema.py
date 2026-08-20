# -*- coding: UTF-8 -*-
"""crud.schema — Schema 三层（库/表/字段）数据访问

复杂平铺/召回查询见 services/schema/service.py；本模块提供基础 CRUD。
"""
from typing import List, Optional

from crud.base import BaseCrud, session_scope
from models.schema import DbSchema, DbTable, DbColumn


class SchemaCrud(BaseCrud):
    model = DbSchema

    def get_by_name(self, name: str) -> Optional[DbSchema]:
        return self.get_one(name=name)

    def list_visible(self, visible_schema_ids: List[int]) -> List[DbSchema]:
        """按可见 ID 列表查询（空列表返回空）"""
        if not visible_schema_ids:
            return []
        with session_scope() as db:
            return db.query(DbSchema).filter(DbSchema.id.in_(visible_schema_ids)).all()

    def list_names(self) -> List[str]:
        with session_scope() as db:
            return [r[0] for r in db.query(DbSchema.name).order_by(DbSchema.name).all()]

    def name_map(self) -> dict:
        """id → name 映射（一次查询供多处使用）"""
        with session_scope() as db:
            return dict(db.query(DbSchema.id, DbSchema.name).all())

    def get_type_by_name(self, name: str) -> Optional[str]:
        with session_scope() as db:
            row = db.query(DbSchema.db_type).filter(DbSchema.name == name).first()
            return row[0] if row else None

    def get_id_by_name(self, name: Optional[str]) -> Optional[int]:
        if not name:
            return None
        with session_scope() as db:
            row = db.query(DbSchema.id).filter(DbSchema.name == name).first()
            return row[0] if row else None

    def get_name_by_id(self, schema_id: Optional[int]) -> Optional[str]:
        if not schema_id:
            return None
        with session_scope() as db:
            row = db.query(DbSchema.name).filter(DbSchema.id == schema_id).first()
            return row[0] if row else None


class TableCrud(BaseCrud):
    model = DbTable

    def list_by_schema(self, schema_id: int) -> List[DbTable]:
        return self.list(schema_id=schema_id, order_by='name')

    def get_by_schema_and_name(self, schema_id: int, name: str) -> Optional[DbTable]:
        return self.get_one(schema_id=schema_id, name=name)


class ColumnCrud(BaseCrud):
    model = DbColumn

    def list_by_table(self, table_id: int) -> List[DbColumn]:
        return self.list(table_id=table_id, order_by='ordinal')

    def list_by_tables(self, table_ids: List[int]) -> List[DbColumn]:
        if not table_ids:
            return []
        with session_scope() as db:
            return (db.query(DbColumn)
                    .filter(DbColumn.table_id.in_(table_ids))
                    .order_by(DbColumn.ordinal).all())

    def get_by_table_and_name(self, table_id: int, name: str) -> Optional[DbColumn]:
        return self.get_one(table_id=table_id, name=name)


schema_crud = SchemaCrud()
table_crud = TableCrud()
column_crud = ColumnCrud()
