# -*- coding: UTF-8 -*-
"""限流 — slowapi 封装（纲领 §3.2/§4.1：限流作为接口一等能力）

key 优先取登录用户（同一账号跨 IP 共享额度），未登录回退客户端 IP。
使用注意（缺一不可，否则限流静默失效）：
    1. 装饰器顺序：@router.post 必须在 @limiter.limit 上方（外层），
       否则路由注册的是未包装函数，限流完全不生效；
    2. 端点必须有名为 `request` 的 Starlette Request 参数
       （body 参数不能占用该名字，需改名）。
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

import os

from app.auth import resolve_token_user


def _rate_limit_key(request):
    """登录用户按 user_id 限流，未登录按 IP"""
    try:
        token = request.cookies.get('token') or request.headers.get(
            'Authorization', '').replace('Bearer ', '')
        user = resolve_token_user(token) if token else None
        if user:
            return f'u{user["user_id"]}'
    except Exception:
        pass
    return get_remote_address(request)


limiter = Limiter(key_func=_rate_limit_key)


# ── 限流档位（集中定义，避免各处魔法字符串；纲领 §3.2/§4.1）──────
# 数据接口按"单用户/单IP 每分钟"计，额度按资源代价分级；
# 可用环境变量 QF_LIMIT_* 覆盖（测试/压测环境放宽用，默认值即线上档位）：
def _limit(env: str, default: str) -> str:
    return os.getenv(env, default) or default

LIMIT_AUTH = _limit('QF_LIMIT_AUTH', '2/minute')            # 登录/注册：防暴力破解
LIMIT_HEAVY = _limit('QF_LIMIT_HEAVY', '10/minute')         # 重接口：生成 SQL 执行、向量索引重建、导出
LIMIT_WRITE = _limit('QF_LIMIT_WRITE', '30/minute')         # 写接口：导入/删除/更新/同步触发
LIMIT_READ = _limit('QF_LIMIT_READ', '120/minute')          # 读接口：列表/详情/统计（防脚本批量刷）
LIMIT_TEST = _limit('QF_LIMIT_TEST', '6/minute')            # 外部连接测试：每次都会真实建连，额度最低

__all__ = ['limiter', 'LIMIT_AUTH', 'LIMIT_HEAVY', 'LIMIT_WRITE',
           'LIMIT_READ', 'LIMIT_TEST']
