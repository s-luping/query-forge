# -*- coding: UTF-8 -*-
"""统一响应结构与错误码 — 开发纲领 §2（公共能力下沉共享层）

设计约束：
    - 向后兼容：错误体保留 `detail` 键（前端 apiRequest 读取 data.detail），
      新增 code / message / request_id 字段做超集，不破坏存量消费方。
    - 新增接口的成功响应统一用 ok() 包装；存量成功结构渐进迁移，不做一次性破坏。

用法（新增接口）：
    from app.response import ok, fail, ErrorCode
    return ok({'items': rows, 'total': n})
    raise HTTPException(400, detail='...')          # 仍走统一错误处理器
"""
import uuid
from contextvars import ContextVar
from enum import IntEnum
from typing import Any

# ── 请求级 traceId（中间件写入，日志/慢SQL/错误体统一携带） ──
_request_id_var: ContextVar[str] = ContextVar('request_id', default='')


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


def set_request_id(rid: str) -> None:
    _request_id_var.set(rid)


def get_request_id() -> str:
    return _request_id_var.get()


# ── 错误码枚举：前 3 位对齐 HTTP 状态，后 2 位细分业务 ──
class ErrorCode(IntEnum):
    OK = 0
    BAD_REQUEST = 40000
    UNAUTHORIZED = 40100
    FORBIDDEN = 40300
    NOT_FOUND = 40400
    CONFLICT = 40900
    RATE_LIMITED = 42900
    INTERNAL = 50000
    SERVICE_UNAVAILABLE = 50300


_HTTP_TO_CODE = {
    400: ErrorCode.BAD_REQUEST,
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    409: ErrorCode.CONFLICT,
    422: ErrorCode.BAD_REQUEST,
    429: ErrorCode.RATE_LIMITED,
    500: ErrorCode.INTERNAL,
    503: ErrorCode.SERVICE_UNAVAILABLE,
}


def code_for_status(http_status: int) -> int:
    return int(_HTTP_TO_CODE.get(http_status, ErrorCode.INTERNAL))


def ok(data: Any = None, message: str = 'ok') -> dict:
    """统一成功响应 — 平铺信封（纲领 §2）

    结构：{code: 0, success: True, message, ...payload}

    设计约束（向前端兼容，零改动）：
        - payload 为 dict 时平铺展开，保留前端已消费的
          items / total / success / message 等键；
        - payload 非 dict 时落到 data 键（如标量/列表）；
        - 不引入嵌套 data 层，避免前端读取路径变更。
    """
    body = {'code': int(ErrorCode.OK), 'success': True, 'message': message}
    if data is None:
        return body
    if isinstance(data, dict):
        body.update(data)
    else:
        body['data'] = data
    return body


def ok_msg(message: str, **extra) -> dict:
    """mutation 成功响应的简写：ok_msg('更新成功')"""
    body = {'code': int(ErrorCode.OK), 'success': True, 'message': message}
    body.update(extra)
    return body


def fail(code: int, message: str, data: Any = None) -> dict:
    """统一失败响应（业务代码内主动构造）— 平铺信封，与 ok() 对称"""
    body = {'code': int(code), 'success': False, 'message': message}
    if data is None:
        return body
    if isinstance(data, dict):
        body.update(data)
    else:
        body['data'] = data
    return body


def error_body(http_status: int, detail: Any = None, message: str = '',
               request_id: str = '') -> dict:
    """统一错误响应体 — detail 键保留以兼容前端，code/message/request_id 为新增字段"""
    return {
        'code': code_for_status(http_status),
        'message': message or '请求失败',
        'detail': detail,
        'request_id': request_id or get_request_id(),
    }
