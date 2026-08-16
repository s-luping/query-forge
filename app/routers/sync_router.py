# -*- coding: UTF-8 -*-
"""元数据同步 API 路由 — 数据源管理 + 同步任务 + 执行历史 + 变更审批

设计要点：
    - 数据源密码使用 Fernet 加密存储，读取时脱敏
    - 手动触发同步在后台线程执行，API 立即返回
    - 变更审批：approve 执行删除操作，reject 保留元数据
"""
import threading
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.auth import AdminUser
from app.logger import logger, log_audit
from app.security.crypto import encrypt_secret, decrypt_secret, mask_api_key
from models import SessionLocal
from models.sync import DataSource, SyncJobConfig, SyncRunLog, SchemaChangeLog
from models.schema import DbSchema, DbTable, DbColumn
from services.sync.connectors import get_connector

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════
# Pydantic 模型
# ═══════════════════════════════════════════════════════════════════

class DataSourceCreate(BaseModel):
    name: str
    db_type: str = 'mysql'
    host: str = 'localhost'
    port: int = 3306
    database: str = ''
    username: str = ''
    password: str = ''
    extra_params: str = '{}'


class DataSourceUpdate(BaseModel):
    name: Optional[str] = None
    db_type: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    database: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    extra_params: Optional[str] = None
    status: Optional[str] = None


class SyncJobCreate(BaseModel):
    datasource_id: int
    target_schema_name: str
    sync_mode: str = 'full'
    schedule_type: str = 'interval'
    schedule_value: str = '360'
    auto_classify: bool = True
    include_tables: str = ''
    exclude_tables: str = ''


class SyncJobUpdate(BaseModel):
    target_schema_name: Optional[str] = None
    sync_mode: Optional[str] = None
    schedule_type: Optional[str] = None
    schedule_value: Optional[str] = None
    is_enabled: Optional[bool] = None
    auto_classify: Optional[bool] = None
    include_tables: Optional[str] = None
    exclude_tables: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════
# 数据源管理
# ═══════════════════════════════════════════════════════════════════

@router.get("/datasources")
def list_datasources(user: AdminUser):
    """列出所有数据源（密码脱敏）"""
    # (权限由 AdminUser 依赖统一校验)
    db = SessionLocal()
    try:
        rows = db.query(DataSource).order_by(DataSource.created_at.desc()).all()
        return {
            "items": [_datasource_to_dict(r) for r in rows],
            "total": len(rows),
        }
    finally:
        db.close()


@router.post("/datasources")
def create_datasource(req: DataSourceCreate, user: AdminUser):
    """创建数据源（密码加密存储）"""
    # (权限由 AdminUser 依赖统一校验)
    db = SessionLocal()
    try:
        if db.query(DataSource).filter(DataSource.name == req.name).first():
            raise HTTPException(400, f"数据源名称已存在: {req.name}")

        ds = DataSource(
            name=req.name,
            db_type=req.db_type,
            host=req.host,
            port=req.port,
            database=req.database,
            username=req.username,
            password_enc=encrypt_secret(req.password) if req.password else '',
            extra_params=req.extra_params,
            created_by=user['user_id'],
        )
        db.add(ds)
        db.commit()
        db.refresh(ds)
        log_audit(user, "create_datasource", f"name={req.name}, type={req.db_type}")
        return _datasource_to_dict(ds)
    finally:
        db.close()


@router.put("/datasources/{ds_id}")
def update_datasource(ds_id: int, req: DataSourceUpdate, user: AdminUser):
    """更新数据源"""
    # (权限由 AdminUser 依赖统一校验)
    db = SessionLocal()
    try:
        ds = db.query(DataSource).filter(DataSource.id == ds_id).first()
        if not ds:
            raise HTTPException(404, "数据源不存在")

        if req.name is not None:
            existing = db.query(DataSource).filter(
                DataSource.name == req.name, DataSource.id != ds_id
            ).first()
            if existing:
                raise HTTPException(400, "名称已被占用")
            ds.name = req.name
        if req.db_type is not None:
            ds.db_type = req.db_type
        if req.host is not None:
            ds.host = req.host
        if req.port is not None:
            ds.port = req.port
        if req.database is not None:
            ds.database = req.database
        if req.username is not None:
            ds.username = req.username
        if req.password is not None:
            ds.password_enc = encrypt_secret(req.password) if req.password else ''
        if req.extra_params is not None:
            ds.extra_params = req.extra_params
        if req.status is not None:
            ds.status = req.status

        db.commit()
        return _datasource_to_dict(ds)
    finally:
        db.close()


