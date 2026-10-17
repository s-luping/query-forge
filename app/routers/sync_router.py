# -*- coding: UTF-8 -*-
"""元数据同步 API 路由 — 数据源管理 + 同步任务 + 执行历史 + 变更审批

设计要点：
    - 数据源密码使用 Fernet 加密存储，读取时脱敏
    - 手动触发同步在后台线程执行，API 立即返回
    - 变更审批：approve 执行删除操作，reject 保留元数据
"""
import threading
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.auth import AdminUser
from app.crypto import decrypt_secret, encrypt_secret, mask_api_key
from app.limiter import LIMIT_HEAVY, LIMIT_READ, LIMIT_TEST, LIMIT_WRITE, limiter
from app.logger import log_audit, logger
from app.response import ErrorCode, fail, ok, ok_msg
from app.timezone import now_beijing
from crud.base import session_scope
from crud.datasource import datasource_crud
from crud.schema import column_crud, schema_crud, table_crud
from crud.sync import change_crud, get_sync_stats, sync_job_crud, sync_run_crud
from models.datasource import DataSource
from models.sync import SyncJobConfig
from services.sync_connectors import get_connector

router = APIRouter()


def _validate_schedule(schedule_type: Optional[str], schedule_value: Optional[str]):
    """interval 类型必须为 ≥10 的正整数分钟（调度巡检周期为 10 分钟，更小值无意义）"""
    if schedule_type == 'interval' and schedule_value is not None:
        try:
            minutes = int(schedule_value)
        except (ValueError, TypeError):
            raise HTTPException(400, "同步间隔必须为整数分钟")
        if minutes < 10:
            raise HTTPException(400, "同步间隔最小为 10 分钟（系统巡检周期），当前值无效")



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
    # 目标数据库名由后端取数据源数据库名，前端无需/不应传入
    target_schema_name: Optional[str] = None
    sync_mode: str = 'full'
    schedule_type: str = 'interval'
    schedule_value: str = '360'
    auto_classify: bool = True
    include_tables: str = ''
    exclude_tables: str = ''


class SyncJobUpdate(BaseModel):
    datasource_id: Optional[int] = None
    sync_mode: Optional[str] = None
    schedule_type: Optional[str] = None
    schedule_value: Optional[str] = None
    is_enabled: Optional[bool] = None
    auto_classify: Optional[bool] = None
    include_tables: Optional[str] = None
    exclude_tables: Optional[str] = None


# ── 响应模型（FastAPI 自动 JSON 序列化；from_attributes 直接读取 ORM） ──

class DataSourceOut(BaseModel):
    """数据源响应 — password_enc 永不输出，仅返回脱敏掩码"""
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    db_type: str
    host: str
    port: int
    database: str
    username: str
    extra_params: str
    status: str
    last_error: Optional[str] = None
    last_tested_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    # 内部读取用（from_attributes 从 ORM 带入），序列化时排除
    password_enc: str = Field(default='', exclude=True)

    @computed_field
    @property
    def password_masked(self) -> str:
        return mask_api_key(decrypt_secret(self.password_enc)) if self.password_enc else '****'

    @computed_field
    @property
    def has_password(self) -> bool:
        return bool(self.password_enc)


class SyncJobOut(BaseModel):
    """同步任务响应 — 统一以 database（数据源数据库名）作为目标库名"""
    model_config = ConfigDict(from_attributes=True)
    id: int
    datasource_id: int
    datasource_name: str = ''
    database: str = ''
    sync_mode: str
    schedule_type: str
    schedule_value: str
    is_enabled: bool
    auto_classify: bool
    include_tables: str
    exclude_tables: str
    last_synced_at: Optional[datetime] = None
    last_sync_status: str = ''
    created_at: Optional[datetime] = None


class SyncRunOut(BaseModel):
    """同步执行记录响应"""
    model_config = ConfigDict(from_attributes=True)
    id: int
    job_id: int
    schema_name: str = ''
    triggered_by: str = ''
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    status: str = ''
    tables_total: int = 0
    tables_synced: int = 0
    columns_added: int = 0
    columns_modified: int = 0
    columns_removed: int = 0
    changes_auto: int = 0
    changes_pending: int = 0
    error_message: Optional[str] = None
    duration_ms: int = 0
    summary: Optional[str] = None


class SyncRunDetailOut(SyncRunOut):
    """同步执行详情（含变更列表）"""
    changes: List['SyncChangeOut'] = []


