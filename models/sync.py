# -*- coding: UTF-8 -*-
"""元数据同步模型 — 数据源 + 同步任务 + 执行历史 + 变更记录

架构层次：
    DataSource (外部数据库连接配置)
        └── SyncJobConfig (同步任务：数据源 → 目标 schema)
                └── SyncRunLog (每次执行的历史记录)
                        └── SchemaChangeLog (检测到的变更明细)

变更审批流程：
    - 新增表/字段 → auto_applied（自动应用 + 自动分类敏感等级）
    - 修改字段类型 → auto_applied（自动更新 + 记录变更）
    - 删除表/字段 → pending（需管理员审批后才执行删除）
    - 管理员拒绝删除 → ignored（保留元数据，标记源库已移除）
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, UniqueConstraint
from models.base import MainBase


class DataSource(MainBase):
    """外部数据源 — 连接配置（密码加密存储，只读账号）"""
    __tablename__ = 'data_sources'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    name = Column(String(100), unique=True, nullable=False, comment='数据源名称')
    db_type = Column(String(30), nullable=False, comment='数据库类型: mysql/postgresql/sqlite/...')
    host = Column(String(200), default='localhost', comment='主机地址')
    port = Column(Integer, default=3306, comment='端口')
    database = Column(String(200), default='', comment='数据库名/schema名')
    username = Column(String(100), default='', comment='连接用户名(应只读)')
    password_enc = Column(Text, default='', comment='加密的密码(enc::前缀)')
    extra_params = Column(Text, default='{}', comment='额外连接参数(JSON)')
    status = Column(String(20), default='active', comment='状态: active/inactive/error')
    last_error = Column(Text, default='', comment='最近一次连接错误')
    last_tested_at = Column(DateTime, comment='最后测试时间')
    created_by = Column(Integer, ForeignKey('users.id'), nullable=True, comment='创建者')
    created_at = Column(DateTime, default=datetime.now, comment='创建时间')
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')


class SyncJobConfig(MainBase):
    """同步任务配置 — 定义从哪个数据源同步到本系统的哪个 schema"""
    __tablename__ = 'sync_job_configs'
    __table_args__ = (UniqueConstraint('datasource_id', 'target_schema_name', name='uix_sync_job_ds_schema'),)
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    datasource_id = Column(Integer, ForeignKey('data_sources.id'), nullable=False, index=True, comment='数据源ID')
    target_schema_name = Column(String(100), nullable=False, comment='同步到本系统的 schema 名')
    sync_mode = Column(String(20), default='full', comment='同步模式: full(全量)')
    schedule_type = Column(String(20), default='interval', comment='调度类型: interval/cron/manual')
    schedule_value = Column(String(100), default='360', comment='调度值: interval分钟数 / cron表达式')
    is_enabled = Column(Boolean, default=True, comment='是否启用')
    auto_classify = Column(Boolean, default=True, comment='自动分类新字段敏感等级')
    include_tables = Column(Text, default='', comment='包含的表名(逗号分隔,空=全部)')
    exclude_tables = Column(Text, default='', comment='排除的表名(逗号分隔)')
    last_synced_at = Column(DateTime, comment='最后同步时间')
    last_sync_status = Column(String(20), default='', comment='最后同步状态: success/failed/running')
    created_at = Column(DateTime, default=datetime.now, comment='创建时间')
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')


class SyncRunLog(MainBase):
    """同步执行历史 — 每次同步运行的完整记录"""
    __tablename__ = 'sync_run_logs'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    job_id = Column(Integer, ForeignKey('sync_job_configs.id'), nullable=False, index=True, comment='同步任务ID')
    triggered_by = Column(String(50), default='scheduler', comment='触发者: scheduler/manual/<username>')
    started_at = Column(DateTime, default=datetime.now, comment='开始时间')
    finished_at = Column(DateTime, comment='结束时间')
    status = Column(String(20), default='running', comment='状态: running/success/failed')
    tables_total = Column(Integer, default=0, comment='源库表总数')
    tables_synced = Column(Integer, default=0, comment='本次同步表数')
    columns_added = Column(Integer, default=0, comment='新增字段数')
    columns_modified = Column(Integer, default=0, comment='修改字段数')
    columns_removed = Column(Integer, default=0, comment='删除字段数(待审批)')
    changes_auto = Column(Integer, default=0, comment='自动应用变更数')
    changes_pending = Column(Integer, default=0, comment='待审批变更数')
    error_message = Column(Text, default='', comment='错误信息')
    duration_ms = Column(Integer, default=0, comment='耗时(毫秒)')
    summary = Column(Text, default='', comment='摘要(JSON): 变更详情')


class SchemaChangeLog(MainBase):
    """Schema 变更记录 — 检测到的每次变更明细"""
    __tablename__ = 'schema_change_logs'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    run_log_id = Column(Integer, ForeignKey('sync_run_logs.id'), nullable=False, index=True, comment='同步执行ID')
    job_id = Column(Integer, ForeignKey('sync_job_configs.id'), nullable=False, index=True, comment='同步任务ID')
    datasource_id = Column(Integer, ForeignKey('data_sources.id'), nullable=False, index=True, comment='数据源ID')
    target_schema_name = Column(String(100), nullable=False, comment='目标 schema 名')
    change_type = Column(String(20), nullable=False, comment='变更类型: add/modify/remove')
    object_type = Column(String(20), nullable=False, comment='对象类型: table/column')
    object_name = Column(String(300), nullable=False, comment='对象全名(table.column)')
    old_value = Column(Text, default='', comment='旧值(JSON)')
    new_value = Column(Text, default='', comment='新值(JSON)')
    auto_classified_level = Column(String(20), default='', comment='自动分类的敏感等级(仅新增字段)')
    approval_status = Column(String(20), default='auto_applied',
                             comment='审批状态: auto_applied/pending/approved/rejected/ignored')
    approved_by = Column(Integer, nullable=True, comment='审批人ID')
    approved_at = Column(DateTime, nullable=True, comment='审批时间')
    created_at = Column(DateTime, default=datetime.now, index=True, comment='创建时间')
