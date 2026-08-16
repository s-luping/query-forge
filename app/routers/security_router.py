"""安全与审计 API 路由 — 审计日志查询 + 敏感字段管理 + 字段级权限管理 + 行级过滤规则"""
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.auth import AdminUser
from app.logger import logger
from models import SessionLocal
from models.security import QueryAuditLog, UserColumnGrant, RowScopeRule
from models.schema import DbColumn, DbTable, DbSchema
from models.user import User

router = APIRouter(tags=["audit"])


# ═══════════════════════════════════════════════════════════════════
# Pydantic 模型
# ═══════════════════════════════════════════════════════════════════

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
    sensitive_level: str  # public/internal/sensitive/confidential


class ColumnPermissionItem(BaseModel):
    user_id: int
    column_id: int
    access_type: str  # SELECT/FILTER/NONE


class ColumnPermissionDetail(BaseModel):
    """字段权限详情（含关联名称，供前端展示）"""
    id: int
    user_id: int
    username: str = ''
    column_id: int
    column_name: str = ''
    table_name: str = ''
    schema_name: str = ''
    access_type: str = 'SELECT'
    sensitive_level: str = 'public'


class ColumnPermissionDetailResponse(BaseModel):
    items: List[ColumnPermissionDetail]
    total: int


class RowScopeRuleItem(BaseModel):
    id: Optional[int] = None
    user_id: int
    table_id: int
    filter_expression: str


class RowScopeRuleDetail(BaseModel):
    """行级规则详情（含关联名称，供前端展示）"""
    id: int
    user_id: int
    username: str = ''
    table_id: int
    table_name: str = ''
    schema_name: str = ''
    filter_expression: str


class RowScopeRuleDetailResponse(BaseModel):
    items: List[RowScopeRuleDetail]
    total: int


class AllColumnItem(BaseModel):
    """全部字段项（含敏感等级，供敏感字段管理）"""
    column_id: int
    column_name: str
    sensitive_level: str = 'public'
    table_name: str = ''
    schema_name: str = ''


# ═══════════════════════════════════════════════════════════════════
# 审计日志
# ═══════════════════════════════════════════════════════════════════

@router.get("/logs", response_model=AuditLogListResponse)
def list_audit_logs(
    user: AdminUser,
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    blocked_only: bool = Query(False),
):
    """查询审计日志（仅管理员）"""
    # (权限由 AdminUser 依赖统一校验)

    db = SessionLocal()
    try:
        q = db.query(QueryAuditLog)
        if blocked_only:
            q = q.filter(QueryAuditLog.was_blocked == True)
        q = q.order_by(QueryAuditLog.created_at.desc())
        total = q.count()
        rows = q.limit(limit).offset(offset).all()

        items = []
        for r in rows:
            items.append(AuditLogItem(
                id=r.id,
                user_id=r.user_id,
                username=r.username or '',
                query=r.query or '',
                generated_sql=r.generated_sql,
                modified_sql=r.modified_sql,
                tables_accessed=r.tables_accessed or '',
                columns_accessed=r.columns_accessed or '',
                hit_sensitive=bool(r.hit_sensitive),
                was_blocked=bool(r.was_blocked),
                block_reason=r.block_reason or '',
                duration_ms=r.duration_ms or 0,
                created_at=str(r.created_at) if r.created_at else None,
            ))
        return AuditLogListResponse(items=items, total=total)
    finally:
        db.close()


@router.get("/stats")
def audit_stats(user: AdminUser):
    """审计统计（仅管理员）"""
    # (权限由 AdminUser 依赖统一校验)

    db = SessionLocal()
    try:
        from sqlalchemy import func
        total = db.query(func.count(QueryAuditLog.id)).scalar() or 0
        blocked = db.query(func.count(QueryAuditLog.id)).filter(
            QueryAuditLog.was_blocked == True).scalar() or 0
        sensitive = db.query(func.count(QueryAuditLog.id)).filter(
            QueryAuditLog.hit_sensitive == True).scalar() or 0
        return {
            "total_queries": total,
            "blocked_queries": blocked,
            "sensitive_hits": sensitive,
            "block_rate": f"{blocked / total * 100:.1f}%" if total > 0 else "0%",
        }
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════
# 敏感字段管理
# ═══════════════════════════════════════════════════════════════════