class SyncChangeOut(BaseModel):
    """变更记录响应"""
    model_config = ConfigDict(from_attributes=True)
    id: int
    run_log_id: int
    job_id: int
    datasource_id: int
    target_schema_name: str = ''
    change_type: str = ''
    object_type: str = ''
    object_name: str = ''
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    auto_classified_level: str = ''
    approval_status: str = ''
    approved_by: Optional[int] = None
    approved_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


# ═══════════════════════════════════════════════════════════════════
# 数据源管理
# ═══════════════════════════════════════════════════════════════════

@router.get("/datasources")
@limiter.limit(LIMIT_READ)
def list_datasources(request: Request, user: AdminUser):
    """列出所有数据源（密码脱敏）"""
    # (权限由 AdminUser 依赖统一校验)
    with session_scope() as db:
        rows = db.query(DataSource).order_by(DataSource.created_at.desc()).all()
        return ok({
            "items": [DataSourceOut.model_validate(r) for r in rows],
            "total": len(rows),
        })
@router.post("/datasources")
@limiter.limit(LIMIT_WRITE)
def create_datasource(request: Request, req: DataSourceCreate, user: AdminUser):
    """创建数据源（密码加密存储）"""
    # (权限由 AdminUser 依赖统一校验)
    with session_scope() as db:
        name = (req.name or '').strip()
        database = (req.database or '').strip()
        if not name:
            raise HTTPException(400, "数据源名称必填")
        if not database:
            raise HTTPException(400, "数据库名必填")
        if db.query(DataSource).filter(DataSource.name == name).first():
            raise HTTPException(400, f"数据源名称已存在: {name}")
    
        ds = DataSource(
            name=name,
            db_type=req.db_type,
            host=req.host,
            port=req.port,
            database=database,
            username=req.username,
            password_enc=encrypt_secret(req.password) if req.password else '',
            extra_params=req.extra_params,
            created_by=user['user_id'],
        )
        db.add(ds)
        db.commit()
        db.refresh(ds)
        log_audit(user, "create_datasource", f"name={name}, type={req.db_type}")
        return DataSourceOut.model_validate(ds)
@router.put("/datasources/{ds_id}")
@limiter.limit(LIMIT_WRITE)
def update_datasource(request: Request, ds_id: int, req: DataSourceUpdate, user: AdminUser):
    """更新数据源"""
    # (权限由 AdminUser 依赖统一校验)
    with session_scope() as db:
        ds = db.query(DataSource).filter(DataSource.id == ds_id).first()
        if not ds:
            raise HTTPException(404, "数据源不存在")
    
        if req.name is not None:
            name = req.name.strip()
            if not name:
                raise HTTPException(400, "数据源名称必填")
            existing = db.query(DataSource).filter(
                DataSource.name == name, DataSource.id != ds_id
            ).first()
            if existing:
                raise HTTPException(400, "名称已被占用")
            ds.name = name
        if req.db_type is not None:
            ds.db_type = req.db_type
        if req.host is not None:
            ds.host = req.host
        if req.port is not None:
            ds.port = req.port
        if req.database is not None:
            database = req.database.strip()
            if not database:
                raise HTTPException(400, "数据库名必填")
            ds.database = database
        if req.username is not None:
            ds.username = req.username
        if req.password is not None:
            ds.password_enc = encrypt_secret(req.password) if req.password else ''
        if req.extra_params is not None:
            ds.extra_params = req.extra_params
        if req.status is not None:
            ds.status = req.status
    
        db.commit()
        return DataSourceOut.model_validate(ds)
@router.delete("/datasources/{ds_id}")
@limiter.limit(LIMIT_WRITE)
def delete_datasource(request: Request, ds_id: int, user: AdminUser):
    """删除数据源（级联清理同步任务/执行历史/变更记录；关联库解除绑定、保留元数据）"""
    # (权限由 AdminUser 依赖统一校验)
    ds = datasource_crud.get_by_id(ds_id)
    if not ds:
        raise HTTPException(404, "数据源不存在")
    job_count = datasource_crud.delete_cascade(ds_id)
    log_audit(user, "delete_datasource",
              f"id={ds_id} jobs_cleaned={job_count}")
    return ok_msg(f"数据源已删除，已清理 {job_count} 个关联同步任务及历史记录")
