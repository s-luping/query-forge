# -*- coding: UTF-8 -*-
"""查询审计日志 — ChatSession 的 write_query_audit_log

gateway_result 兼容两种形态：
  - SqlGatewayResult 对象（pipeline 传入）
  - to_dict() 产物 dict（chat 传入）
"""
from typing import Optional

from app.logger import logger
from crud.base import session_scope


def write_query_audit_log(user_id: int, user: dict, query: str,
                          generated_sql: str, final_sql: str,
                          gateway_result=None, duration_ms: int = 0,
                          pipeline_log: str = '') -> Optional[int]:
    """写入 QueryAuditLog；失败只记日志，不影响主流程

    Returns:
        新建审计记录的 id（供路由层追加后置步骤后 update_pipeline_log 回写）；
        写入失败返回 None。
    """
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

        # QueryAuditLog 挂 LogsBase（三库分离），必须写日志库
        with session_scope(logs=True) as db:
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
            db.refresh(log)
            return log.id
    except Exception as e:
        logger.warning(f"审计日志写入失败: {e}")
        return None


def update_pipeline_log(log_id: Optional[int], pipeline_log: str):
    """回写审计记录的 pipeline_log 字段（路由层追加后置步骤后调用）

    供「链路追踪」弹窗展示完整端到端链路（前置鉴权 + 生成 + 后置执行/持久化）。
    失败静默，不影响主流程。
    """
    if not log_id:
        return
    try:
        from models.security import QueryAuditLog
        # QueryAuditLog 在日志库（三库分离），回写也必须走日志库
        with session_scope(logs=True) as db:
            db.query(QueryAuditLog).filter(QueryAuditLog.id == log_id).update(
                {QueryAuditLog.pipeline_log: pipeline_log})
            db.commit()
    except Exception as e:
        logger.warning(f"审计链路日志回写失败 (log_id={log_id}): {e}")
