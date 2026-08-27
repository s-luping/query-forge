# -*- coding: UTF-8 -*-
"""定时元数据同步 — 每 10 分钟检查所有启用的同步任务

调度策略：
    - interval 类型：schedule_value 为分钟数，检查距 last_synced_at（上次尝试时间，
      成功或失败都会更新）是否已过间隔
    - cron 类型：暂不支持自动调度（可通过手动触发）
    - manual 类型：仅手动触发

到期判定语义：interval = 距上次同步尝试至少间隔 N 分钟，之后在下一个 10 分钟
巡检点触发（因此实际最小执行粒度为 10 分钟）。

执行方式：到期任务在独立后台线程执行，不阻塞调度器事件循环（源库读取可能
耗时数分钟，若在事件循环内同步执行会卡死所有 HTTP 请求）。
"""
import threading
from datetime import timedelta

from app.logger import logger
from app.timezone import now_beijing

# running 状态超过该时长无结果视为僵死（进程崩溃残留），允许重新调度
STALE_RUNNING_HOURS = 6


def run_scheduled_syncs():
    """检查并执行所有到期的同步任务"""
    from crud.base import session_scope
    from models.sync import SyncJobConfig

    try:
        due_job_ids = _collect_due_jobs()
        if not due_job_ids:
            return
        logger.info(f"定时同步: {len(due_job_ids)} 个任务到期")

        # 线程在会话提交（running 状态落库）之后启动，避免竞态覆盖执行结果
        for job_id in due_job_ids:
            t = threading.Thread(target=_run_job_safely, args=(job_id,),
                                 daemon=True, name=f"sync-job-{job_id}")
            t.start()
    except Exception as e:
        logger.error(f"定时同步检查失败: {e}", exc_info=True)


def _collect_due_jobs() -> list:
    """筛选到期任务并原子地标记 running（提交后才派发线程）"""
    from crud.base import session_scope
    from models.sync import SyncJobConfig

    with session_scope() as db:
        jobs = db.query(SyncJobConfig).filter(
            SyncJobConfig.is_enabled == True,
            SyncJobConfig.schedule_type == 'interval',
        ).all()

        if not jobs:
            return []

        now = now_beijing()
        due_ids = []

        for job in jobs:
            try:
                interval_minutes = int(job.schedule_value)
            except (ValueError, TypeError):
                logger.warning(f"同步任务 {job.id} schedule_value 无效: {job.schedule_value}")
                continue
            if interval_minutes < 1:
                logger.warning(f"同步任务 {job.id} 间隔无效（<1 分钟）: {job.schedule_value}")
                continue

            # 正在执行的任务跳过；超过阈值仍 running 视为进程崩溃残留，放行重试
            if job.last_sync_status == 'running':
                if (job.last_synced_at is None
                        or now - job.last_synced_at <= timedelta(hours=STALE_RUNNING_HOURS)):
                    continue
                logger.warning(f"同步任务 {job.id} running 状态超过 {STALE_RUNNING_HOURS} 小时，按僵死处理重新调度")

            # reference_time 为上次尝试时间（成功/失败均更新）；新建任务按创建时间
            # 计算首个周期，避免第一次巡检绕过用户配置的 interval。
            reference_time = job.last_synced_at or job.created_at
            if reference_time and now - reference_time >= timedelta(minutes=interval_minutes):
                # 先标记 running 并随会话提交落库，防止下个巡检周期重复派发
                job.last_sync_status = 'running'
                due_ids.append(job.id)

        return due_ids


def _run_job_safely(job_id: int):
    """后台线程执行单个同步任务（会话与调度巡检完全隔离）"""
    from crud.base import session_scope
    from models.sync import SyncJobConfig
    from models.datasource import DataSource
    from services.sync_engine import SyncEngine

    try:
        with session_scope() as db:
            job = db.query(SyncJobConfig).filter(
                SyncJobConfig.id == job_id).first()
            ds = db.query(DataSource).filter(
                DataSource.id == job.datasource_id).first() if job else None
            if not job or not ds:
                logger.warning(f"同步任务 {job_id} 或其数据源不存在，跳过")
                return
            db.expunge(job)
            db.expunge(ds)

        engine = SyncEngine(job, ds, triggered_by='scheduler')
        engine.run()
    except Exception as e:
        logger.error(f"同步任务 {job_id} 执行失败: {e}", exc_info=True)
        # 兜底：异常逃出 engine 时也复位状态并推进尝试时间，避免下轮巡检立刻重试
        try:
            from crud.base import tx_scope
            with tx_scope() as db:
                from models.sync import SyncJobConfig as _J
                row = db.query(_J).filter(_J.id == job_id).first()
                if row and row.last_sync_status == 'running':
                    row.last_sync_status = 'failed'
                    row.last_synced_at = now_beijing()
                db.commit()
        except Exception as e2:
            logger.error(f"同步任务 {job_id} 状态复位失败: {e2}")