@router.post("/datasources/{ds_id}/test")
@limiter.limit(LIMIT_TEST)
def test_datasource(request: Request, ds_id: int, user: AdminUser):
    """测试数据源连接"""
    # (权限由 AdminUser 依赖统一校验)
    with session_scope() as db:
        ds = db.query(DataSource).filter(DataSource.id == ds_id).first()
        if not ds:
            raise HTTPException(404, "数据源不存在")
    
        password = decrypt_secret(ds.password_enc)
        connector = get_connector(
            ds.db_type,
            host=ds.host, port=ds.port, database=ds.database,
            username=ds.username, password=password,
            extra_params=ds.extra_params,
        )
        connected, msg = connector.test_connection()
        connector.close()

        ds.last_tested_at = now_beijing()
        ds.status = 'active' if connected else 'error'
        ds.last_error = '' if connected else msg[:500]
        db.commit()

        if connected:
            return ok_msg(msg)
        return fail(ErrorCode.BAD_REQUEST, msg)
# ═══════════════════════════════════════════════════════════════════
# 同步任务管理
# ═══════════════════════════════════════════════════════════════════

@router.get("/jobs")
@limiter.limit(LIMIT_READ)
def list_jobs(request: Request, user: AdminUser):
    """列出所有同步任务（含数据源名称与数据库名）"""
    # (权限由 AdminUser 依赖统一校验)
    rows = sync_job_crud.list_with_datasource()
    items = []
    for job, ds_name, ds_database in rows:
        out = SyncJobOut.model_validate(job)
        out.datasource_name = ds_name
        out.database = ds_database
        items.append(out)
    return ok({"items": items, "total": len(items)})
@router.post("/jobs")
@limiter.limit(LIMIT_WRITE)
def create_job(request: Request, req: SyncJobCreate, user: AdminUser):
    """创建同步任务 — 目标数据库名一律取数据源「数据库名」，不接受前端自定义。"""
    # (权限由 AdminUser 依赖统一校验)
    ds = datasource_crud.get_by_id(req.datasource_id)
    if not ds:
        raise HTTPException(404, "数据源不存在")
    schema_name = (ds.database or '').strip()
    if not schema_name:
        raise HTTPException(400, "数据源未填写数据库名，无法作为目标数据库")

    if sync_job_crud.get_by_datasource_and_schema(req.datasource_id, schema_name):
        raise HTTPException(400, "该数据源+目标 schema 的同步任务已存在")

    _validate_schedule(req.schedule_type, req.schedule_value)

    job = sync_job_crud.create(
        datasource_id=req.datasource_id,
        target_schema_name=schema_name,
        sync_mode=req.sync_mode,
        schedule_type=req.schedule_type,
        schedule_value=req.schedule_value,
        auto_classify=req.auto_classify,
        include_tables=req.include_tables,
        exclude_tables=req.exclude_tables,
    )
    log_audit(user, "create_sync_job",
              f"ds={req.datasource_id}, schema={schema_name}")
    out = SyncJobOut.model_validate(job)
    out.datasource_name = ds.name
    out.database = ds.database
    return out
@router.put("/jobs/{job_id}")
@limiter.limit(LIMIT_WRITE)
def update_job(request: Request, job_id: int, req: SyncJobUpdate, user: AdminUser):
    """更新同步任务 — 目标数据库名恒等于数据源数据库名，不支持修改。"""
    # (权限由 AdminUser 依赖统一校验)
    job = sync_job_crud.get_by_id(job_id)
    if not job:
        raise HTTPException(404, "同步任务不存在")

    # 目标数据库名始终取数据源数据库名；数据源变更后下次编辑保存时自动同步
    _validate_schedule(req.schedule_type, req.schedule_value)
    updates = {}
    for field in ['sync_mode', 'schedule_type', 'schedule_value',
                  'auto_classify', 'include_tables', 'exclude_tables']:
        val = getattr(req, field, None)
        if val is not None:
            updates[field] = val
    if req.is_enabled is not None:
        updates['is_enabled'] = req.is_enabled
    if req.datasource_id is not None and req.datasource_id != job.datasource_id:
        ds = datasource_crud.get_by_id(req.datasource_id)
        if not ds:
            raise HTTPException(404, "数据源不存在")
        schema_name = (ds.database or '').strip()
        if not schema_name:
            raise HTTPException(400, "数据源未填写数据库名，无法作为目标数据库")
        # 唯一约束（datasource_id+target_schema_name）前置校验，避免 IntegrityError 500
        existing = sync_job_crud.get_by_datasource_and_schema(req.datasource_id, schema_name)
        if existing and existing.id != job_id:
            raise HTTPException(400, "该数据源+目标 schema 的同步任务已存在")
        updates['datasource_id'] = req.datasource_id
        updates['target_schema_name'] = schema_name

    if updates:
        sync_job_crud.update(job_id, **updates)
    job = sync_job_crud.get_by_id(job_id)
    ds = datasource_crud.get_by_id(job.datasource_id)
    out = SyncJobOut.model_validate(job)
    out.datasource_name = ds.name if ds else ''
    out.database = ds.database if ds else ''
    return out
