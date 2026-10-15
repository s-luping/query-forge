# -*- coding: UTF-8 -*-
"""全局异常处理器 / traceId 端到端 — 纲领 §2、§4.1

重点防回归：HTTPException 处理器必须注册在 Starlette 父类上，
否则路由未命中抛出的 404 / 405 会绕过统一错误体。
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope='module')
def client():
    import main
    return TestClient(main.app, raise_server_exceptions=False)


def test_not_found_uses_unified_error_body(client):
    """404 必须走统一错误体（回归点：处理器曾只注册在 FastAPI HTTPException 子类上）"""
    r = client.get('/api/definitely-not-a-real-route')
    assert r.status_code == 404
    body = r.json()
    assert set(body.keys()) == {'code', 'message', 'detail', 'request_id'}
    assert body['code'] == 40400
    assert body['detail']  # detail 键保留给前端


def test_validation_error_unified(client):
    """422 参数校验失败 → 统一错误体"""
    r = client.post('/login', json={'wrong_field': 1})
    assert r.status_code == 422
    body = r.json()
    assert set(body.keys()) == {'code', 'message', 'detail', 'request_id'}
    assert body['code'] == 40000


def test_request_id_header_present(client):
    """traceId 贯穿响应头（纲领 §4.1 前后端串联）"""
    r = client.get('/api/definitely-not-a-real-route')
    assert r.headers.get('X-Request-ID')


def test_header_matches_body_request_id(client):
    """响应头 X-Request-ID 与错误体 request_id 一致"""
    r = client.get('/api/definitely-not-a-real-route')
    assert r.headers.get('X-Request-ID') == r.json()['request_id']


def test_rate_limit_returns_429_with_retry_after(client):
    """限流触发 → 429 + Retry-After + 统一错误体"""
    last = None
    for _ in range(5):
        last = client.post('/login', json={'username': 'nobody', 'password': 'bad'})
        if last.status_code == 429:
            break
    assert last.status_code == 429
    assert last.json()['code'] == 42900
    assert last.headers.get('Retry-After')