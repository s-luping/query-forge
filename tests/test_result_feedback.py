# -*- coding: UTF-8 -*-
"""查询结果反馈可解释性 — 空结果归因 / LLM 失败分类 / 权限归因提示 / SSRF IPv6"""
import pytest

from app.routers.conversation_router import _classify_llm_failure, _permission_note
from core.llm_client import _validate_llm_url
from fastapi import HTTPException


# ── _permission_note：空结果归因 ──────────────────────────────────

def test_permission_note_none_when_nothing():
    assert _permission_note({'gateway': None}) is None
    assert _permission_note({}, None) is None


def test_permission_note_empty_result_with_row_filter():
    """行级过滤后 0 行 → 明示权限过滤是空结果的可能原因"""
    result = {'gateway': {'was_modified': True,
                          'modifications': ['注入行级过滤: orders → region_id IN (1,2)'],
                          'hit_sensitive': False, 'is_allowed': True}}
    qr = {'error': None, 'row_count': 0, 'columns': ['c'], 'rows': []}
    note = _permission_note(result, qr)
    assert note is not None
    assert '0 行' in note
    assert '行级过滤' in note
    assert 'orders' in note


def test_permission_note_empty_result_without_filter():
    """无权限过滤的 0 行 → 常规归因（条件过严/数据为空）"""
    result = {'gateway': None}
    qr = {'error': None, 'row_count': 0, 'columns': ['c'], 'rows': []}
    note = _permission_note(result, qr)
    assert note is not None
    assert '筛选条件过严' in note


def test_permission_note_no_hint_for_nonempty_or_error():
    """有数据/执行报错时不追加空结果提示"""
    ok_qr = {'error': None, 'row_count': 5, 'columns': ['c'], 'rows': [[1]]}
    assert _permission_note({'gateway': None}, ok_qr) is None
    err_qr = {'error': 'SQL 执行失败', 'row_count': 0, 'columns': [], 'rows': []}
    assert _permission_note({'gateway': None}, err_qr) is None


# ── _classify_llm_failure：LLM 失败原因分类（返回 HTTPException 供路由 raise） ──

def test_classify_timeout():
    e = RuntimeError("调用 X API网络请求失败: ReadTimeout(Read timed out)")
    exc = _classify_llm_failure(e, "创建对话失败")
    assert exc.status_code == 504
    assert '超时' in exc.detail


def test_classify_rate_limit():
    e = ValueError("API返回错误状态码: 429, Too Many Requests")
    exc = _classify_llm_failure(e, "创建对话失败")
    assert exc.status_code == 502
    assert '限流' in exc.detail


def test_classify_bad_key():
    e = ValueError("API返回错误状态码: 401, Invalid API key")
    exc = _classify_llm_failure(e, "发送消息失败")
    assert exc.status_code == 502
    assert '密钥' in exc.detail


def test_classify_no_key():
    e = ValueError("未配置 OpenAI API密钥，请设置环境变量或在前端配置")
    exc = _classify_llm_failure(e, "创建对话失败")
    assert exc.status_code == 400
    assert '模型管理页' in exc.detail


def test_classify_unknown_keeps_context():
    e = ValueError("某些无法归类的错误")
    exc = _classify_llm_failure(e, "创建对话失败")
    assert exc.status_code == 500
    assert '创建对话失败' in exc.detail


# ── SSRF：IPv6 回环 / IPv4 映射地址 ───────────────────────────────

def test_ssrf_blocks_ipv6_loopback():
    with pytest.raises(ValueError):
        _validate_llm_url('http://[::1]:8000/v1/chat/completions')


def test_ssrf_blocks_ipv4_mapped_loopback():
    with pytest.raises(ValueError):
        _validate_llm_url('http://[::ffff:127.0.0.1]:8888/v1')


def test_ssrf_blocks_ipv4_mapped_private():
    with pytest.raises(ValueError):
        _validate_llm_url('http://[::ffff:10.0.0.5]/v1')


def test_ssrf_allows_public_domain():
    _validate_llm_url('https://integrate.api.nvidia.com/v1')


def test_ssrf_allows_public_ip():
    _validate_llm_url('http://8.8.8.8/v1')
