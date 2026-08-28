# -*- coding: UTF-8 -*-
"""schema 域服务 — 三层模型（db_schemas/db_tables/db_columns）读写

同时提供与旧"一行一字段"表兼容的平铺视图（ColumnFlat / FieldRow），
供 API 响应与 core 流水线（字段召回、CSV 构建）无感切换。
"""
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple, Dict

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from models.schema import DbSchema, DbTable, DbColumn
from models.datasource import DataSource
from crud.base import session_scope


# ═══════════════════════════════════════════════════════════════════
# 平铺视图（兼容旧 Schema ORM 的形状）
# ═══════════════════════════════════════════════════════════════════

@dataclass
class ColumnFlat:
    """平铺的列视图 — 供 SchemaItem 响应模型 model_validate 使用"""
    id: int
    schema_name: str
    table_name: str
    table_description: Optional[str]
    column_name: str
    column_type: Optional[str]
    column_description: Optional[str]
    column_key: Optional[str]
    foreign_key: Optional[str]
    is_nullable: bool
    default_value: Optional[str]
    sample_values: Optional[str]
    sensitive_level: str = 'public'
    is_dimension: bool = False
    is_measure: bool = False
    created_at: datetime = None


@dataclass
class FieldRow:
    """轻量字段行 — 供 pipeline/chat 字段召回使用（属性访问兼容旧 ORM 对象）"""
    table_name: str
    column_name: str
    column_type: str = ''
    column_description: str = ''
    column_key: str = ''
    foreign_key: str = ''
    sample_values: str = ''
    schema_name: str = ''
    column_id: int = 0
    sensitive_level: str = 'public'
    is_dimension: bool = False
    is_measure: bool = False
    table_description: str = ''


_FLAT_COLS = (
    DbColumn.id, DbSchema.name, DbTable.name, DbTable.description,
    DbColumn.name, DbColumn.data_type, DbColumn.description,
    DbColumn.column_key, DbColumn.foreign_key, DbColumn.is_nullable,
    DbColumn.default_value, DbColumn.sample_values, DbColumn.sensitive_level,
    DbColumn.is_dimension, DbColumn.is_measure,
    DbColumn.created_at,
)


def _base_query(db: Session):
    return (db.query(*_FLAT_COLS)
            .join(DbTable, DbColumn.table_id == DbTable.id)
            .join(DbSchema, DbTable.schema_id == DbSchema.id))


def _to_flat(row) -> ColumnFlat:
    return ColumnFlat(
        id=row[0], schema_name=row[1], table_name=row[2], table_description=row[3],
        column_name=row[4], column_type=row[5], column_description=row[6],
        column_key=row[7] or '', foreign_key=row[8] or '', is_nullable=bool(row[9]),
        default_value=row[10], sample_values=row[11], sensitive_level=row[12] or 'public',
        is_dimension=bool(row[13]), is_measure=bool(row[14]),
        created_at=row[15],
    )


def _apply_filters(query, schema_name=None, table_name=None, search=None,
                   visible_schema_ids=None, table_grants_by_schema=None):
    if visible_schema_ids is not None:
        if not visible_schema_ids:
            return query.filter(DbSchema.id < 0)  # 空列表 → 无可见数据
        query = query.filter(DbSchema.id.in_(visible_schema_ids))
    if table_grants_by_schema:
        # 表级白名单：受限 schema 仅名单内表可见；未受限 schema 全可见
        restricted_sids = list(table_grants_by_schema.keys())
        allowed_tids = [tid for ids in table_grants_by_schema.values() for tid in ids]
        query = query.filter(or_(
            ~DbTable.schema_id.in_(restricted_sids),
            DbTable.id.in_(allowed_tids),
        ))
    if schema_name:
        query = query.filter(DbSchema.name == schema_name)
    if table_name:
        query = query.filter(DbTable.name == table_name)
    if search:
        pattern = f"%{search}%"
        query = query.filter(or_(
            DbSchema.name.like(pattern),
            DbTable.name.like(pattern),
            DbColumn.name.like(pattern),
            DbColumn.description.like(pattern),
            DbTable.description.like(pattern),
        ))
    return query


def query_flat(db: Session, schema_name=None, table_name=None, search=None,
               visible_schema_ids=None, table_grants_by_schema=None,
               limit=None, offset=None) -> Tuple[List[ColumnFlat], int]:
    """平铺查询，返回 (rows, total)"""
    q = _apply_filters(_base_query(db), schema_name, table_name, search,
                       visible_schema_ids, table_grants_by_schema)
    total = q.count()
    q = q.order_by(DbColumn.created_at.desc(), DbColumn.id.desc())
    if limit is not None:
        q = q.limit(limit)
    if offset is not None:
        q = q.offset(offset)
    return [_to_flat(r) for r in q.all()], total