@router.put("/sensitive-level")
def update_sensitive_level(
    update: SensitiveLevelUpdate,
    user: AdminUser,
):
    """更新字段敏感等级（仅管理员）"""
    # (权限由 AdminUser 依赖统一校验)

    if update.sensitive_level not in ('public', 'internal', 'sensitive', 'confidential'):
        raise HTTPException(400, f"无效的敏感等级: {update.sensitive_level}")

    db = SessionLocal()
    try:
        col = db.query(DbColumn).filter(DbColumn.id == update.column_id).first()
        if not col:
            raise HTTPException(404, "字段不存在")
        old_level = col.sensitive_level or 'public'
        col.sensitive_level = update.sensitive_level
        db.commit()
        logger.info(f"字段 {col.name} 敏感等级: {old_level} → {update.sensitive_level}")
        return {"success": True, "column_id": col.id, "old_level": old_level,
                "new_level": update.sensitive_level}
    finally:
        db.close()


@router.get("/sensitive-columns")
def list_sensitive_columns(
    user: AdminUser,
    schema_name: Optional[str] = None,
):
    """列出敏感字段（仅管理员）"""
    # (权限由 AdminUser 依赖统一校验)

    db = SessionLocal()
    try:
        q = (db.query(DbColumn.id, DbColumn.name, DbColumn.sensitive_level,
                      DbTable.name, DbSchema.name)
             .join(DbTable, DbColumn.table_id == DbTable.id)
             .join(DbSchema, DbTable.schema_id == DbSchema.id)
             .filter(DbColumn.sensitive_level.in_(['sensitive', 'confidential'])))
        if schema_name:
            q = q.filter(DbSchema.name == schema_name)
        rows = q.all()
        return {
            "items": [
                {"column_id": r[0], "column_name": r[1], "sensitive_level": r[2],
                 "table_name": r[3], "schema_name": r[4]}
                for r in rows
            ],
            "total": len(rows)
        }
    finally:
        db.close()


@router.get("/all-columns")
def list_all_columns(
    user: AdminUser,
    schema_name: Optional[str] = None,
    table_name: Optional[str] = None,
):
    """列出全部字段及其敏感等级（仅管理员）— 供敏感字段管理 UI"""
    # (权限由 AdminUser 依赖统一校验)

    db = SessionLocal()
    try:
        q = (db.query(DbColumn.id, DbColumn.name, DbColumn.sensitive_level,
                      DbTable.name, DbSchema.name)
             .join(DbTable, DbColumn.table_id == DbTable.id)
             .join(DbSchema, DbTable.schema_id == DbSchema.id))
        if schema_name:
            q = q.filter(DbSchema.name == schema_name)
        if table_name:
            q = q.filter(DbTable.name == table_name)
        rows = q.order_by(DbSchema.name, DbTable.name, DbColumn.id).all()
        return {
            "items": [
                {"column_id": r[0], "column_name": r[1],
                 "sensitive_level": r[2] or 'public',
                 "table_name": r[3], "schema_name": r[4]}
                for r in rows
            ],
            "total": len(rows)
        }
    finally:
        db.close()


@router.get("/all-tables")
def list_all_tables(
    user: AdminUser,
    schema_name: Optional[str] = None,
):
    """列出全部表及 ID（仅管理员）— 供行级规则管理 UI 选择表"""
    # (权限由 AdminUser 依赖统一校验)

    db = SessionLocal()
    try:
        q = (db.query(DbTable.id, DbTable.name, DbSchema.name)
             .join(DbSchema, DbTable.schema_id == DbSchema.id))
        if schema_name:
            q = q.filter(DbSchema.name == schema_name)
        rows = q.order_by(DbSchema.name, DbTable.name).all()
        return {
            "items": [
                {"table_id": r[0], "table_name": r[1], "schema_name": r[2]}
                for r in rows
            ],
            "total": len(rows)
        }
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════
# 字段级权限管理
# ═══════════════════════════════════════════════════════════════════

@router.get("/column-permissions")
def list_column_permissions(
    user: AdminUser,
    target_user_id: Optional[int] = None,
):
    """列出字段级权限配置（仅管理员）— 返回关联名称便于展示"""
    # (权限由 AdminUser 依赖统一校验)

    db = SessionLocal()
    try:
        q = (db.query(
                UserColumnGrant.id,
                UserColumnGrant.user_id,
                User.username,
                UserColumnGrant.column_id,
                DbColumn.name,
                DbColumn.sensitive_level,
                DbTable.name,
                DbSchema.name,
                UserColumnGrant.access_type)
             .join(DbColumn, UserColumnGrant.column_id == DbColumn.id)
             .join(DbTable, DbColumn.table_id == DbTable.id)
             .join(DbSchema, DbTable.schema_id == DbSchema.id)
             .join(User, UserColumnGrant.user_id == User.id))
        if target_user_id:
            q = q.filter(UserColumnGrant.user_id == target_user_id)
        rows = q.order_by(User.username, DbSchema.name, DbTable.name, DbColumn.name).all()
        items = [ColumnPermissionDetail(
            id=r[0], user_id=r[1], username=r[2] or '',
            column_id=r[3], column_name=r[4] or '',
            sensitive_level=r[5] or 'public',
            table_name=r[6] or '', schema_name=r[7] or '',
            access_type=r[8]
        ) for r in rows]
        return {"items": [item.model_dump() for item in items], "total": len(items)}
    finally:
        db.close()


