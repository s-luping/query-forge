"""安全中心：查询审计、敏感等级和数据资源浏览。"""
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func

from app.auth import AdminUser
from app.logger import logger
from models import SessionLocal
from models.security import QueryAuditLog
from models.schema import DbColumn, DbTable, DbSchema

router = APIRouter(tags=['audit'])


class AuditLogItem(BaseModel):
    id: int
    user_id: int
    username: str = ''
    query: str
    generated_sql: Optional[str] = None
    modified_sql: Optional[str] = None
    tables_accessed: str = ''
    columns_accessed: str = ''
    hit_sensitive: bool = False
    was_blocked: bool = False
    block_reason: str = ''
    duration_ms: int = 0
    created_at: Optional[str] = None


class AuditLogListResponse(BaseModel):
    items: List[AuditLogItem]
    total: int


class SensitiveLevelUpdate(BaseModel):
    column_id: int
    sensitive_level: str


@router.get('/logs', response_model=AuditLogListResponse)
def list_audit_logs(user: AdminUser, limit: int = Query(50, le=200),
                    offset: int = Query(0), blocked_only: bool = Query(False)):
    db = SessionLocal()
    try:
        query = db.query(QueryAuditLog)
        if blocked_only:
            query = query.filter(QueryAuditLog.was_blocked == True)
        total = query.count()
        rows = query.order_by(QueryAuditLog.created_at.desc()).limit(limit).offset(offset).all()
        return AuditLogListResponse(items=[AuditLogItem(
            id=row.id, user_id=row.user_id, username=row.username or '', query=row.query or '',
            generated_sql=row.generated_sql, modified_sql=row.modified_sql,
            tables_accessed=row.tables_accessed or '', columns_accessed=row.columns_accessed or '',
            hit_sensitive=bool(row.hit_sensitive), was_blocked=bool(row.was_blocked),
            block_reason=row.block_reason or '', duration_ms=row.duration_ms or 0,
            created_at=str(row.created_at) if row.created_at else None,
        ) for row in rows], total=total)
    finally:
        db.close()


@router.get('/stats')
def audit_stats(user: AdminUser):
    db = SessionLocal()
    try:
        total = db.query(func.count(QueryAuditLog.id)).scalar() or 0
        blocked = db.query(func.count(QueryAuditLog.id)).filter(QueryAuditLog.was_blocked == True).scalar() or 0
        sensitive = db.query(func.count(QueryAuditLog.id)).filter(QueryAuditLog.hit_sensitive == True).scalar() or 0
        return {'total_queries': total, 'blocked_queries': blocked,
                'sensitive_hits': sensitive,
                'block_rate': f'{blocked / total * 100:.1f}%' if total else '0%'}
    finally:
        db.close()


@router.put('/sensitive-level')
def update_sensitive_level(update: SensitiveLevelUpdate, user: AdminUser):
    if update.sensitive_level not in ('public', 'internal', 'sensitive', 'confidential'):
        raise HTTPException(400, f'无效的敏感等级: {update.sensitive_level}')
    db = SessionLocal()
    try:
        column = db.query(DbColumn).filter(DbColumn.id == update.column_id).first()
        if not column:
            raise HTTPException(404, '字段不存在')
        old_level = column.sensitive_level or 'public'
        column.sensitive_level = update.sensitive_level
        db.commit()
        logger.info(f'字段 {column.name} 敏感等级: {old_level} -> {update.sensitive_level}')
        return {'success': True, 'column_id': column.id, 'old_level': old_level,
                'new_level': update.sensitive_level}
    finally:
        db.close()


@router.get('/sensitive-columns')
def list_sensitive_columns(user: AdminUser, schema_name: Optional[str] = None):
    db = SessionLocal()
    try:
        query = (db.query(DbColumn.id, DbColumn.name, DbColumn.sensitive_level,
                          DbTable.name, DbSchema.name)
                 .join(DbTable, DbColumn.table_id == DbTable.id)
                 .join(DbSchema, DbTable.schema_id == DbSchema.id)
                 .filter(DbColumn.sensitive_level.in_(['sensitive', 'confidential'])))
        if schema_name:
            query = query.filter(DbSchema.name == schema_name)
        rows = query.all()
        return {'items': [{'column_id': row[0], 'column_name': row[1],
                           'sensitive_level': row[2], 'table_name': row[3],
                           'schema_name': row[4]} for row in rows], 'total': len(rows)}
    finally:
        db.close()


@router.get('/all-columns')
def list_all_columns(user: AdminUser, schema_name: Optional[str] = None,
                     table_name: Optional[str] = None):
    db = SessionLocal()
    try:
        query = (db.query(DbColumn.id, DbColumn.name, DbColumn.sensitive_level,
                          DbTable.name, DbSchema.name)
                 .join(DbTable, DbColumn.table_id == DbTable.id)
                 .join(DbSchema, DbTable.schema_id == DbSchema.id))
        if schema_name:
            query = query.filter(DbSchema.name == schema_name)
        if table_name:
            query = query.filter(DbTable.name == table_name)
        rows = query.order_by(DbSchema.name, DbTable.name, DbColumn.id).all()
        return {'items': [{'column_id': row[0], 'column_name': row[1],
                           'sensitive_level': row[2] or 'public', 'table_name': row[3],
                           'schema_name': row[4]} for row in rows], 'total': len(rows)}
    finally:
        db.close()


@router.get('/all-tables')
def list_all_tables(user: AdminUser, schema_name: Optional[str] = None):
    db = SessionLocal()
    try:
        query = db.query(DbTable.id, DbTable.name, DbSchema.name).join(
            DbSchema, DbTable.schema_id == DbSchema.id)
        if schema_name:
            query = query.filter(DbSchema.name == schema_name)
        rows = query.order_by(DbSchema.name, DbTable.name).all()
        return {'items': [{'table_id': row[0], 'table_name': row[1],
                           'schema_name': row[2]} for row in rows], 'total': len(rows)}
    finally:
        db.close()
