# -*- coding: UTF-8 -*-
"""向量索引状态服务 — 标记索引过期

职责：
  - mark_index_stale: 标记索引过期（数据有新增但索引未更新）

向量索引不再自动构建：导入/同步后只标记 stale，重建统一由
定时任务「向量索引重建」（scheduler/jobs/vector_index.py）执行，
避免构建与用户当前使用（导入/召回）冲突。

依赖方向：services/vector → core/retrieval（正确方向）
"""
from app.logger import logger


def mark_index_stale(schema_name: str):
    """标记索引为过期（数据有新增但索引未更新）"""
    try:
        from core.ret_index_meta import set_index_meta
        set_index_meta(schema_name, 'stale')
    except Exception as e:
        logger.warning(f"标记向量索引过期失败: {e}")