@router.post("/column-permission")
def set_column_permission(
    item: ColumnPermissionItem,
    user: AdminUser,
):
    """设置字段级权限（仅管理员）"""
    # (权限由 AdminUser 依赖统一校验)

    if item.access_type not in ('SELECT', 'FILTER', 'NONE'):
        raise HTTPException(400, f"无效的权限级别: {item.access_type}")

    db = SessionLocal()
    try:
        existing = db.query(UserColumnGrant).filter(
            UserColumnGrant.user_id == item.user_id,
            UserColumnGrant.column_id == item.column_id
        ).first()
        if existing:
            existing.access_type = item.access_type
        else:
            db.add(UserColumnGrant(
                user_id=item.user_id,
                column_id=item.column_id,
                access_type=item.access_type
            ))
        db.commit()
        return {"success": True}
    finally:
        db.close()


@router.delete("/column-permission")
def delete_column_permission(
    user: AdminUser,
    user_id: int = Query(...),
    column_id: int = Query(...),
):
    """删除字段级权限（仅管理员）"""
    # (权限由 AdminUser 依赖统一校验)

    db = SessionLocal()
    try:
        existing = db.query(UserColumnGrant).filter(
            UserColumnGrant.user_id == user_id,
            UserColumnGrant.column_id == column_id
        ).first()
        if not existing:
            raise HTTPException(404, "权限记录不存在")
        db.delete(existing)
        db.commit()
        return {"success": True}
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════
# 行级过滤规则
# ═══════════════════════════════════════════════════════════════════

@router.get("/row-scope-rules")
def list_row_scope_rules(
    user: AdminUser,
    target_user_id: Optional[int] = None,
):
    """列出行级过滤规则（仅管理员）— 返回关联名称便于展示"""
    # (权限由 AdminUser 依赖统一校验)

    db = SessionLocal()
    try:
        q = (db.query(
                RowScopeRule.id,
                RowScopeRule.user_id,
                User.username,
                RowScopeRule.table_id,
                DbTable.name,
                DbSchema.name,
                RowScopeRule.filter_expression)
             .join(DbTable, RowScopeRule.table_id == DbTable.id)
             .join(DbSchema, DbTable.schema_id == DbSchema.id)
             .join(User, RowScopeRule.user_id == User.id))
        if target_user_id:
            q = q.filter(RowScopeRule.user_id == target_user_id)
        rows = q.order_by(User.username, DbSchema.name, DbTable.name).all()
        items = [RowScopeRuleDetail(
            id=r[0], user_id=r[1], username=r[2] or '',
            table_id=r[3], table_name=r[4] or '',
            schema_name=r[5] or '',
            filter_expression=r[6] or ''
        ) for r in rows]
        return {"items": [item.model_dump() for item in items], "total": len(items)}
    finally:
        db.close()


@router.post("/row-scope-rule")
def set_row_scope_rule(
    item: RowScopeRuleItem,
    user: AdminUser,
):
    """设置行级过滤规则（仅管理员）"""
    # (权限由 AdminUser 依赖统一校验)

    db = SessionLocal()
    try:
        existing = db.query(RowScopeRule).filter(
            RowScopeRule.user_id == item.user_id,
            RowScopeRule.table_id == item.table_id
        ).first()
        if existing:
            existing.filter_expression = item.filter_expression
        else:
            db.add(RowScopeRule(
                user_id=item.user_id,
                table_id=item.table_id,
                filter_expression=item.filter_expression
            ))
        db.commit()
        return {"success": True}
    finally:
        db.close()


@router.delete("/row-scope-rule")
def delete_row_scope_rule(
    user: AdminUser,
    user_id: int = Query(...),
    table_id: int = Query(...),
):
    """删除行级过滤规则（仅管理员）"""
    # (权限由 AdminUser 依赖统一校验)

    db = SessionLocal()
    try:
        existing = db.query(RowScopeRule).filter(
            RowScopeRule.user_id == user_id,
            RowScopeRule.table_id == table_id
        ).first()
        if not existing:
            raise HTTPException(404, "行级规则不存在")
        db.delete(existing)
        db.commit()
        return {"success": True}
    finally:
        db.close()
