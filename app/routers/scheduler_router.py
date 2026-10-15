# -*- coding: UTF-8 -*-
"""定时任务中心接口 — 任务增删改查 / 执行控制 / 执行日志 / cron 预览

参考 RuoYi / XXL-JOB 的任务管理 API 设计：
    GET    /api/scheduler/jobs              任务列表（含调度器运行时状态）
    POST   /api/scheduler/jobs              新增任务
    PUT    /api/scheduler/jobs/{id}         修改任务
    DELETE /api/scheduler/jobs/{id}         删除任务（系统内置任务禁止删除）
    POST   /api/scheduler/jobs/{id}/run     手动执行一次
    POST   /api/scheduler/jobs/{id}/pause   暂停
    POST   /api/scheduler/jobs/{id}/resume  恢复
    GET    /api/scheduler/jobs/{id}/logs    执行日志（分页）
    DELETE /api/scheduler/logs              清空执行日志（可按任务过滤）
    GET    /api/scheduler/handlers          可用处理器及参数 schema
    POST   /api/scheduler/cron-preview      cron 表达式校验 + 下次执行时间预览
"""
import json
from typing import Optional

from apscheduler.triggers.cron import CronTrigger
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.auth import AdminUser
from app.limiter import LIMIT_READ, LIMIT_WRITE, limiter
from app.logger import log_audit
from app.timezone import BEIJING_TZ, now_beijing
from crud.base import session_scope
from models.scheduler import SchedulerJob, SchedulerJobLog
from scheduler.registry import get_handler_def, list_handlers, validate_params
from scheduler.scheduler import MIN_INTERVAL_SECONDS, scheduler_manager

router = APIRouter()


# ── 请求/响应模型 ─────────────────────────────────────────────

class JobUpsertRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    handler: str = Field(min_length=1, max_length=100)
    schedule_type: str = Field(pattern='^(cron|interval)$')
    cron_expr: str = ''
    interval_seconds: int = 0
    params: dict = Field(default_factory=dict)
    description: str = Field(default='', max_length=300)
    misfire_grace_time: int = Field(default=60, ge=0, le=86400)
    max_instances: int = Field(default=1, ge=1, le=10)


# ── 内部工具 ──────────────────────────────────────────────────

def _format_datetime(value) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=BEIJING_TZ)
    return value.astimezone(BEIJING_TZ).strftime('%Y-%m-%d %H:%M:%S')


def _validate_schedule(data: JobUpsertRequest):
    """调度配置校验 — cron 表达式可解析 / interval 不低于下限"""
    if data.schedule_type == 'cron':
        expr = (data.cron_expr or '').strip()
        if not expr:
            raise HTTPException(status_code=400, detail='cron 表达式不能为空')
        try:
            CronTrigger.from_crontab(expr, timezone=BEIJING_TZ)
        except ValueError as exc:
            raise HTTPException(status_code=400,
                                detail=f'cron 表达式不合法（格式：分 时 日 月 周）：{exc}')
    else:
        if data.interval_seconds < MIN_INTERVAL_SECONDS:
            raise HTTPException(
                status_code=400,
                detail=f'执行间隔不能小于 {MIN_INTERVAL_SECONDS} 秒')


def _job_item(job: SchedulerJob) -> dict:
    """任务行序列化 — 合并调度器运行时状态（下次执行时间）"""
    handler_def = get_handler_def(job.handler)
    runtime = scheduler_manager.scheduler.get_job(str(job.id)) \
        if scheduler_manager.scheduler.running else None
    next_run = _format_datetime(runtime.next_run_time) if runtime else None
    try:
        params = json.loads(job.params or '{}')
    except (TypeError, ValueError):
        params = {}
    if job.schedule_type == 'interval':
        schedule_desc = f'每 {job.interval_seconds} 秒'
    else:
        schedule_desc = f'cron({job.cron_expr})'
    return {
        'id': job.id,
        'name': job.name,
        'handler': job.handler,
        'handler_label': handler_def['label'] if handler_def else job.handler,
        'handler_registered': handler_def is not None,
        'schedule_type': job.schedule_type,
        'cron_expr': job.cron_expr,
        'interval_seconds': job.interval_seconds,
        'schedule_desc': schedule_desc,
        'params': params,
        'status': job.status,
        'is_system': bool(job.is_system),
        'description': job.description,
        'misfire_grace_time': job.misfire_grace_time,
        'max_instances': job.max_instances,
        'last_run_at': _format_datetime(job.last_run_at),
        'last_run_status': job.last_run_status,
        'last_run_duration_ms': job.last_run_duration_ms,
        'next_run_time': next_run,
        'created_at': _format_datetime(job.created_at),
        'updated_at': _format_datetime(job.updated_at),
    }


def _get_job_or_404(job_id: int) -> SchedulerJob:
    with session_scope() as db:
        job = db.query(SchedulerJob).filter(SchedulerJob.id == job_id).first()
        if job is None:
            raise HTTPException(status_code=404, detail='任务不存在')
        db.expunge(job)
        return job


# ── 任务 CRUD ─────────────────────────────────────────────────