@router.post("/history/clear")
@limiter.limit(LIMIT_WRITE)
def clear_sync_history(request: Request, user: AdminUser):
    """清空全部同步执行历史与变更记录（仅管理员，不可恢复）"""
    # (权限由 AdminUser 依赖统一校验)
    runs, changes = change_crud.clear_history()
    log_audit(user, "clear_sync_history", f"runs={runs} changes={changes}")
    logger.info(f"管理员 {user['username']} 清空同步历史: runs={runs} changes={changes}")
    return ok_msg(f"已清除 {runs} 条同步历史、{changes} 条变更记录")
@router.delete("/jobs/{job_id}")
@limiter.limit(LIMIT_WRITE)
def delete_job(request: Request, job_id: int, user: AdminUser):
    """删除同步任务（连同执行历史与变更记录）"""
    # (权限由 AdminUser 依赖统一校验)
    job = sync_job_crud.get_by_id(job_id)
    if not job:
        raise HTTPException(404, "同步任务不存在")
    sync_job_crud.delete_cascade(job_id)
    log_audit(user, "delete_sync_job", f"job_id={job_id}")
    return ok_msg("同步任务已删除")
@router.post("/jobs/{job_id}/run")
@limiter.limit(LIMIT_HEAVY)
def trigger_sync(request: Request, job_id: int, user: AdminUser):
    """手动触发同步（后台执行）"""
    # (权限由 AdminUser 依赖统一校验)
    with session_scope() as db:
        job = db.query(SyncJobConfig).filter(SyncJobConfig.id == job_id).first()
        if not job:
            raise HTTPException(404, "同步任务不存在")
    
        ds = db.query(DataSource).filter(DataSource.id == job.datasource_id).first()
        if not ds:
            raise HTTPException(404, "关联数据源不存在")

        # 并发防护：30 分钟内有处于 running 状态的执行记录时拒绝重复触发
        # （执行记录已拆至日志库，需单独会话查询）
        from models.sync import SyncRunLog
        with session_scope(logs=True) as ldb:
            active_run = ldb.query(SyncRunLog).filter(
                SyncRunLog.job_id == job_id,
                SyncRunLog.status == 'running',
            ).order_by(SyncRunLog.started_at.desc()).first()
        if active_run and active_run.started_at:
            from app.timezone import now_beijing as _now
            if (_now() - active_run.started_at).total_seconds() < 30 * 60:
                raise HTTPException(409, "该任务正在同步中，请稍候再试")
    
        triggered_by = f"manual:{user.get('username', '')}"
    
        # 后台线程执行同步
        def _run_in_background(job_id, ds_id, triggered_by):
            try:
                with session_scope() as bg_db:
                    bg_job = bg_db.query(SyncJobConfig).filter(
                        SyncJobConfig.id == job_id).first()
                    bg_ds = bg_db.query(DataSource).filter(
                        DataSource.id == ds_id).first()
                    if not bg_job or not bg_ds:
                        return
                    from services.sync_engine import SyncEngine
                    engine = SyncEngine(bg_job, bg_ds, triggered_by=triggered_by)
                    engine.run()
            except Exception as e:
                logger.error(f"后台同步失败: {e}", exc_info=True)
    
        thread = threading.Thread(target=_run_in_background,
                                  args=(job_id, ds.id, triggered_by),
                                  daemon=True)
        thread.start()
    
        log_audit(user, "trigger_sync", f"job_id={job_id}")
        return ok_msg("同步任务已触发，正在后台执行")
# ═══════════════════════════════════════════════════════════════════
# 同步历史
# ═══════════════════════════════════════════════════════════════════

@router.get("/runs")
@limiter.limit(LIMIT_READ)
def list_runs(
    request: Request,
    user: AdminUser,
    job_id: Optional[int] = None,
    status: Optional[str] = Query(None, pattern='^(running|success|failed)$'),
    limit: int = Query(50, le=200),
    offset: int = 0,
):
    """同步执行历史"""
    # (权限由 AdminUser 依赖统一校验)
    rows, total = sync_run_crud.list_paged(job_id, limit, offset, status=status)
    # 批量取任务目标库名（避免 N+1 查询）
    run_job_ids = {r.job_id for r in rows if r.job_id}
    job_schema_map = sync_run_crud.schema_map_for_runs(list(run_job_ids))
    # 实时待审批数：按 run_log_id 统计仍处于 pending 的变更，随审批动态减少
    pending_map = change_crud.pending_count_by_runs([r.id for r in rows])
    items = []
    for r in rows:
        out = SyncRunOut.model_validate(r)
        out.schema_name = job_schema_map.get(r.job_id, '')
        # changes_pending 覆盖为实时值；changes_auto 为运行时的自动应用数，不再变化
        out.changes_pending = pending_map.get(r.id, 0)
        items.append(out)
    return ok({"items": items, "total": total})
