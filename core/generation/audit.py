# -*- coding: UTF-8 -*-
"""
查询审计日志 — 原 SQLPipeline 与 ChatSession 两份 _write_audit_log 的合并

gateway_result 兼容两种形态：
  - SqlGatewayResult 对象（pipeline 传入）
  - to_dict() 产物 dict（chat 传入）
"""
from app.logger import logger, pipeline_logger
from curd.base import session_scope


def write_query_audit_log(user_id: int, user: dict, query: str,
                          generated_sql: str, final_sql: str,
                          gateway_result=None, duration_ms: int = 0,
                          pipeline_log: str = ''):
    """写入 QueryAuditLog；失败只记日志，不影响主流程"""
    try:
        from models.security import QueryAuditLog

        if gateway_result is not None and hasattr(gateway_result, 'to_dict'):
            gateway_result = gateway_result.to_dict()

        if gateway_result:
            tables = ','.join(gateway_result.get('tables', []))
            columns = ','.join(gateway_result.get('columns', {}).keys())
            hit_sensitive = gateway_result.get('hit_sensitive', False)
            was_blocked = not gateway_result.get('is_allowed', True)
            block_reason = gateway_result.get('block_reason', '') or ''
        else:
            tables = columns = block_reason = ''
            hit_sensitive = was_blocked = False

        with session_scope() as db:
            log = QueryAuditLog(
                user_id=user_id,
                username=str(user.get('username', '')),
                query=query,
                generated_sql=generated_sql,
                modified_sql=final_sql if generated_sql != final_sql else None,
                tables_accessed=tables,
                columns_accessed=columns,
                hit_sensitive=hit_sensitive,
                was_blocked=was_blocked,
                block_reason=block_reason,
                pipeline_log=pipeline_log,
                duration_ms=duration_ms,
            )
            db.add(log)
            db.commit()
    except Exception as e:
        logger.warning(f"审计日志写入失败: {e}")
        pipeline_logger.error(f"审计日志写入失败: {e}")
