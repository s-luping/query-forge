"""系统定时任务监控与控制接口。"""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from app.auth import AdminUser
from app.limiter import LIMIT_READ, LIMIT_WRITE, limiter
from app.logger import log_audit
from app.timezone import BEIJING_TZ
from scheduler.scheduler import scheduler_manager

router = APIRouter()

_JOB_LABELS = {
    'aggregate_usage': 'LLM 用量聚合',
    'cleanup_telemetry': '遥测数据清理',
    'cleanup_main_db': '主库数据清理',
    'wal_checkpoint': 'WAL 日志回收',
    'run_scheduled_syncs': '同步任务调度巡检',
}


def _format_datetime(value) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=BEIJING_TZ)
    return value.astimezone(BEIJING_TZ).strftime('%Y-%m-%d %H:%M:%S')


def _job_item(job):
    return {
        'id': job.id,
        'name': _JOB_LABELS.get(job.id, job.name or job.id),
        'job_id': job.id,
        'function': job.func_ref or getattr(job.func, '__name__', ''),
        'trigger': str(job.trigger),
        'next_run_time': _format_datetime(job.next_run_time),
        'pending': bool(job.pending),
        'paused': job.next_run_time is None,
        'misfire_grace_time': job.misfire_grace_time,
        'max_instances': job.max_instances,
    }


@router.get('/tasks')
@limiter.limit(LIMIT_READ)
def list_scheduler_tasks(request: Request, user: AdminUser):
    """列出系统 APScheduler 任务。"""
    scheduler = scheduler_manager.scheduler
    return {
        'running': scheduler.running,
        'timezone': 'Asia/Shanghai',
        'items': [_job_item(job) for job in scheduler.get_jobs()],
    }


@router.post('/tasks/{job_id}/run')
@limiter.limit(LIMIT_WRITE)
def run_scheduler_task(request: Request, job_id: str, user: AdminUser):
    scheduler = scheduler_manager.scheduler
    if not scheduler.running:
        raise HTTPException(status_code=503, detail='调度器尚未启动')
    if scheduler.get_job(job_id) is None:
        raise HTTPException(status_code=404, detail='定时任务不存在')
    job = scheduler.get_job(job_id)
    scheduler.add_job(
        job.func,
        trigger='date',
        run_date=datetime.now(BEIJING_TZ) + timedelta(seconds=1),
        id=f'{job_id}_manual',
        replace_existing=True,
        kwargs=job.kwargs,
    )
    log_audit(user, 'run_scheduler_task', f'job={job_id}')
    return {'success': True, 'message': f'已触发任务：{_JOB_LABELS.get(job_id, job_id)}'}


@router.post('/tasks/{job_id}/pause')
@limiter.limit(LIMIT_WRITE)
def pause_scheduler_task(request: Request, job_id: str, user: AdminUser):
    scheduler = scheduler_manager.scheduler
    if scheduler.get_job(job_id) is None:
        raise HTTPException(status_code=404, detail='定时任务不存在')
    scheduler.pause_job(job_id)
    log_audit(user, 'pause_scheduler_task', f'job={job_id}')
    return {'success': True, 'message': '任务已暂停'}


@router.post('/tasks/{job_id}/resume')
@limiter.limit(LIMIT_WRITE)
def resume_scheduler_task(request: Request, job_id: str, user: AdminUser):
    scheduler = scheduler_manager.scheduler
    if scheduler.get_job(job_id) is None:
        raise HTTPException(status_code=404, detail='定时任务不存在')
    scheduler.resume_job(job_id)
    log_audit(user, 'resume_scheduler_task', f'job={job_id}')
    return {'success': True, 'message': '任务已恢复'}
