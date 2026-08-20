# -*- coding: UTF-8 -*-
"""向量索引服务 — 索引构建、状态管理（从路由层下沉）"""
from services.vector.service import (
    auto_build_vector_index,
    mark_index_stale,
    vector_build_lock,
)
