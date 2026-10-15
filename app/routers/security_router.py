"""安全中心：查询审计、敏感等级和数据资源浏览。"""
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, or_

from app.auth import AdminUser
from app.limiter import LIMIT_READ, LIMIT_WRITE, limiter
from app.logger import logger
from app.response import ok
from crud.base import session_scope
from models.schema import DbColumn, DbSchema, DbTable
from models.security import QueryAuditLog

router = APIRouter()


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
    duration_ms: float = 0
    pipeline_log: Optional[str] = None    # 链路追踪 JSON（关键词→召回→聚合→生成→校验→网关）
    created_at: Optional[str] = None


class AuditLogListResponse(BaseModel):
    items: List[AuditLogItem]
    total: int


class SensitiveLevelUpdate(BaseModel):
    column_id: int
    sensitive_level: str


@router.get('/logs', response_model=AuditLogListResponse)
@limiter.limit(LIMIT_READ)
def list_audit_logs(request: Request, user: AdminUser, limit: int = Query(50, le=200),
                    offset: int = Query(0), blocked_only: bool = Query(False)):
    with session_scope(logs=True) as db:
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
            pipeline_log=row.pipeline_log,
            created_at=str(row.created_at) if row.created_at else None,
        ) for row in rows], total=total)
@router.get('/stats')
@limiter.limit(LIMIT_READ)
def audit_stats(request: Request, user: AdminUser):
    with session_scope(logs=True) as db:
        total = db.query(func.count(QueryAuditLog.id)).scalar() or 0
        blocked = db.query(func.count(QueryAuditLog.id)).filter(QueryAuditLog.was_blocked == True).scalar() or 0
        sensitive = db.query(func.count(QueryAuditLog.id)).filter(QueryAuditLog.hit_sensitive == True).scalar() or 0
        return {'total_queries': total, 'blocked_queries': blocked,
                'sensitive_hits': sensitive,
                'block_rate': f'{blocked / total * 100:.1f}%' if total else '0%'}
@router.put('/sensitive-level')
@limiter.limit(LIMIT_WRITE)
def update_sensitive_level(request: Request, update: SensitiveLevelUpdate, user: AdminUser):
    if update.sensitive_level not in ('public', 'internal', 'sensitive', 'confidential'):
        raise HTTPException(400, f'无效的敏感等级: {update.sensitive_level}')
    with session_scope() as db:
        column = db.query(DbColumn).filter(DbColumn.id == update.column_id).first()
        if not column:
            raise HTTPException(404, '字段不存在')
        old_level = column.sensitive_level or 'public'
        column.sensitive_level = update.sensitive_level
        db.commit()
        logger.info(f'字段 {column.name} 敏感等级: {old_level} -> {update.sensitive_level}')
        return {'success': True, 'column_id': column.id, 'old_level': old_level,
                'new_level': update.sensitive_level}
@router.get('/sensitive-columns')
@limiter.limit(LIMIT_READ)
def list_sensitive_columns(request: Request, user: AdminUser, schema_name: Optional[str] = None):
    with session_scope() as db:
        query = (db.query(DbColumn.id, DbColumn.name, DbColumn.sensitive_level,
                          DbTable.name, DbSchema.name)
                 .join(DbTable, DbColumn.table_id == DbTable.id)
                 .join(DbSchema, DbTable.schema_id == DbSchema.id)
                 .filter(DbColumn.sensitive_level.in_(['sensitive', 'confidential'])))
        if schema_name:
            query = query.filter(DbSchema.name == schema_name)
        rows = query.all()
        return ok({'items': [{'column_id': row[0], 'column_name': row[1],
                              'sensitive_level': row[2], 'table_name': row[3],
                              'schema_name': row[4]} for row in rows], 'total': len(rows)})
@router.get('/all-columns')
@limiter.limit(LIMIT_READ)
def list_all_columns(request: Request, user: AdminUser, schema_name: Optional[str] = None,
                     table_name: Optional[str] = None,
                     search: Optional[str] = None,
                     sensitive_level: Optional[str] = None,
                     limit: int = Query(100, ge=1, le=1000),
                     offset: int = Query(0, ge=0)):
    with session_scope() as db:
        query = (db.query(DbColumn.id, DbColumn.name, DbColumn.sensitive_level,
                          DbColumn.description, DbTable.name, DbSchema.name)
                 .join(DbTable, DbColumn.table_id == DbTable.id)
                 .join(DbSchema, DbTable.schema_id == DbSchema.id))
        if schema_name:
            query = query.filter(DbSchema.name == schema_name)
        if table_name:
            query = query.filter(DbTable.name == table_name)
        if search:
            pattern = f'%{search}%'
            query = query.filter(or_(
                DbSchema.name.like(pattern),
                DbTable.name.like(pattern),
                DbColumn.name.like(pattern),
            ))
        if sensitive_level:
            query = query.filter(DbColumn.sensitive_level == sensitive_level)
        total = query.count()
        rows = (query.order_by(DbSchema.name, DbTable.name, DbColumn.id)
                .offset(offset).limit(limit).all())
        return ok({'items': [{'column_id': row[0], 'column_name': row[1],
                              'sensitive_level': row[2] or 'public',
                              'description': row[3] or '', 'table_name': row[4],
                              'schema_name': row[5]} for row in rows], 'total': total})
@router.get('/all-tables')
@limiter.limit(LIMIT_READ)
def list_all_tables(request: Request, user: AdminUser, schema_name: Optional[str] = None):
    with session_scope() as db:
        query = db.query(DbTable.id, DbTable.name, DbSchema.name).join(
            DbSchema, DbTable.schema_id == DbSchema.id)
        if schema_name:
            query = query.filter(DbSchema.name == schema_name)
        rows = query.order_by(DbSchema.name, DbTable.name).all()
        return ok({'items': [{'table_id': row[0], 'table_name': row[1],
                              'schema_name': row[2]} for row in rows], 'total': len(rows)})