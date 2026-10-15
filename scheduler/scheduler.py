# -*- coding: UTF-8 -*-
"""调度器管理 — 数据库驱动的动态定时任务（参考 RuoYi / XXL-JOB 任务中心）

架构：
    scheduler_jobs 表（任务定义，页面可增删改）
        └── SchedulerManager 启动时全量加载 enabled 任务注册到 APScheduler
                └── _execute_db_job 执行器：解析 registry 处理器 → 执行
                        └── scheduler_job_logs 表（每次执行记录）+ 回写任务最近状态

与旧版（硬编码 add_job）的差异：
    - 任务定义持久化在主库，重启不丢，页面可动态新增/修改/删除/暂停/恢复
    - 系统内置任务（清理/聚合/同步巡检）以种子数据形式写入，is_system=1
      不可删除但可调整调度、参数、暂停恢复
    - 每次执行（含手动执行一次）落执行日志，便于排查
"""
import json
import traceback

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.logger import logger
from app.timezone import BEIJING_TZ, now_beijing
from crud.base import session_scope
from models.scheduler import SchedulerJob, SchedulerJobLog
from scheduler.registry import get_handler_def, validate_params

# 系统内置任务种子 — 幂等播种（按 name 判存在），is_system=1 不可删除
SYSTEM_JOB_SEEDS = [
    {
        'name': 'LLM 用量聚合',
        'handler': 'aggregate_usage',
        'schedule_type': 'interval',
        'interval_seconds': 3600,
        'params': {'days_back': 7},
        'description': '每小时聚合 LLM 用量到 llm_usage_stats（回溯 7 天幂等覆盖）',
    },
    {
        'name': '遥测数据清理',
        'handler': 'cleanup_telemetry',
        'schedule_type': 'cron',
        'cron_expr': '0 3 * * *',
        'params': {'retention_days': 90},
        'description': '每天 03:00 清理过期遥测数据（默认保留 90 天）',
    },
    {
        'name': '日志库清理',
        'handler': 'cleanup_logs_db',
        'schedule_type': 'cron',
        'cron_expr': '10 3 * * *',
        'params': {'audit_retention_days': 90, 'sync_retention_days': 90},
        'description': '每天 03:10 清理日志库过期数据（审计/同步历史，默认 90 天）',
    },
    {
        'name': '主库数据清理',
        'handler': 'cleanup_main_db',
        'schedule_type': 'cron',
        'cron_expr': '30 3 * * *',
        'params': {'result_retention_days': 30},
        'description': '每天 03:30 清空主库过期查询结果 JSON（默认 30 天）',
    },
    {
        'name': 'WAL 日志回收',
        'handler': 'wal_checkpoint',
        'schedule_type': 'cron',
        'cron_expr': '0 4 * * *',
        'params': {},
        'description': '每天 04:00 对 SQLite 主库执行 WAL checkpoint',
    },
    {
        'name': '同步任务调度巡检',
        'handler': 'run_scheduled_syncs',
        'schedule_type': 'interval',
        'interval_seconds': 600,
        'params': {},
        'description': '每 10 分钟巡检并执行到期的元数据同步任务',
    },
    {
        'name': '向量索引重建',
        'handler': 'rebuild_vector_index',
        'schedule_type': 'interval',
        'interval_seconds': 3600,
        'params': {},
        'description': '每小时检查全库向量索引，stale/error/缺失 时按需重建（导入/同步不再自动构建）',
    },
]

MIN_INTERVAL_SECONDS = 10  # 间隔调度下限，防止误配置打爆调度器


def _build_trigger(job: SchedulerJob):
    """按任务定义构造 APScheduler 触发器 — 配置非法抛 ValueError"""
    if job.schedule_type == 'cron':
        expr = (job.cron_expr or '').strip()
        if not expr:
            raise ValueError('cron 表达式不能为空')
        return CronTrigger.from_crontab(expr, timezone=BEIJING_TZ)
    if job.schedule_type == 'interval':
        seconds = int(job.interval_seconds or 0)
        if seconds < MIN_INTERVAL_SECONDS:
            raise ValueError(f'间隔不能小于 {MIN_INTERVAL_SECONDS} 秒')
        return IntervalTrigger(seconds=seconds, timezone=BEIJING_TZ)
    raise ValueError(f'不支持的调度类型: {job.schedule_type}')


