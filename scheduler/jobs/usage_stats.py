# -*- coding: UTF-8 -*-
"""LLM 用量聚合任务 — 从遥测库 llm_calls 聚合到主库 llm_usage_stats

按 天×用户×模型 汇总调用次数、Token、成本，供用量看板查询。
由 scheduler 每小时触发一次（可配置），聚合最近 N 天的数据（幂等覆盖）。
"""
from datetime import date, datetime, timedelta

from sqlalchemy import case, func

from app.logger import logger
from app.timezone import now_beijing
from crud.base import session_scope
from models.llm import LLMCall, LLMUsageStat


def aggregate_usage_stats(days_back: int = 7) -> dict:
    """聚合最近 N 天的 LLM 用量到 llm_usage_stats（幂等）

    Args:
        days_back: 向前回溯的天数（默认 7 天，覆盖每小时增量）

    Returns:
        {"rows_upserted": int, "days_covered": int}
    """
    today = now_beijing().date()
    start_date = today - timedelta(days=days_back)
    # 用范围比较而非 func.date()：后者包住字段会导致索引失效，改为 >= 起算日零点
    start_datetime = datetime.combine(start_date, datetime.min.time())

    # ── 1. 从遥测库读取聚合数据 ──
    with session_scope(telemetry=True) as tdb:
        rows = (tdb.query(
            func.date(LLMCall.created_at).label('stat_date'),
            LLMCall.user_id,
            LLMCall.provider,
            LLMCall.model,
            func.count(LLMCall.id).label('call_count'),
            func.sum(case(
                (LLMCall.status == 'success', 1), else_=0
            )).label('success_count'),
            func.coalesce(func.sum(LLMCall.prompt_tokens), 0).label('prompt_tokens'),
            func.coalesce(func.sum(LLMCall.completion_tokens), 0).label('completion_tokens'),
            func.coalesce(func.sum(LLMCall.total_tokens), 0).label('total_tokens'),
        )
        .filter(LLMCall.created_at >= start_datetime)
        .group_by(
            func.date(LLMCall.created_at),
            LLMCall.user_id, LLMCall.provider, LLMCall.model,
        )
        .all())

    if not rows:
        logger.debug("aggregate_usage_stats: 无可聚合数据")
        return {"rows_upserted": 0, "days_covered": 0}

    # ── 2. Upsert 到主库 llm_usage_stats ──
    try:
        with session_scope() as db:
            # 批量预加载已有记录（避免 N+1 查询）
            existing = {}
            if rows:
                stat_dates = list({r.stat_date for r in rows})
                user_ids = list({r.user_id for r in rows})
                for row in db.query(LLMUsageStat).filter(
                    LLMUsageStat.stat_date.in_(stat_dates),
                    LLMUsageStat.user_id.in_(user_ids),
                ).all():
                    existing[(row.stat_date, row.user_id, row.model)] = row

            upserted = 0
            for r in rows:
                stat_date = r.stat_date if isinstance(r.stat_date, date) else datetime.strptime(str(r.stat_date), '%Y-%m-%d').date()
                row = existing.get((stat_date, r.user_id, r.model))

                if row:
                    row.provider = r.provider or ''
                    row.call_count = r.call_count
                    row.success_count = r.success_count
                    row.prompt_tokens = r.prompt_tokens
                    row.completion_tokens = r.completion_tokens
                    row.total_tokens = r.total_tokens
                else:
                    db.add(LLMUsageStat(
                        stat_date=stat_date,
                        user_id=r.user_id,
                        provider=r.provider or '',
                        model=r.model,
                        call_count=r.call_count,
                        success_count=r.success_count,
                        prompt_tokens=r.prompt_tokens,
                        completion_tokens=r.completion_tokens,
                        total_tokens=r.total_tokens,
                    ))
                upserted += 1

        logger.info(f"aggregate_usage_stats: 聚合 {upserted} 行 ({len(rows)} 组)，覆盖 {start_date} → {today}")
        return {"rows_upserted": upserted, "days_covered": days_back}
    except Exception as e:
        logger.error(f"aggregate_usage_stats 失败: {e}")
        return {"rows_upserted": 0, "days_covered": 0, "error": str(e)}