# ═══════════════════════════════════════════════════════════════════
# 写入：解析结果 → 三层 upsert
# ═══════════════════════════════════════════════════════════════════

def save_parsed_results(parsed_results: List[dict], user_id: int, db: Session,
                        db_type: str = '', source: str = 'ddl',
                        datasource_id: Optional[int] = None) -> Tuple[int, int, List[str]]:
    """保存解析结果到三层表（同 schema+table+column 视为重复跳过）

    存储时数据库类型（db_type）必填：新建库必须携带具体类型。
    数据源（datasource_id）在导入时一并关联：新建库写入，已存在且未关联时补填。
    返回 (new_count, duplicate_count, schema_names)
    """
    if not parsed_results:
        return 0, 0, []

    new_count = 0
    duplicate_count = 0

    # 按 schema → table 分组
    grouped = {}
    for r in parsed_results:
        grouped.setdefault(r['schema_name'], {}).setdefault(r['table_name'], []).append(r)

    touched_schemas = []
    for schema_name, tables in grouped.items():
        schema = db.query(DbSchema).filter(DbSchema.name == schema_name).first()
        if not schema:
            if not db_type:
                raise ValueError(f"数据库类型不能为空（库: {schema_name}）")
            schema = DbSchema(owner_user_id=user_id, name=schema_name,
                              db_type=db_type, source=source,
                              datasource_id=datasource_id)
            db.add(schema)
            db.flush()
        else:
            if db_type and not schema.db_type:
                schema.db_type = db_type
            if datasource_id is not None and not schema.datasource_id:
                schema.datasource_id = datasource_id
        touched_schemas.append(schema_name)

        for table_name, cols in tables.items():
            table = db.query(DbTable).filter(
                DbTable.schema_id == schema.id, DbTable.name == table_name).first()
            if not table:
                table = DbTable(schema_id=schema.id, name=table_name)
                db.add(table)
                db.flush()

            # 表注释：解析结果里有且当前为空时更新（只写一次，不再逐字段重复）
            table_desc = cols[0].get('table_description') or ''
            if table_desc and not table.description:
                table.description = table_desc

            existing_cols = {c.name for c in db.query(DbColumn.name).filter(
                DbColumn.table_id == table.id).all()}

            ordinal = len(existing_cols)
            for col in cols:
                col_name = col.get('column_name', '')
                if not col_name or col_name in existing_cols:
                    duplicate_count += 1
                    continue
                db.add(DbColumn(
                    table_id=table.id,
                    ordinal=ordinal,
                    name=col_name,
                    data_type=col.get('column_type') or '',
                    description=col.get('column_description') or '',
                    is_nullable=col.get('is_nullable', True),
                    default_value=col.get('default_value'),
                    column_key=col.get('column_key') or '',
                    foreign_key=col.get('foreign_key') or '',
                    sample_values=col.get('sample_values'),
                ))
                existing_cols.add(col_name)
                ordinal += 1
                new_count += 1

    db.commit()
    return new_count, duplicate_count, touched_schemas


# ═══════════════════════════════════════════════════════════════════
# 读辅助
# ═══════════════════════════════════════════════════════════════════

def get_schema_id_by_name(db: Session, name: str) -> Optional[int]:
    row = db.query(DbSchema.id).filter(DbSchema.name == name).first()
    return row[0] if row else None


def get_schema_name_by_id(db: Session, schema_id: Optional[int]) -> Optional[str]:
    if not schema_id:
        return None
    row = db.query(DbSchema.name).filter(DbSchema.id == schema_id).first()
    return row[0] if row else None


def get_schema_name_map(db: Session) -> dict:
    """id → name 映射（列表页批量解析用）"""
    return {r[0]: r[1] for r in db.query(DbSchema.id, DbSchema.name).all()}


def list_schema_names(db: Session, visible_schema_ids=None) -> List[str]:
    q = db.query(DbSchema.name)
    if visible_schema_ids is not None:
        if not visible_schema_ids:
            return []
        q = q.filter(DbSchema.id.in_(visible_schema_ids))
    return [r[0] for r in q.distinct().all()]