@router.get("/runs/{run_id}")
@limiter.limit(LIMIT_READ)
def get_run_detail(request: Request, run_id: int, user: AdminUser):
    """同步执行详情（含变更列表）"""
    # (权限由 AdminUser 依赖统一校验)
    run = sync_run_crud.get_by_id(run_id)
    if not run:
        raise HTTPException(404, "执行记录不存在")

    changes = change_crud.list_by_run(run_id)
    job_schema = sync_job_crud.schema_name_by_id(run.job_id)

    detail = SyncRunDetailOut.model_validate(run)
    detail.schema_name = job_schema
    detail.changes = [SyncChangeOut.model_validate(c) for c in changes]
    # 待审批数覆盖为实时值（随审批/拒绝动态减少）
    detail.changes_pending = change_crud.pending_count_by_run(run_id)
    return detail
# ═══════════════════════════════════════════════════════════════════
# 变更记录与审批
# ═══════════════════════════════════════════════════════════════════

@router.get("/changes")
@limiter.limit(LIMIT_READ)
def list_changes(
    request: Request,
    user: AdminUser,
    job_id: Optional[int] = None,
    approval_status: Optional[str] = None,
    change_type: Optional[str] = None,
    limit: int = Query(100, le=500),
    offset: int = 0,
):
    """变更记录列表"""
    # (权限由 AdminUser 依赖统一校验)
    rows, total = change_crud.list_paged(job_id, approval_status, change_type, limit, offset)
    return ok({
        "items": [SyncChangeOut.model_validate(c) for c in rows],
        "total": total,
    })
@router.post("/changes/{change_id}/approve")
@limiter.limit(LIMIT_WRITE)
def approve_change(request: Request, change_id: int, user: AdminUser):
    """审批通过变更（执行删除操作）"""
    # (权限由 AdminUser 依赖统一校验)
    ch = change_crud.get_by_id(change_id)
    if not ch:
        raise HTTPException(404, "变更记录不存在")
    if ch.approval_status != 'pending':
        raise HTTPException(400, f"当前状态不可审批: {ch.approval_status}")

    # 执行删除
    if ch.change_type == 'remove':
        schema = schema_crud.get_by_name(ch.target_schema_name)
        if schema:
            if ch.object_type == 'table':
                table = table_crud.get_by_schema_and_name(schema.id, ch.object_name)
                if table:
                    column_crud.delete_by(table_id=table.id)
                    table_crud.delete(table.id)
            elif ch.object_type == 'column':
                table_name, col_name = ch.object_name.rsplit('.', 1)
                table = table_crud.get_by_schema_and_name(schema.id, table_name)
                if table:
                    column_crud.delete_by(table_id=table.id, name=col_name)

    change_crud.update(change_id,
                       approval_status='approved',
                       approved_by=user['user_id'],
                       approved_at=now_beijing())

    log_audit(user, "approve_change",
              f"id={change_id}, {ch.change_type} {ch.object_name}")
    return ok_msg(f"变更已审批通过: {ch.object_name}")
@router.post("/changes/{change_id}/reject")
@limiter.limit(LIMIT_WRITE)
def reject_change(request: Request, change_id: int, user: AdminUser):
    """拒绝变更（保留元数据）"""
    # (权限由 AdminUser 依赖统一校验)
    ch = change_crud.get_by_id(change_id)
    if not ch:
        raise HTTPException(404, "变更记录不存在")
    if ch.approval_status != 'pending':
        raise HTTPException(400, f"当前状态不可审批: {ch.approval_status}")

    change_crud.update(change_id,
                       approval_status='rejected',
                       approved_by=user['user_id'],
                       approved_at=now_beijing())

    log_audit(user, "reject_change", f"id={change_id}, {ch.object_name}")
    return ok_msg(f"变更已拒绝: {ch.object_name}")
@router.get("/stats")
@limiter.limit(LIMIT_READ)
def sync_stats(request: Request, user: AdminUser):
    """同步统计概览"""
    # (权限由 AdminUser 依赖统一校验)
    return get_sync_stats()