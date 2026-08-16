"""安全模型 — 字段级权限 + 行级过滤 + 查询审计

权限三级模型：
    SELECT  — 完全可读，可出现在 SQL 任意子句
    FILTER  — 可用不可见：允许 WHERE/JOIN/GROUP BY/HAVING，禁止 SELECT 列表
    NONE    — 完全不可用

默认行为（无显式授权记录时）按 sensitive_level 推导：
    public        → SELECT
    internal      → SELECT
    sensitive     → FILTER
    confidential  → NONE
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, UniqueConstraint
from models.base import MainBase


class UserColumnGrant(MainBase):
    """用户字段级授权 — 覆盖 sensitive_level 的默认推导"""
    __tablename__ = 'user_column_grants'
    __table_args__ = (UniqueConstraint('user_id', 'column_id', name='uix_user_column_grant'),)
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True, comment='用户ID')
    column_id = Column(Integer, ForeignKey('db_columns.id'), nullable=False, index=True, comment='字段ID')
    access_type = Column(String(10), nullable=False, default='SELECT',
                         comment='权限级别: SELECT/FILTER/NONE')
    created_at = Column(DateTime, default=datetime.now, comment='创建时间')


class RowScopeRule(MainBase):
    """行级数据范围规则 — SQL 执行前注入 WHERE 条件"""
    __tablename__ = 'row_scope_rules'
    __table_args__ = (UniqueConstraint('user_id', 'table_id', name='uix_row_scope_rule'),)
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True, comment='用户ID')
    table_id = Column(Integer, ForeignKey('db_tables.id'), nullable=False, index=True, comment='表ID')
    filter_expression = Column(Text, nullable=False, comment='行级过滤表达式(如 dept_id = 10)')
    created_at = Column(DateTime, default=datetime.now, comment='创建时间')
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')


class QueryAuditLog(MainBase):
    """查询审计日志 — 每次查询的完整审计记录"""
    __tablename__ = 'query_audit_logs'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True, comment='用户ID')
    username = Column(String(50), comment='用户名(冗余便于查询)')
    query = Column(Text, nullable=False, comment='自然语言问题')
    generated_sql = Column(Text, comment='LLM 生成的原始 SQL')
    modified_sql = Column(Text, comment='经权限网关处理后的 SQL')
    tables_accessed = Column(Text, comment='命中的表名(逗号分隔)')
    columns_accessed = Column(Text, comment='命中的字段名(逗号分隔)')
    hit_sensitive = Column(Boolean, default=False, comment='是否命中敏感字段')
    was_blocked = Column(Boolean, default=False, comment='是否被权限拦截')
    block_reason = Column(String(500), comment='拦截原因')
    pipeline_log = Column(Text, comment='流程日志(JSON)')
    duration_ms = Column(Integer, default=0, comment='耗时(毫秒)')
    created_at = Column(DateTime, default=datetime.now, index=True, comment='创建时间')
