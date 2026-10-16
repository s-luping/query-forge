# -*- coding: UTF-8 -*-
"""LLM 配置欠费自动标记回归 — core/llm_client.py + conversation_router 标记链路

覆盖五条性质：
  1. _is_arrears_response 关键词识别（大小写不敏感 / 中文 / 负例不误伤）
  2. call_llm_with_details 非 200 且响应体含欠费关键词 → LLMArrearsError（ValueError 子类）
  3. 非欠费错误（如密钥无效）仍为普通 ValueError，不误标
  4. _mark_llm_config_arrears 仅更新 status 一个字段；None/不存在 ID 安全无副作用
  5. _build_llm_client 把实际使用的 config_id 挂到客户端（含默认配置回退）
"""
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core import llm_client as llm_client_mod
from core.llm_client import LLMArrearsError, LLMClient, _is_arrears_response

# 火山方舟真实欠费响应片段（2026-10-16 日志取证）
VO_ARREARS_BODY = ('{"error":{"code":"SetLimitExceeded","message":"Your account '
                   '[2101997991] has reached the set usage limit for the '
                   '[doubao-seed-2-1-pro] model, and the model service has been '
                   'paused.","param":"","type":"TooManyRequests"}}')


def _make_client():
    # base_url 用公网假地址（SSRF 校验禁内网），实际请求被 mock 不出网
    return LLMClient(provider='test', api_key='k', model='m',
                     base_url='https://api.example.com/v1')


class _FakeResponse:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text


class _FakeSession:
    def __init__(self, response):
        self._response = response
        self.called = False

    def post(self, *args, **kwargs):
        self.called = True
        return self._response


@pytest.fixture()
def fake_api(monkeypatch):
    """替换共享 Session，返回预设响应（不出网）"""
    holder = {}

    def _install(response):
        holder['session'] = _FakeSession(response)
        monkeypatch.setattr(llm_client_mod, '_get_session',
                            lambda: holder['session'])
        return holder['session']

    return _install


# ── 1. 关键词识别 ────────────────────────────────────────────────

@pytest.mark.parametrize('body', [
    VO_ARREARS_BODY,                                # 火山 SetLimitExceeded
    '{"error":{"code":"Arrearage","message":"账户欠费"}}',
    '{"error":{"code":"insufficient_quota"}}',      # OpenAI 风格
    '您的余额不足，请充值',
    'OpenQuotaExceeded: usage limit reached',       # 大小写不敏感
])
def test_arrears_body_matched(body):
    assert _is_arrears_response(body) is True


@pytest.mark.parametrize('body', [
    '{"error":{"code":"AuthenticationError","message":"Invalid API key provided"}}',
    'ModelNotOpen: model not subscribed',           # 未开通≠欠费，不误标
    '{"error":{"message":"timeout"}}',
    '',                                              # 空响应体
])
def test_non_arrears_body_not_matched(body):
    assert _is_arrears_response(body) is False


# ── 2/3. 异常类型判定 ────────────────────────────────────────────

def test_call_llm_raises_arrears_error(fake_api):
    """欠费响应 → LLMArrearsError（保持 ValueError 子类，兼容旧捕获）"""
    fake_api(_FakeResponse(429, VO_ARREARS_BODY))
    with pytest.raises(LLMArrearsError) as ei:
        _make_client().call_llm_with_details('SELECT 1')
    assert 'SetLimitExceeded' in str(ei.value)
    assert isinstance(ei.value, ValueError)


def test_chat_raises_arrears_error(fake_api):
    fake_api(_FakeResponse(429, VO_ARREARS_BODY))
    with pytest.raises(LLMArrearsError):
        _make_client().chat([{'role': 'user', 'content': 'hi'}])


def test_non_arrears_api_error_stays_valueerror(fake_api):
    """密钥无效等普通错误不升级为欠费异常"""
    fake_api(_FakeResponse(401, '{"error":{"code":"AuthenticationError"}}'))
    with pytest.raises(ValueError) as ei:
        _make_client().call_llm_with_details('SELECT 1')
    assert not isinstance(ei.value, LLMArrearsError)


# ── 4. 标记函数：仅更新 status ───────────────────────────────────

@pytest.fixture()
def llm_db(monkeypatch):
    """内存 SQLite 建 llm_configs 表，替换 conversation_router 的 session_scope"""
    from app.crypto import encrypt_secret
    from models.llm import LLMConfig

    engine = create_engine('sqlite://')
    LLMConfig.__table__.create(engine)
    factory = sessionmaker(bind=engine)

    @contextmanager
    def fake_session_scope():
        s = factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    monkeypatch.setattr('app.routers.conversation_router.session_scope',
                        fake_session_scope)
    # 预置一条配置，验证标记前后其余字段不变
    seed = LLMConfig(user_id=1, provider='豆包', model='doubao-pro',
                     api_key=encrypt_secret('k'), max_tokens=32768,
                     is_default=True, is_active=True, status='normal')
    s = factory()
    s.add(seed)
    s.commit()
    s.refresh(seed)
    seed_id = seed.id
    snapshot = (seed.provider, seed.model, seed.max_tokens,
                seed.is_default, seed.is_active)
    s.close()
    return {'factory': factory, 'seed_id': seed_id, 'snapshot': snapshot}


def test_mark_arrears_updates_only_status(llm_db):
    from app.routers.conversation_router import _mark_llm_config_arrears
    from models.llm import LLMConfig

    _mark_llm_config_arrears(llm_db['seed_id'])

    s = llm_db['factory']()
    row = s.query(LLMConfig).filter(LLMConfig.id == llm_db['seed_id']).one()
    assert row.status == 'arrears'
    # 其余字段一律不动
    assert (row.provider, row.model, row.max_tokens,
            row.is_default, row.is_active) == llm_db['snapshot']
    s.close()


def test_mark_arrears_none_and_missing_id_safe(llm_db):
    """config_id 为 None / 不存在的 ID：不报错、不写库"""
    from app.routers.conversation_router import _mark_llm_config_arrears
    from models.llm import LLMConfig

    _mark_llm_config_arrears(None)          # 无 config_id 直接返回
    _mark_llm_config_arrears(99999)         # 不存在的 ID：warning 不抛

    s = llm_db['factory']()
    row = s.query(LLMConfig).filter(LLMConfig.id == llm_db['seed_id']).one()
    assert row.status == 'normal'           # 种子行未被误改
    s.close()


# ── 5. _build_llm_client 挂载 config_id ──────────────────────────

def test_build_llm_client_attaches_config_id(llm_db):
    """指定/默认配置命中时挂 config_id，供欠费回写定位"""
    from app.routers.conversation_router import _build_llm_client

    client = _build_llm_client(user_id=1, llm_config_id=llm_db['seed_id'])
    assert client.config_id == llm_db['seed_id']
    assert client.model == 'doubao-pro'


def test_build_llm_client_fallback_has_no_config_id(llm_db):
    """无可用配置回退裸客户端：无 config_id（标记函数安全跳过）"""
    from app.routers.conversation_router import _build_llm_client

    client = _build_llm_client(user_id=42, llm_config_id=99999)
    assert getattr(client, 'config_id', None) is None
