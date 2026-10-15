# -*- coding: UTF-8 -*-
"""定时任务模型 — 动态任务定义（主库）+ 执行日志（日志库）

参考 RuoYi / XXL-JOB 的「任务中心」设计：
    SchedulerJob (任务定义，主库)
        └── SchedulerJobLog (每次执行的记录，日志库)

任务调度流程：
    - 管理员在页面上增/删/改任务 → 写入 scheduler_jobs → 同步到 APScheduler
    - 调度器按 cron / interval 触发执行器 → 处理器从 registry 按名解析
    - 每次执行（含手动执行）写入 scheduler_job_logs，回写任务最近执行状态

库归属说明：SchedulerJobLog 为追加型高频写日志，拆至日志库（logs.db）。
跨库引用（job_id → scheduler_jobs.id）降级为普通索引列，删除任务时
由 crud/路由层保留日志（历史可查）或显式清理。
"""
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, UniqueConstraint

from app.timezone import now_beijing
from models.base import LogsBase, MainBase


class SchedulerJob(MainBase):
    """定时任务定义 — 数据库持久化，支持页面动态增删改"""
    __tablename__ = 'scheduler_jobs'
    __table_args__ = (UniqueConstraint('name', name='uix_scheduler_job_name'),)
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    name = Column(String(100), nullable=False, comment='任务名称(唯一)')
    handler = Column(String(100), nullable=False, index=True, comment='处理器标识(registry 注册名)')
    schedule_type = Column(String(20), default='cron', comment='调度类型: cron/interval')
    cron_expr = Column(String(100), default='', comment='cron 表达式(分 时 日 月 周)')
    interval_seconds = Column(Integer, default=0, comment='间隔秒数(schedule_type=interval 时生效)')
    params = Column(Text, default='{}', comment='任务参数(JSON,键值对)')
    status = Column(String(20), default='enabled', index=True, comment='状态: enabled/paused')
    is_system = Column(Boolean, default=False, comment='系统内置任务(不可删除)')
    misfire_grace_time = Column(Integer, default=60, comment='错过触发的宽限秒数')
    max_instances = Column(Integer, default=1, comment='同一任务最大并发实例数')
    description = Column(String(300), default='', comment='任务描述')
    last_run_at = Column(DateTime, comment='最近执行时间')
    last_run_status = Column(String(20), default='', comment='最近执行状态: success/failed')
    last_run_duration_ms = Column(Integer, default=0, comment='最近执行耗时(毫秒)')
    created_at = Column(DateTime, default=now_beijing, comment='创建时间（北京时间）')
    updated_at = Column(DateTime, default=now_beijing, onupdate=now_beijing, comment='更新时间（北京时间）')


class SchedulerJobLog(LogsBase):
    """定时任务执行日志 — 每次执行（含手动触发）的完整记录（日志库）"""
    __tablename__ = 'scheduler_job_logs'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    job_id = Column(Integer, nullable=False, index=True, comment='任务ID(跨库引用scheduler_jobs.id)')
    job_name = Column(String(100), default='', comment='任务名称(冗余,任务删除后日志仍可读)')
    handler = Column(String(100), default='', comment='处理器标识')
    params = Column(Text, default='{}', comment='本次执行的参数(JSON)')
    trigger = Column(String(20), default='scheduler', comment='触发方式: scheduler/manual')
    status = Column(String(20), default='running', index=True, comment='状态: running/success/failed')
    error_message = Column(Text, default='', comment='失败原因(含堆栈)')
    result_summary = Column(Text, default='', comment='执行结果摘要(JSON)')
    started_at = Column(DateTime, default=now_beijing, comment='开始时间（北京时间）')
    finished_at = Column(DateTime, comment='结束时间')
    duration_ms = Column(Integer, default=0, comment='耗时(毫秒)')