@router.get('/jobs')
@limiter.limit(LIMIT_READ)
def list_jobs(request: Request, user: AdminUser):
    """任务列表 + 调度器运行状态"""
    with session_scope() as db:
        jobs = db.query(SchedulerJob).order_by(SchedulerJob.is_system.desc(),
                                               SchedulerJob.id).all()
        for obj in jobs:
            db.expunge(obj)
    return {
        'running': scheduler_manager.scheduler.running,
        'timezone': 'Asia/Shanghai',
        'items': [_job_item(job) for job in jobs],
    }


@router.post('/jobs')
@limiter.limit(LIMIT_WRITE)
def create_job(request: Request, data: JobUpsertRequest, user: AdminUser):
    """新增定时任务 — 立即注册到调度器"""
    if get_handler_def(data.handler) is None:
        raise HTTPException(status_code=400, detail=f'未注册的处理器: {data.handler}')
    _validate_schedule(data)
    try:
        params = validate_params(data.handler, data.params)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    with session_scope() as db:
        if db.query(SchedulerJob).filter(SchedulerJob.name == data.name.strip()).first():
            raise HTTPException(status_code=400, detail=f'任务名称已存在: {data.name}')
        job = SchedulerJob(
            name=data.name.strip(),
            handler=data.handler,
            schedule_type=data.schedule_type,
            cron_expr=(data.cron_expr or '').strip() if data.schedule_type == 'cron' else '',
            interval_seconds=data.interval_seconds if data.schedule_type == 'interval' else 0,
            params=json.dumps(params, ensure_ascii=False),
            status='enabled',
            is_system=False,
            description=data.description,
            misfire_grace_time=data.misfire_grace_time,
            max_instances=data.max_instances,
        )
        db.add(job)
        db.flush()
        db.refresh(job)
        db.expunge(job)
    scheduler_manager.reload_job(job)
    log_audit(user, 'create_scheduler_job', f'job={job.id} name={job.name}')
    return {'success': True, 'message': f'任务已创建并启用：{job.name}', 'id': job.id}


@router.put('/jobs/{job_id}')
@limiter.limit(LIMIT_WRITE)
def update_job(request: Request, job_id: int, data: JobUpsertRequest, user: AdminUser):
    """修改任务定义 — 立即同步调度器（修改参数/调度计划即时生效）"""
    _get_job_or_404(job_id)
    if get_handler_def(data.handler) is None:
        raise HTTPException(status_code=400, detail=f'未注册的处理器: {data.handler}')
    _validate_schedule(data)
    try:
        params = validate_params(data.handler, data.params)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    with session_scope() as db:
        row = db.query(SchedulerJob).filter(SchedulerJob.id == job_id).first()
        if row is None:
            raise HTTPException(status_code=404, detail='任务不存在')
        dup = db.query(SchedulerJob).filter(
            SchedulerJob.name == data.name.strip(),
            SchedulerJob.id != job_id).first()
        if dup:
            raise HTTPException(status_code=400, detail=f'任务名称已存在: {data.name}')
        row.name = data.name.strip()
        row.handler = data.handler
        row.schedule_type = data.schedule_type
        row.cron_expr = (data.cron_expr or '').strip() if data.schedule_type == 'cron' else ''
        row.interval_seconds = data.interval_seconds if data.schedule_type == 'interval' else 0
        row.params = json.dumps(params, ensure_ascii=False)
        row.description = data.description
        row.misfire_grace_time = data.misfire_grace_time
        row.max_instances = data.max_instances
        db.flush()
        db.refresh(row)
        db.expunge(row)
    scheduler_manager.reload_job(row)
    log_audit(user, 'update_scheduler_job', f'job={job_id} name={row.name}')
    return {'success': True, 'message': f'任务已更新：{row.name}'}


@router.delete('/jobs/{job_id}')
@limiter.limit(LIMIT_WRITE)
def delete_job(request: Request, job_id: int, user: AdminUser):
    """删除任务 — 系统内置任务禁止删除；执行日志保留可查"""
    job = _get_job_or_404(job_id)
    if job.is_system:
        raise HTTPException(status_code=400, detail='系统内置任务不可删除，如需停用请选择「暂停」')
    scheduler_manager.remove_job(job)
    with session_scope() as db:
        row = db.query(SchedulerJob).filter(SchedulerJob.id == job_id).first()
        if row is not None:
            db.delete(row)
    log_audit(user, 'delete_scheduler_job', f'job={job_id} name={job.name}')
    return {'success': True, 'message': f'任务已删除：{job.name}'}


# ── 执行控制 ──────────────────────────────────────────────────

@router.post('/jobs/{job_id}/run')
@limiter.limit(LIMIT_WRITE)
def run_job(request: Request, job_id: int, user: AdminUser):
    """手动执行一次 — 异步触发，结果在执行日志中查看"""
    job = _get_job_or_404(job_id)
    if get_handler_def(job.handler) is None:
        raise HTTPException(status_code=400, detail=f'处理器已失效: {job.handler}')
    if not scheduler_manager.trigger_job(job_id):
        raise HTTPException(status_code=503, detail='调度器尚未启动')
    log_audit(user, 'run_scheduler_job', f'job={job_id} name={job.name}')
    return {'success': True, 'message': f'已触发执行：{job.name}（结果请查看执行日志）'}


