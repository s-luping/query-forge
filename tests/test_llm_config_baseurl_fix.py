# -*- coding: UTF-8 -*-
"""验证 llm_router.update_config 的 base_url 绑定修复

场景复现：
  旧代码误读 Starlette Request.base_url（URL 对象）写入 String 列，
  触发 sqlite3.InterfaceError: Error binding parameter 0。
修复后：从 payload 读取并对 base_url 做 str() 兜底。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine
from starlette.requests import Request

from models.llm import LLMConfig

ATTRS = ['model', 'base_url', 'max_tokens', 'temperature', 'timeout', 'description']


def make_request():
    scope = {
        'type': 'http', 'method': 'PUT', 'path': '/api/v1/llm-config/3',
        'headers': [(b'host', b'127.0.0.1:8888')], 'scheme': 'http',
        'server': ('127.0.0.1', 8888), 'query_string': b'',
    }
    return Request(scope)


class FakePayload:
    """模拟 LLMConfigUpdate"""
    model = 'glm-4.6'
    base_url = 'https://open.bigmodel.cn/api/paas/v4/'
    max_tokens = 8192
    temperature = 0.2
    timeout = 300
    description = '验证修复'


def run_binding(apply_fn):
    """把 apply_fn 产出的属性赋值到 ORM 对象，再触发一次真正的 SQLite 绑定"""
    engine = create_engine('sqlite://')
    LLMConfig.__table__.create(engine)
    config = LLMConfig(
        user_id=1, provider='zhipu', model='old-model', api_key='x',
        base_url='https://old.example.com/')
    attrs = apply_fn()
    for attr in ATTRS:
        val = getattr(attrs, attr, None)
        if val is not None:
            setattr(config, attr, val)

    from sqlalchemy.orm import sessionmaker
    session = sessionmaker(bind=engine)()
    session.add(config)
    session.flush()
    # 强制 UPDATE：改一个无关字段再 flush，触发完整参数绑定
    config.provider = 'zhipu'
    session.flush()
    row = session.query(LLMConfig).first()
    return row.base_url, type(row.base_url).__name__


# ── 旧逻辑：读 request ──────────────────────────────────────────
def old_apply():
    req = make_request()
    class Ctx:
        pass
    ctx = Ctx()
    for attr in ATTRS:
        setattr(ctx, attr, getattr(req, attr, None))
    return ctx


# ── 新逻辑：读 payload + base_url str() 兜底 ────────────────────
def new_apply():
    payload = FakePayload()
    class Ctx:
        pass
    ctx = Ctx()
    for attr in ATTRS:
        val = getattr(payload, attr, None)
        if val is not None and attr == 'base_url':
            val = str(val)
        setattr(ctx, attr, val)
    return ctx


if __name__ == '__main__':
    print('=== 复现旧逻辑（读 request.base_url）===')
    try:
        url, tname = run_binding(old_apply)
        print(f'绑定成功: {url!r} ({tname})  ← 不符合预期，未复现')
    except Exception as e:
        print(f'复现成功，报错类型: {type(e).__name__}')
        print(f'报错信息: {e}')

    print()
    print('=== 验证新逻辑（读 payload + str 兜底）===')
    url, tname = run_binding(new_apply)
    assert isinstance(url, str) and url == FakePayload.base_url, f'base_url 异常: {url!r}'
    print(f'绑定成功: {url!r} ({tname})')
    print('PASS: 修复生效')
