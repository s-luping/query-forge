# -*- coding: UTF-8 -*-
"""向量索引服务 — 从路由层下沉，供 sync engine 和 schema router 共用

职责：
  - auto_build_vector_index: 自动构建向量索引（后台异步，含重试和锁）
  - mark_index_stale: 标记索引过期

依赖方向：services/vector → core/retrieval（正确方向）
旧依赖 services/sync → app/routers（反向依赖）已消除。
"""
import threading
from typing import Optional

from app.logger import logger

# 模块级构建锁 — 防止并发构建同一 schema 的索引
vector_build_lock = threading.Lock()


def mark_index_stale(schema_name: str):
    """标记索引为过期（数据有新增但索引未更新）"""
    try:
        from core.retrieval.index_meta import set_index_meta
        set_index_meta(schema_name, 'stale')
    except Exception:
        pass


def auto_build_vector_index(schema_name: str, schema_field_count: int) -> Optional[str]:
    """自动构建向量索引（后台异步，不阻塞调用方）

    条件：
    1. Embedding 模型已就绪
    2. 字段数量达到阈值（VECTOR_INDEX_THRESHOLD）

    流程：标记过期 → 后台线程构建（含重试 + 锁）
    """
    from core.retrieval.vector_store import EmbeddingModel, get_vector_config

    if not EmbeddingModel.is_ready():
        logger.warning(f"Embedding 模型未就绪，跳过自动索引构建: {schema_name}")
        return None

    threshold = get_vector_config('VECTOR_INDEX_THRESHOLD')
    if schema_field_count < threshold:
        logger.info(f"Schema {schema_name} 字段数量 {schema_field_count} 未达到阈值 {threshold}，跳过自动索引构建")
        return None

    # 先标记为过期（新数据已入库，索引待更新）
    mark_index_stale(schema_name)

    def _build_in_background():
        from core.retrieval.index_meta import build_vector_index, get_index_meta
        max_retries = 3
        for attempt in range(max_retries):
            with vector_build_lock:
                # 检查是否仍需构建（可能被上一轮修复了）
                meta = get_index_meta(schema_name)
                if meta and meta['status'] == 'ready':
                    logger.info(f"Schema {schema_name} 索引已就绪，跳过构建（attempt {attempt+1}）")
                    return

                try:
                    logger.info(f"开始构建向量索引: {schema_name} (attempt {attempt+1})")
                    result = build_vector_index(schema_name)
                    if result.get('success'):
                        logger.info(f"Schema {schema_name} 向量索引构建完成")
                except Exception as e:
                    logger.warning(f"后台构建向量索引失败: {e}")
                    return  # 构建失败不重试

            # 释放锁后再次检查：构建期间是否有新数据导入导致索引再次过期
            if attempt < max_retries - 1:
                import time
                time.sleep(0.5)
                meta = get_index_meta(schema_name)
                if meta and meta['status'] != 'stale':
                    return  # 索引已是最新，无需再构建

    thread = threading.Thread(target=_build_in_background, daemon=True)
    thread.start()
    return f"Schema {schema_name} 正在后台创建向量索引（字段数: {schema_field_count}）"
