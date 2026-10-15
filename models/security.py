"""安全模型 — 查询审计。

字段敏感等级和角色字段权限由 schema 模型与 models.role 共同管理。

库归属：日志库（logs.db）。user_id 原外键引用 users.id，拆库后降级为
普通索引列，删除用户时由 user_router 显式级联清理（应用层保证完整性）。
"""
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from app.timezone import now_beijing
from models.base import LogsBase


class QueryAuditLog(LogsBase):
    """查询审计日志 — 每次查询的完整审计记录"""
    __tablename__ = 'query_audit_logs'
    id = Column(Integer, primary_key=True, autoincrement=True, comment='主键')
    user_id = Column(Integer, nullable=False, index=True, comment='用户ID(跨库引用users.id,应用层级联清理)')
    username = Column(String(50), comment='用户名(冗余便于查询)')
    query = Column(Text, nullable=False, comment='自然语言问题')
    generated_sql = Column(Text, comment='LLM 生成的原始 SQL')
    modified_sql = Column(Text, comment='经权限网关处理后的 SQL')
    tables_accessed = Column(Text, comment='命中的表名(逗号分隔)')
    columns_accessed = Column(Text, comment='命中的字段名(逗号分隔)')
    hit_sensitive = Column(Boolean, default=False, index=True, comment='是否命中敏感字段')
    was_blocked = Column(Boolean, default=False, index=True, comment='是否被权限拦截')
    block_reason = Column(String(500), comment='拦截原因')
    pipeline_log = Column(Text, comment='流程日志(JSON)')
    duration_ms = Column(Integer, default=0, comment='耗时(毫秒)')
    created_at = Column(DateTime, default=now_beijing, index=True, comment='创建时间（北京时间）')
