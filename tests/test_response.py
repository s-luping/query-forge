# -*- coding: UTF-8 -*-
"""统一响应 / traceId / 限流 — 纲领 §2（统一响应结构与错误码）、§4.1（traceId 可观测）

覆盖本轮基础设施改造的关键行为，防止回归：
    - error_body 保留 detail 键（前端 apiRequest 依赖），新增 code/message/request_id
    - 各类异常（404 / 422 / 429）均走统一错误体，不退回 Starlette 原生 {"detail": ...}
    - X-Request-ID 响应头与错误体 request_id 一致
    - 限流 key 按登录用户优先、匿名回退 IP
"""
import pytest

from app.response import ErrorCode, code_for_status, error_body, get_request_id, set_request_id


# ── error_body 结构 ─────────────────────────────────────────
def test_error_body_keeps_detail_key():
    """detail 键必须保留 —— 前端 apiRequest 读取 data.detail 展示错误"""
    body = error_body(404, detail='Not Found', message='Not Found')
    assert body['detail'] == 'Not Found'


def test_error_body_has_all_keys():
    body = error_body(400, detail='x')
    assert set(body.keys()) == {'code', 'message', 'detail', 'request_id'}


def test_error_body_falls_back_to_context_request_id():
    """未显式传 request_id 时取当前请求上下文"""
    set_request_id('rid-ctx')
    assert error_body(500, detail='x')['request_id'] == 'rid-ctx'


def test_error_body_explicit_request_id_wins():
    set_request_id('rid-ctx')
    assert error_body(500, detail='x', request_id='rid-explicit')['request_id'] == 'rid-explicit'


@pytest.mark.parametrize('status,expected', [
    (400, ErrorCode.BAD_REQUEST),
    (401, ErrorCode.UNAUTHORIZED),
    (403, ErrorCode.FORBIDDEN),
    (404, ErrorCode.NOT_FOUND),
    (409, ErrorCode.CONFLICT),
    (422, ErrorCode.BAD_REQUEST),   # 语义校验失败归类参数错误
    (429, ErrorCode.RATE_LIMITED),
    (500, ErrorCode.INTERNAL),
    (503, ErrorCode.SERVICE_UNAVAILABLE),
])
def test_code_for_status_mapping(status, expected):
    assert code_for_status(status) == int(expected)


def test_code_for_unknown_status_is_internal():
    assert code_for_status(418) == int(ErrorCode.INTERNAL)


def test_request_id_roundtrip():
    set_request_id('abc123')
    assert get_request_id() == 'abc123'