def list_schema_types(db: Session, visible_schema_ids=None) -> Dict[str, str]:
    """库名 → db_type 映射（供前端"选库自动带出类型"）"""
    q = db.query(DbSchema.name, DbSchema.db_type)
    if visible_schema_ids is not None:
        if not visible_schema_ids:
            return {}
        q = q.filter(DbSchema.id.in_(visible_schema_ids))
    return {r[0]: (r[1] or '') for r in q.all()}


def get_schema_type_by_name(db: Session, schema_name: Optional[str]) -> str:
    """按库名取 db_type（库不存在或未设置时返回空串）"""
    if not schema_name:
        return ''
    row = db.query(DbSchema.db_type).filter(DbSchema.name == schema_name).first()
    return (row[0] or '') if row else ''


def list_schemas_with_datasource(db: Session, visible_schema_ids=None):
    """库列表（含数据源分组信息）— 数据源 → 数据库 → 表 展示层级

    返回: [{schema_id, name, db_type, datasource_id, datasource_name}]
    datasource_name 为空表示手动导入/未关联数据源。
    """
    q = (db.query(DbSchema.id, DbSchema.name, DbSchema.db_type,
                  DbSchema.datasource_id, DataSource.name)
         .outerjoin(DataSource, DbSchema.datasource_id == DataSource.id))
    if visible_schema_ids is not None:
        if not visible_schema_ids:
            return []
        q = q.filter(DbSchema.id.in_(visible_schema_ids))
    return [
        {"schema_id": r[0], "name": r[1], "db_type": r[2] or '',
         "datasource_id": r[3], "datasource_name": r[4] or ''}
        for r in q.order_by(DbSchema.name.asc()).all()
    ]


def list_tables(db: Session, schema_name=None, visible_schema_ids=None,
                table_grants_by_schema=None) -> List[Tuple[str, str]]:
    """返回 [(table_name, description)]"""
    q = (db.query(DbTable.name, DbTable.description)
         .join(DbSchema, DbTable.schema_id == DbSchema.id))
    if visible_schema_ids is not None:
        if not visible_schema_ids:
            return []
        q = q.filter(DbSchema.id.in_(visible_schema_ids))
    if table_grants_by_schema:
        restricted_sids = list(table_grants_by_schema.keys())
        allowed_tids = [tid for ids in table_grants_by_schema.values() for tid in ids]
        q = q.filter(or_(
            ~DbTable.schema_id.in_(restricted_sids),
            DbTable.id.in_(allowed_tids),
        ))
    if schema_name:
        q = q.filter(DbSchema.name == schema_name)
    return [(r[0], r[1] or '') for r in q.distinct().all()]


def field_count(schema_name: Optional[str] = None) -> int:
    """字段总数（供向量索引阈值判断）"""
    with session_scope() as db:
        q = db.query(func.count(DbColumn.id)).join(DbTable, DbColumn.table_id == DbTable.id)
        if schema_name:
            q = q.join(DbSchema, DbTable.schema_id == DbSchema.id).filter(DbSchema.name == schema_name)
        return q.scalar() or 0
def iter_field_rows(schema_name: Optional[str] = None,
                    table_names: Optional[List[str]] = None,
                    visible_schema_ids=None,
                    table_grants_by_schema=None) -> List[FieldRow]:
    """字段行列表（旧 Schema ORM 属性形状），供 core 流水线使用"""
    with session_scope() as db:
        q = (db.query(DbSchema.name, DbTable.name, DbTable.description,
                      DbColumn.name, DbColumn.data_type,
                      DbColumn.description, DbColumn.column_key, DbColumn.foreign_key,
                      DbColumn.sample_values, DbColumn.id, DbColumn.sensitive_level,
                      DbColumn.is_dimension, DbColumn.is_measure)
             .join(DbTable, DbColumn.table_id == DbTable.id)
             .join(DbSchema, DbTable.schema_id == DbSchema.id))
        if visible_schema_ids is not None:
            if not visible_schema_ids:
                return []
            q = q.filter(DbSchema.id.in_(visible_schema_ids))
        if table_grants_by_schema:
            restricted_sids = list(table_grants_by_schema.keys())
            allowed_tids = [tid for ids in table_grants_by_schema.values() for tid in ids]
            q = q.filter(or_(
                ~DbTable.schema_id.in_(restricted_sids),
                DbTable.id.in_(allowed_tids),
            ))
        if schema_name:
            q = q.filter(DbSchema.name == schema_name)
        if table_names:
            q = q.filter(DbTable.name.in_(table_names))
        return [FieldRow(
            schema_name=r[0], table_name=r[1], table_description=r[2] or '',
            column_name=r[3], column_type=r[4] or '',
            column_description=r[5] or '',
            column_key=r[6] or '', foreign_key=r[7] or '',
            sample_values=r[8] or '', column_id=r[9],
            sensitive_level=r[10] or 'public',
            is_dimension=bool(r[11]), is_measure=bool(r[12]),
        ) for r in q.all()]