def execute_db_job(job_id: int, trigger: str = 'scheduler'):
    """定时任务执行器 — 按 job_id 加载最新定义并执行，全程落执行日志

    每次触发都从数据库读最新配置：修改参数后无需重启即生效。
    """
    # 1. 读取任务定义（快照，避免长事务内执行任务函数）
    with session_scope() as db:
        job = db.query(SchedulerJob).filter(SchedulerJob.id == job_id).first()
        if job is None:
            logger.warning(f"定时任务 #{job_id} 已不存在，跳过执行")
            return
        snapshot = {
            'name': job.name,
            'handler': job.handler,
            'params': job.params or '{}',
        }

    # 2. 解析处理器与参数
    handler_def = get_handler_def(snapshot['handler'])
    error_message = ''
    result_summary = ''
    started_at = now_beijing()
    try:
        if handler_def is None:
            raise ValueError(f'未注册的处理器: {snapshot["handler"]}（可能已被移除）')
        params = validate_params(snapshot['handler'], json.loads(snapshot['params']))
    except Exception as exc:
        # 定义即非法：直接失败，不调用处理器
        params = None
        error_message = str(exc)
        result_summary = ''

    status = 'running'
    if params is not None:
        # 3. 执行处理器（同步函数，APScheduler 在线程池中运行）
        try:
            result = handler_def['func'](**params)
            status = 'success'
            try:
                result_summary = json.dumps(result, ensure_ascii=False, default=str)
            except Exception:
                result_summary = ''
        except Exception as exc:
            status = 'failed'
            error_message = ''.join(traceback.format_exception(exc)[-5:])
            logger.error(f"定时任务 [{snapshot['name']}] 执行失败: {exc}")

    finished_at = now_beijing()
    duration_ms = int((finished_at - started_at).total_seconds() * 1000)

    # 4. 落执行日志（日志库）+ 回写任务最近状态（主库）
    with session_scope(logs=True) as db:
        db.add(SchedulerJobLog(
            job_id=job_id,
            job_name=snapshot['name'],
            handler=snapshot['handler'],
            params=snapshot['params'],
            trigger=trigger,
            status=status,
            error_message=error_message,
            result_summary=result_summary,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
        ))
    with session_scope() as db:
        job = db.query(SchedulerJob).filter(SchedulerJob.id == job_id).first()
        if job is not None:
            job.last_run_at = finished_at
            job.last_run_status = status
            job.last_run_duration_ms = duration_ms
    logger.info(f"定时任务 [{snapshot['name']}] 执行完成: {status} ({duration_ms}ms)")


class SchedulerManager:
    def __init__(self):
        self.scheduler = AsyncIOScheduler(timezone=BEIJING_TZ)

    def init_scheduler(self):
        """播种系统内置任务 + 从数据库加载全部启用任务"""
        self._seed_system_jobs()
        self._load_jobs_from_db()

    def _seed_system_jobs(self):
        """幂等播种系统内置任务 — 按 name 判存在，已存在不覆盖用户改动"""
        created = 0
        with session_scope() as db:
            for seed in SYSTEM_JOB_SEEDS:
                if db.query(SchedulerJob).filter(SchedulerJob.name == seed['name']).first():
                    continue
                db.add(SchedulerJob(
                    name=seed['name'],
                    handler=seed['handler'],
                    schedule_type=seed['schedule_type'],
                    cron_expr=seed.get('cron_expr', ''),
                    interval_seconds=seed.get('interval_seconds', 0),
                    params=json.dumps(seed.get('params', {}), ensure_ascii=False),
                    status='enabled',
                    is_system=True,
                    description=seed.get('description', ''),
                ))
                created += 1
        if created:
            logger.info(f"已播种 {created} 个系统内置定时任务")

    def _load_jobs_from_db(self):
        """加载全部 enabled 任务到 APScheduler — 单个任务配置非法不影响其他任务"""
        with session_scope() as db:
            jobs = db.query(SchedulerJob).filter(SchedulerJob.status == 'enabled').all()
            for obj in jobs:
                db.expunge(obj)
        ok = 0
        for job in jobs:
            try:
                self._register(job)
                ok += 1
            except Exception as e:
                logger.error(f"定时任务 [{job.name}] 注册失败（配置非法，已跳过）: {e}")
        logger.info(f"已从数据库注册 {ok}/{len(jobs)} 个定时任务")

    def _register(self, job: SchedulerJob):
        """把任务定义注册到 APScheduler（触发器配置非法抛异常）"""
        self.scheduler.add_job(
            execute_db_job,
            trigger=_build_trigger(job),
            args=[job.id],
            id=str(job.id),
            name=job.name,
            misfire_grace_time=job.misfire_grace_time or 60,
            max_instances=max(1, int(job.max_instances or 1)),
            replace_existing=True,
        )

    # ── 动态管理（供路由层调用）────────────────────────────────

    def reload_job(self, job: SchedulerJob):
        """新增/修改任务后同步调度器 — enabled 注册，paused 移除"""
        if not self.scheduler.running:
            return
        if self.scheduler.get_job(str(job.id)):
            self.scheduler.remove_job(str(job.id))
        if job.status == 'enabled':
            self._register(job)
            logger.info(f"定时任务 [{job.name}] 已同步到调度器")
        else:
            logger.info(f"定时任务 [{job.name}] 已从调度器移除（暂停）")

    def remove_job(self, job: SchedulerJob):
        """删除任务后从调度器摘除"""
        if self.scheduler.running and self.scheduler.get_job(str(job.id)):
            self.scheduler.remove_job(str(job.id))
            logger.info(f"定时任务 [{job.name}] 已从调度器移除（删除）")

    def trigger_job(self, job_id: int) -> bool:
        """手动执行一次 — 独立的一次性任务，与调度计划互不影响"""
        if not self.scheduler.running:
            return False
        self.scheduler.add_job(
            execute_db_job,
            trigger='date',
            run_date=now_beijing(),
            args=[job_id, 'manual'],
            id=f'manual_{job_id}',
            replace_existing=True,
        )
        return True

    def start(self):
        self.scheduler.start()
        logger.info("调度器已启动")

    def shutdown(self):
        self.scheduler.shutdown(wait=False)
        logger.info("调度器已关闭")


scheduler_manager = SchedulerManager()