@router.delete("/datasources/{ds_id}")
def delete_datasource(ds_id: int, user: AdminUser):
    """删除数据源（级联清理同步任务/执行历史/变更记录；关联库解除绑定、保留元数据）"""
    # (权限由 AdminUser 依赖统一校验)
    db = SessionLocal()
    try:
        ds = db.query(DataSource).filter(DataSource.id == ds_id).first()
        if not ds:
            raise HTTPException(404, "数据源不存在")

        job_ids = [j[0] for j in db.query(SyncJobConfig.id).filter(
            SyncJobConfig.datasource_id == ds_id).all()]

        # 主库外键约束开启，须按依赖顺序清理，否则 IntegrityError → 500
        # 1) 变更记录（引用 datasource_id / job_id）
        db.query(SchemaChangeLog).filter(
            SchemaChangeLog.datasource_id == ds_id).delete()
        # 2) 执行历史（引用 job_id）
        if job_ids:
            db.query(SyncRunLog).filter(SyncRunLog.job_id.in_(job_ids)).delete()
        # 3) 同步任务
        db.query(SyncJobConfig).filter(
            SyncJobConfig.datasource_id == ds_id).delete()
        # 4) 该数据源同步出的库解除绑定（保留结构元数据，不误删）
        db.query(DbSchema).filter(DbSchema.datasource_id == ds_id).update(
            {DbSchema.datasource_id: None})

        db.delete(ds)
        db.commit()
        log_audit(user, "delete_datasource",
                  f"id={ds_id} jobs_cleaned={len(job_ids)}")
        return {"success": True,
                "message": f"数据源已删除，已清理 {len(job_ids)} 个关联同步任务及历史记录"}
    finally:
        db.close()


@router.post("/datasources/{ds_id}/test")
def test_datasource(ds_id: int, user: AdminUser):
    """测试数据源连接"""
    # (权限由 AdminUser 依赖统一校验)
    db = SessionLocal()
    try:
        ds = db.query(DataSource).filter(DataSource.id == ds_id).first()
        if not ds:
            raise HTTPException(404, "数据源不存在")

        password = decrypt_secret(ds.password_enc)
        connector = get_connector(
            ds.db_type,
            host=ds.host, port=ds.port, database=ds.database,
            username=ds.username, password=password,
        )
        ok, msg = connector.test_connection()
        connector.close()

        ds.last_tested_at = datetime.now()
        ds.status = 'active' if ok else 'error'
        ds.last_error = '' if ok else msg[:500]
        db.commit()

        return {"success": ok, "message": msg}
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════
# 同步任务管理
# ═══════════════════════════════════════════════════════════════════

@router.get("/jobs")
def list_jobs(user: AdminUser):
    """列出所有同步任务（含数据源名称）"""
    # (权限由 AdminUser 依赖统一校验)
    db = SessionLocal()
    try:
        rows = (db.query(SyncJobConfig, DataSource.name)
                .join(DataSource, SyncJobConfig.datasource_id == DataSource.id)
                .order_by(SyncJobConfig.created_at.desc()).all())
        return {
            "items": [_job_to_dict(job, ds_name) for job, ds_name in rows],
            "total": len(rows),
        }
    finally:
        db.close()