# ═══════════════════════════════════════════════════════════════════
# 删除 / 更新
# ═══════════════════════════════════════════════════════════════════

def delete_schema_by_name(db: Session, schema_name: str) -> int:
    """删除整个 schema（含表和字段），返回删除的字段数"""
    schema = db.query(DbSchema).filter(DbSchema.name == schema_name).first()
    if not schema:
        return 0
    table_ids = [t.id for t in db.query(DbTable.id).filter(DbTable.schema_id == schema.id).all()]
    col_count = 0
    if table_ids:
        col_count = db.query(DbColumn).filter(DbColumn.table_id.in_(table_ids)).delete(synchronize_session=False)
        db.query(DbTable).filter(DbTable.id.in_(table_ids)).delete(synchronize_session=False)
    db.query(DbSchema).filter(DbSchema.id == schema.id).delete(synchronize_session=False)
    db.commit()
    return col_count


def delete_table(db: Session, schema_name: str, table_name: str) -> int:
    """删除指定表（含字段），返回删除的字段数"""
    schema = db.query(DbSchema).filter(DbSchema.name == schema_name).first()
    if not schema:
        return 0
    table = db.query(DbTable).filter(
        DbTable.schema_id == schema.id, DbTable.name == table_name).first()
    if not table:
        return 0
    col_count = db.query(DbColumn).filter(DbColumn.table_id == table.id).delete(synchronize_session=False)
    db.query(DbTable).filter(DbTable.id == table.id).delete(synchronize_session=False)
    db.commit()
    return col_count


def delete_column_by_id(db: Session, column_id: int) -> bool:
    col = db.query(DbColumn).filter(DbColumn.id == column_id).first()
    if not col:
        return False
    db.delete(col)
    db.commit()
    return True


def update_sample_values(db: Session, column_id: int, sample_values: str) -> bool:
    col = db.query(DbColumn).filter(DbColumn.id == column_id).first()
    if not col:
        return False
    col.sample_values = sample_values
    db.commit()
    return True


def update_column_metadata(db: Session, column_id: int,
                           is_dimension: Optional[bool] = None,
                           is_measure: Optional[bool] = None,
                           description: Optional[str] = None) -> bool:
    """更新字段的维度/度量标记与描述（仅管理员）。未传字段保持不变。"""
    col = db.query(DbColumn).filter(DbColumn.id == column_id).first()
    if not col:
        return False
    if is_dimension is not None:
        col.is_dimension = bool(is_dimension)
    if is_measure is not None:
        col.is_measure = bool(is_measure)
    if description is not None:
        col.description = description
    db.commit()
    return True


# ═══════════════════════════════════════════════════════════════════
# 统计
# ═══════════════════════════════════════════════════════════════════

def stats(db: Session, visible_schema_ids=None, table_grants_by_schema=None) -> dict:
    base_cols = (db.query(func.count(DbColumn.id))
                 .join(DbTable, DbColumn.table_id == DbTable.id)
                 .join(DbSchema, DbTable.schema_id == DbSchema.id))
    base_tables = (db.query(func.count(func.distinct(DbTable.id)))
                   .join(DbSchema, DbTable.schema_id == DbSchema.id))
    base_schemas = db.query(func.count(func.distinct(DbSchema.id)))

    if visible_schema_ids is not None:
        if not visible_schema_ids:
            return {"schema_count": 0, "table_count": 0, "column_count": 0}
        base_cols = base_cols.filter(DbSchema.id.in_(visible_schema_ids))
        base_tables = base_tables.filter(DbSchema.id.in_(visible_schema_ids))
        base_schemas = base_schemas.filter(DbSchema.id.in_(visible_schema_ids))

    if table_grants_by_schema:
        restricted_sids = list(table_grants_by_schema.keys())
        allowed_tids = [tid for ids in table_grants_by_schema.values() for tid in ids]
        tbl_filter = or_(~DbTable.schema_id.in_(restricted_sids),
                         DbTable.id.in_(allowed_tids))
        base_cols = base_cols.filter(tbl_filter)
        base_tables = base_tables.filter(tbl_filter)

    return {
        "schema_count": base_schemas.scalar() or 0,
        "table_count": base_tables.scalar() or 0,
        "column_count": base_cols.scalar() or 0,
    }