@router.post('/jobs/{job_id}/pause')
@limiter.limit(LIMIT_WRITE)
def pause_job(request: Request, job_id: int, user: AdminUser):
    """暂停任务 — 从调度器摘除，定义保留"""
    job = _get_job_or_404(job_id)
    with session_scope() as db:
        row = db.query(SchedulerJob).filter(SchedulerJob.id == job_id).first()
        if row is not None:
            row.status = 'paused'
            db.flush()
            db.refresh(row)
            db.expunge(row)
    scheduler_manager.reload_job(row)
    log_audit(user, 'pause_scheduler_job', f'job={job_id} name={job.name}')
    return {'success': True, 'message': f'任务已暂停：{job.name}'}


@router.post('/jobs/{job_id}/resume')
@limiter.limit(LIMIT_WRITE)
def resume_job(request: Request, job_id: int, user: AdminUser):
    """恢复任务 — 重新注册到调度器"""
    job = _get_job_or_404(job_id)
    with session_scope() as db:
        row = db.query(SchedulerJob).filter(SchedulerJob.id == job_id).first()
        if row is not None:
            row.status = 'enabled'
            db.flush()
            db.refresh(row)
            db.expunge(row)
    scheduler_manager.reload_job(row)
    log_audit(user, 'resume_scheduler_job', f'job={job_id} name={job.name}')
    return {'success': True, 'message': f'任务已恢复：{job.name}'}


# ── 执行日志 ──────────────────────────────────────────────────

@router.get('/logs')
@limiter.limit(LIMIT_READ)
def list_job_logs(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    job_id: Optional[int] = Query(None, description='按任务过滤，缺省查全部'),
    status: Optional[str] = Query(None, pattern='^(running|success|failed)$'),
    user: AdminUser = None,
):
    """执行日志（分页，可按任务/状态过滤）"""
    offset = (page - 1) * page_size
    with session_scope(logs=True) as db:
        q = db.query(SchedulerJobLog)
        if job_id is not None:
            q = q.filter(SchedulerJobLog.job_id == job_id)
        if status:
            q = q.filter(SchedulerJobLog.status == status)
        total = q.count()
        rows = (q.order_by(SchedulerJobLog.id.desc())
                 .offset(offset).limit(page_size).all())
        return {
            'total': total,
            'page': page,
            'page_size': page_size,
            'items': [
                {
                    'id': r.id,
                    'job_id': r.job_id,
                    'job_name': r.job_name,
                    'handler': r.handler,
                    'params': r.params,
                    'trigger': r.trigger,
                    'status': r.status,
                    'error_message': r.error_message,
                    'result_summary': r.result_summary,
                    'started_at': _format_datetime(r.started_at),
                    'finished_at': _format_datetime(r.finished_at),
                    'duration_ms': r.duration_ms,
                }
                for r in rows
            ],
        }


@router.delete('/logs')
@limiter.limit(LIMIT_WRITE)
def clear_job_logs(
    request: Request,
    job_id: Optional[int] = Query(None, description='只清空指定任务的日志，缺省清空全部'),
    user: AdminUser = None,
):
    """清空执行日志 — 可选按任务过滤"""
    with session_scope(logs=True) as db:
        q = db.query(SchedulerJobLog)
        if job_id is not None:
            q = q.filter(SchedulerJobLog.job_id == job_id)
        deleted = q.delete(synchronize_session=False)
    log_audit(user, 'clear_scheduler_job_logs', f'job={job_id} deleted={deleted}')
    return {'success': True, 'message': f'已清空 {deleted} 条执行日志'}


# ── 处理器与 cron 预览 ────────────────────────────────────────

@router.get('/handlers')
@limiter.limit(LIMIT_READ)
def list_job_handlers(request: Request, user: AdminUser):
    """可用处理器清单（含参数 schema，供新增/修改任务表单使用）"""
    return {'items': list_handlers()}


@router.post('/cron-preview')
@limiter.limit(LIMIT_READ)
def cron_preview(request: Request, body: dict, user: AdminUser = None):
    """cron 表达式校验 + 下次 5 次执行时间预览（前端实时提示）"""
    expr = str((body or {}).get('cron_expr', '')).strip()
    if not expr:
        raise HTTPException(status_code=400, detail='cron 表达式不能为空')
    try:
        trigger = CronTrigger.from_crontab(expr, timezone=BEIJING_TZ)
    except ValueError as exc:
        raise HTTPException(status_code=400,
                            detail=f'cron 表达式不合法（格式：分 时 日 月 周）：{exc}')
    next_times = []
    current = now_beijing()
    fire_time = trigger.get_next_fire_time(None, current)
    for _ in range(5):
        if fire_time is None:
            break
        next_times.append(_format_datetime(fire_time))
        fire_time = trigger.get_next_fire_time(fire_time, fire_time)
    return {'valid': True, 'next_run_times': next_times}
