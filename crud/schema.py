# -*- coding: UTF-8 -*-
"""crud.schema — Schema 三层（库/表/字段）数据访问

复杂平铺/召回查询见 services/schema/service.py；本模块提供基础 CRUD。
"""
from typing import List, Optional

from crud.base import BaseCrud, session_scope
from models.schema import DbColumn, DbSchema, DbTable, DbTableRelation


class SchemaCrud(BaseCrud):
    model = DbSchema

    def get_by_name(self, name: str) -> Optional[DbSchema]:
        return self.get_one(name=name)

    def list_visible(self, visible_schema_ids: Optional[List[int]]) -> List[DbSchema]:
        """按可见 ID 列表查询；None=全部（管理员），空列表返回空"""
        with session_scope() as db:
            q = db.query(DbSchema)
            if visible_schema_ids is not None:
                if not visible_schema_ids:
                    return []
                q = q.filter(DbSchema.id.in_(visible_schema_ids))
            rows = q.all()
            for r in rows:
                db.expunge(r)
            return rows

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
            rows = (db.query(DbColumn)
                    .filter(DbColumn.table_id.in_(table_ids))
                    .order_by(DbColumn.ordinal).all())
            # expunge 后再返回，避免会话外访问过期属性触发 DetachedInstanceError
            for r in rows:
                db.expunge(r)
            return rows

    def get_by_table_and_name(self, table_id: int, name: str) -> Optional[DbColumn]:
        return self.get_one(table_id=table_id, name=name)


class RelationCrud(BaseCrud):
    """表关系维护 CRUD — db_table_relations（支持同数据源跨库）"""
    model = DbTableRelation

    def list_by_schema(self, schema_id: int) -> List[DbTableRelation]:
        """按单个 schema 列出（左或右任一側属于该库即命中）"""
        with session_scope() as db:
            rows = db.query(DbTableRelation).filter(
                (DbTableRelation.left_schema_id == schema_id) |
                (DbTableRelation.right_schema_id == schema_id)
            ).order_by(DbTableRelation.id).all()
            for r in rows:
                db.expunge(r)
            return rows

    def list_by_schemas(self, schema_ids: List[int]) -> List[DbTableRelation]:
        """按可见 schema 集合列出（空列表返回空；左右任一侧命中即可）"""
        if not schema_ids:
            return []
        with session_scope() as db:
            rows = db.query(DbTableRelation).filter(
                DbTableRelation.left_schema_id.in_(schema_ids) |
                DbTableRelation.right_schema_id.in_(schema_ids)
            ).order_by(DbTableRelation.id).all()
            for r in rows:
                db.expunge(r)
            return rows

    def exists_same(self, left_schema_id: int, left_table: str, left_column: str,
                    right_schema_id: int, right_table: str, right_column: str,
                    exclude_id: Optional[int] = None) -> bool:
        """同一对连接字段（含方向颠倒）是否已存在；两侧 schema 一起参与判重"""
        with session_scope() as db:
            fwd = db.query(DbTableRelation).filter(
                DbTableRelation.left_schema_id == left_schema_id,
                DbTableRelation.left_table == left_table,
                DbTableRelation.left_column == left_column,
                DbTableRelation.right_schema_id == right_schema_id,
                DbTableRelation.right_table == right_table,
                DbTableRelation.right_column == right_column)
            rev = db.query(DbTableRelation).filter(
                DbTableRelation.left_schema_id == right_schema_id,
                DbTableRelation.left_table == right_table,
                DbTableRelation.left_column == right_column,
                DbTableRelation.right_schema_id == left_schema_id,
                DbTableRelation.right_table == left_table,
                DbTableRelation.right_column == left_column)
            if exclude_id is not None:
                fwd = fwd.filter(DbTableRelation.id != exclude_id)
                rev = rev.filter(DbTableRelation.id != exclude_id)
            return fwd.first() is not None or rev.first() is not None


schema_crud = SchemaCrud()
table_crud = TableCrud()
column_crud = ColumnCrud()
relation_crud = RelationCrud()