@router.post("/jobs")
def create_job(req: SyncJobCreate, user: AdminUser):
    """创建同步任务"""
    # (权限由 AdminUser 依赖统一校验)
    db = SessionLocal()
    try:
        ds = db.query(DataSource).filter(DataSource.id == req.datasource_id).first()
        if not ds:
            raise HTTPException(404, "数据源不存在")

        existing = db.query(SyncJobConfig).filter(
            SyncJobConfig.datasource_id == req.datasource_id,
            SyncJobConfig.target_schema_name == req.target_schema_name,
        ).first()
        if existing:
            raise HTTPException(400, "该数据源+目标 schema 的同步任务已存在")

        job = SyncJobConfig(
            datasource_id=req.datasource_id,
            target_schema_name=req.target_schema_name,
            sync_mode=req.sync_mode,
            schedule_type=req.schedule_type,
            schedule_value=req.schedule_value,
            auto_classify=req.auto_classify,
            include_tables=req.include_tables,
            exclude_tables=req.exclude_tables,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        log_audit(user, "create_sync_job",
                  f"ds={req.datasource_id}, schema={req.target_schema_name}")
        return _job_to_dict(job, ds.name)
    finally:
        db.close()


@router.put("/jobs/{job_id}")
def update_job(job_id: int, req: SyncJobUpdate, user: AdminUser):
    """更新同步任务"""
    # (权限由 AdminUser 依赖统一校验)
    db = SessionLocal()
    try:
        job = db.query(SyncJobConfig).filter(SyncJobConfig.id == job_id).first()
        if not job:
            raise HTTPException(404, "同步任务不存在")

        for field in ['target_schema_name', 'sync_mode', 'schedule_type',
                       'schedule_value', 'auto_classify', 'include_tables',
                       'exclude_tables']:
            val = getattr(req, field, None)
            if val is not None:
                setattr(job, field, val)
        if req.is_enabled is not None:
            job.is_enabled = req.is_enabled

        db.commit()
        ds_name = db.query(DataSource.name).filter(
            DataSource.id == job.datasource_id).scalar() or ''
        return _job_to_dict(job, ds_name)
    finally:
        db.close()


@router.post("/history/clear")
def clear_sync_history(user: AdminUser):
    """清空全部同步执行历史与变更记录（仅管理员，不可恢复）"""
    # (权限由 AdminUser 依赖统一校验)
    db = SessionLocal()
    try:
        # 先删变更记录（引用 run_log_id/job_id），再删执行日志
        changes = db.query(SchemaChangeLog).delete()
        runs = db.query(SyncRunLog).delete()
        db.commit()
        log_audit(user, "clear_sync_history", f"runs={runs} changes={changes}")
        logger.info(f"管理员 {user['username']} 清空同步历史: runs={runs} changes={changes}")
        return {"success": True,
                "message": f"已清除 {runs} 条同步历史、{changes} 条变更记录"}
    finally:
        db.close()


@router.delete("/jobs/{job_id}")
def delete_job(job_id: int, user: AdminUser):
    """删除同步任务（连同执行历史与变更记录）"""
    # (权限由 AdminUser 依赖统一校验)
    db = SessionLocal()
    try:
        job = db.query(SyncJobConfig).filter(SyncJobConfig.id == job_id).first()
        if not job:
            raise HTTPException(404, "同步任务不存在")
        # 主库外键约束开启：先删变更记录与执行日志，再删任务
        db.query(SchemaChangeLog).filter(SchemaChangeLog.job_id == job_id).delete()
        db.query(SyncRunLog).filter(SyncRunLog.job_id == job_id).delete()
        db.delete(job)
        db.commit()
        log_audit(user, "delete_sync_job", f"job_id={job_id}")
        return {"success": True, "message": "同步任务已删除"}
    finally:
        db.close()


@router.post("/jobs/{job_id}/run")
def trigger_sync(job_id: int, user: AdminUser):
    """手动触发同步（后台执行）"""
    # (权限由 AdminUser 依赖统一校验)
    db = SessionLocal()
    try:
        job = db.query(SyncJobConfig).filter(SyncJobConfig.id == job_id).first()
        if not job:
            raise HTTPException(404, "同步任务不存在")

        ds = db.query(DataSource).filter(DataSource.id == job.datasource_id).first()
        if not ds:
            raise HTTPException(404, "关联数据源不存在")

        triggered_by = f"manual:{user.get('username', '')}"

        # 后台线程执行同步
        def _run_in_background(job_id, ds_id, triggered_by):
            bg_db = SessionLocal()
            try:
                bg_job = bg_db.query(SyncJobConfig).filter(
                    SyncJobConfig.id == job_id).first()
                bg_ds = bg_db.query(DataSource).filter(
                    DataSource.id == ds_id).first()
                if not bg_job or not bg_ds:
                    return
                from services.sync.engine import SyncEngine
                engine = SyncEngine(bg_job, bg_ds, triggered_by=triggered_by)
                engine.run()
            except Exception as e:
                logger.error(f"后台同步失败: {e}", exc_info=True)
            finally:
                bg_db.close()

        thread = threading.Thread(target=_run_in_background,
                                  args=(job_id, ds.id, triggered_by),
                                  daemon=True)
        thread.start()

        log_audit(user, "trigger_sync", f"job_id={job_id}")
        return {"success": True, "message": "同步任务已触发，正在后台执行"}
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════
# 同步历史
# ═══════════════════════════════════════════════════════════════════

@router.get("/runs")
def list_runs(
    user: AdminUser,
    job_id: Optional[int] = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
):
    """同步执行历史"""
    # (权限由 AdminUser 依赖统一校验)
    db = SessionLocal()
    try:
        q = db.query(SyncRunLog)
        if job_id:
            q = q.filter(SyncRunLog.job_id == job_id)
        total = q.count()
        rows = q.order_by(SyncRunLog.started_at.desc()).limit(limit).offset(offset).all()
        # 批量取任务目标库名（避免 N+1 查询）
        run_job_ids = {r.job_id for r in rows if r.job_id}
        job_schema_map = {}
        if run_job_ids:
            job_schema_map = dict(db.query(SyncJobConfig.id, SyncJobConfig.target_schema_name)
                                  .filter(SyncJobConfig.id.in_(run_job_ids)).all())
        return {
            "items": [_run_to_dict(r, job_schema_map.get(r.job_id, '')) for r in rows],
            "total": total,
        }
    finally:
        db.close()


@router.get("/runs/{run_id}")
def get_run_detail(run_id: int, user: AdminUser):
    """同步执行详情（含变更列表）"""
    # (权限由 AdminUser 依赖统一校验)
    db = SessionLocal()
    try:
        run = db.query(SyncRunLog).filter(SyncRunLog.id == run_id).first()
        if not run:
            raise HTTPException(404, "执行记录不存在")

        changes = db.query(SchemaChangeLog).filter(
            SchemaChangeLog.run_log_id == run_id
        ).order_by(SchemaChangeLog.id).all()

        job_schema = db.query(SyncJobConfig.target_schema_name).filter(
            SyncJobConfig.id == run.job_id).scalar() or ''

        return {
            **_run_to_dict(run, job_schema),
            "changes": [_change_to_dict(c) for c in changes],
        }
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════
# 变更记录与审批
# ═══════════════════════════════════════════════════════════════════

@router.get("/changes")
def list_changes(
    user: AdminUser,
    job_id: Optional[int] = None,
    approval_status: Optional[str] = None,
    change_type: Optional[str] = None,
    limit: int = Query(100, le=500),
    offset: int = 0,
):
    """变更记录列表"""
    # (权限由 AdminUser 依赖统一校验)
    db = SessionLocal()
    try:
        q = db.query(SchemaChangeLog)
        if job_id:
            q = q.filter(SchemaChangeLog.job_id == job_id)
        if approval_status:
            q = q.filter(SchemaChangeLog.approval_status == approval_status)
        if change_type:
            q = q.filter(SchemaChangeLog.change_type == change_type)
        total = q.count()
        rows = q.order_by(SchemaChangeLog.created_at.desc()).limit(limit).offset(offset).all()
        return {
            "items": [_change_to_dict(c) for c in rows],
            "total": total,
        }
    finally:
        db.close()


@router.post("/changes/{change_id}/approve")
def approve_change(change_id: int, user: AdminUser):
    """审批通过变更（执行删除操作）"""
    # (权限由 AdminUser 依赖统一校验)
    db = SessionLocal()
    try:
        ch = db.query(SchemaChangeLog).filter(SchemaChangeLog.id == change_id).first()
        if not ch:
            raise HTTPException(404, "变更记录不存在")
        if ch.approval_status != 'pending':
            raise HTTPException(400, f"当前状态不可审批: {ch.approval_status}")

        # 执行删除
        if ch.change_type == 'remove':
            schema = db.query(DbSchema).filter(
                DbSchema.name == ch.target_schema_name).first()
            if schema:
                if ch.object_type == 'table':
                    table = db.query(DbTable).filter(
                        DbTable.schema_id == schema.id,
                        DbTable.name == ch.object_name,
                    ).first()
                    if table:
                        db.query(DbColumn).filter(
                            DbColumn.table_id == table.id
                        ).delete(synchronize_session=False)
                        db.delete(table)
                elif ch.object_type == 'column':
                    table_name, col_name = ch.object_name.rsplit('.', 1)
                    table = db.query(DbTable).filter(
                        DbTable.schema_id == schema.id,
                        DbTable.name == table_name,
                    ).first()
                    if table:
                        db.query(DbColumn).filter(
                            DbColumn.table_id == table.id,
                            DbColumn.name == col_name,
                        ).delete(synchronize_session=False)

        ch.approval_status = 'approved'
        ch.approved_by = user['user_id']
        ch.approved_at = datetime.now()
        db.commit()

        log_audit(user, "approve_change",
                  f"id={change_id}, {ch.change_type} {ch.object_name}")
        return {"success": True, "message": f"变更已审批通过: {ch.object_name}"}
    finally:
        db.close()


@router.post("/changes/{change_id}/reject")
def reject_change(change_id: int, user: AdminUser):
    """拒绝变更（保留元数据）"""
    # (权限由 AdminUser 依赖统一校验)
    db = SessionLocal()
    try:
        ch = db.query(SchemaChangeLog).filter(SchemaChangeLog.id == change_id).first()
        if not ch:
            raise HTTPException(404, "变更记录不存在")
        if ch.approval_status != 'pending':
            raise HTTPException(400, f"当前状态不可审批: {ch.approval_status}")

        ch.approval_status = 'rejected'
        ch.approved_by = user['user_id']
        ch.approved_at = datetime.now()
        db.commit()

        log_audit(user, "reject_change", f"id={change_id}, {ch.object_name}")
        return {"success": True, "message": f"变更已拒绝: {ch.object_name}"}
    finally:
        db.close()


@router.get("/stats")
def sync_stats(user: AdminUser):
    """同步统计概览"""
    # (权限由 AdminUser 依赖统一校验)
    db = SessionLocal()
    try:
        from sqlalchemy import func
        total_ds = db.query(func.count(DataSource.id)).scalar() or 0
        active_ds = db.query(func.count(DataSource.id)).filter(
            DataSource.status == 'active').scalar() or 0
        total_jobs = db.query(func.count(SyncJobConfig.id)).scalar() or 0
        enabled_jobs = db.query(func.count(SyncJobConfig.id)).filter(
            SyncJobConfig.is_enabled == True).scalar() or 0
        total_runs = db.query(func.count(SyncRunLog.id)).scalar() or 0
        success_runs = db.query(func.count(SyncRunLog.id)).filter(
            SyncRunLog.status == 'success').scalar() or 0
        failed_runs = db.query(func.count(SyncRunLog.id)).filter(
            SyncRunLog.status == 'failed').scalar() or 0
        pending_changes = db.query(func.count(SchemaChangeLog.id)).filter(
            SchemaChangeLog.approval_status == 'pending').scalar() or 0

        return {
            "datasources": {"total": total_ds, "active": active_ds},
            "jobs": {"total": total_jobs, "enabled": enabled_jobs},
            "runs": {"total": total_runs, "success": success_runs, "failed": failed_runs},
            "changes": {"pending": pending_changes},
        }
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════
# 序列化辅助
# ═══════════════════════════════════════════════════════════════════

def _datasource_to_dict(ds: DataSource) -> dict:
    return {
        "id": ds.id,
        "name": ds.name,
        "db_type": ds.db_type,
        "host": ds.host,
        "port": ds.port,
        "database": ds.database,
        "username": ds.username,
        "password_masked": mask_api_key(decrypt_secret(ds.password_enc)),
        "has_password": bool(ds.password_enc),
        "extra_params": ds.extra_params,
        "status": ds.status,
        "last_error": ds.last_error,
        "last_tested_at": ds.last_tested_at.isoformat() if ds.last_tested_at else None,
        "created_at": ds.created_at.isoformat() if ds.created_at else None,
    }


def _job_to_dict(job: SyncJobConfig, datasource_name: str = '') -> dict:
    return {
        "id": job.id,
        "datasource_id": job.datasource_id,
        "datasource_name": datasource_name,
        "target_schema_name": job.target_schema_name,
        "sync_mode": job.sync_mode,
        "schedule_type": job.schedule_type,
        "schedule_value": job.schedule_value,
        "is_enabled": job.is_enabled,
        "auto_classify": job.auto_classify,
        "include_tables": job.include_tables,
        "exclude_tables": job.exclude_tables,
        "last_synced_at": job.last_synced_at.isoformat() if job.last_synced_at else None,
        "last_sync_status": job.last_sync_status,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }


def _run_to_dict(run: SyncRunLog, schema_name: str = '') -> dict:
    return {
        "id": run.id,
        "job_id": run.job_id,
        "schema_name": schema_name or '',
        "triggered_by": run.triggered_by,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "status": run.status,
        "tables_total": run.tables_total,
        "tables_synced": run.tables_synced,
        "columns_added": run.columns_added,
        "columns_modified": run.columns_modified,
        "columns_removed": run.columns_removed,
        "changes_auto": run.changes_auto,
        "changes_pending": run.changes_pending,
        "duration_ms": run.duration_ms,
        "error_message": run.error_message,
        "summary": run.summary,
    }


def _change_to_dict(ch: SchemaChangeLog) -> dict:
    return {
        "id": ch.id,
        "run_log_id": ch.run_log_id,
        "job_id": ch.job_id,
        "datasource_id": ch.datasource_id,
        "target_schema_name": ch.target_schema_name,
        "change_type": ch.change_type,
        "object_type": ch.object_type,
        "object_name": ch.object_name,
        "old_value": ch.old_value,
        "new_value": ch.new_value,
        "auto_classified_level": ch.auto_classified_level,
        "approval_status": ch.approval_status,
        "approved_by": ch.approved_by,
        "approved_at": ch.approved_at.isoformat() if ch.approved_at else None,
        "created_at": ch.created_at.isoformat() if ch.created_at else None,
    }
