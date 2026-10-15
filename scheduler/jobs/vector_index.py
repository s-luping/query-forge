# -*- coding: UTF-8 -*-
"""定时向量索引重建 — 替代导入/召回时的自动构建

背景：导入或同步后立即后台构建会与用户当前使用（其他用户导入、对话召回）
冲突，故不再自动触发；导入/同步只标记 stale，重建统一由本定时任务执行：
    - 仅当索引 stale/error/缺失 时才构建，ready 状态幂等跳过
    - 构建为全库统一索引（元数据 key='default'），期间旧索引文件
      原子保留继续服务，完成后自动替换
    - 手动重建仍走管理页 /build-vector-index 端点
"""
import threading

from app.logger import logger

# 与手动构建/召回共用的构建锁 — 防止并发全量构建
vector_build_lock = threading.Lock()


def rebuild_vector_index(force: bool = False) -> dict:
    """按需重建全库向量索引（stale/error/缺失才构建，force 强制）

    返回 dict 作为执行摘要，供任务日志展示。
    """
    from core.ret_index_meta import build_vector_index, get_index_meta
    from core.ret_vector_store import EmbeddingModel

    if not EmbeddingModel.is_ready():
        logger.warning("Embedding 模型未就绪，跳过向量索引重建")
        return {'action': 'skipped', 'reason': 'embedding 未就绪'}

    meta = get_index_meta('default')
    status = meta.get('status') if meta else 'missing'
    if not force and status == 'ready':
        return {'action': 'skipped', 'reason': f'索引已就绪（字段数: {meta["field_count"]}）'}

    with vector_build_lock:
        # 双重检查：等锁期间可能已被其他构建完成
        meta = get_index_meta('default')
        if not force and meta and meta['status'] == 'ready':
            return {'action': 'skipped', 'reason': '索引已就绪（等待锁期间被其他构建完成）'}

        logger.info(f"定时任务开始重建全库向量索引（原状态: {status}）")
        result = build_vector_index(None)
        if result.get('success'):
            logger.info("全库向量索引重建完成")
            return {'action': 'rebuilt',
                    'field_count': result.get('field_count', 0),
                    'previous_status': status}
        return {'action': 'failed', 'message': result.get('message', '构建失败'),
                'previous_status': status}
