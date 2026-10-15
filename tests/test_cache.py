# -*- coding: UTF-8 -*-
"""TTL 缓存 — 纲领 §1（公共能力下沉）、§3.2（列表/详情短 TTL 缓存）

重点防回归：
    - 不同函数在相同参数下**不得互相撞键**（曾出现 list_schema_types
      返回 list_schema_names 结果的事故）
    - 主动失效应立即生效，不依赖 TTL 到期
    - 不可哈希参数（ORM Session）不得导致异常或缓存污染
    - maxsize 上限生效，防无界增长
"""
import time

from app.cache import TTLCache


def test_hit_after_first_call():
    c = TTLCache()
    calls = []

    @c.cached(ttl=5.0, namespace='t1')
    def f(x):
        calls.append(x)
        return x * 2

    assert f(3) == 6
    assert f(3) == 6
    assert len(calls) == 1, '第二次应命中缓存，不重复执行'


def test_different_functions_do_not_collide():
    """同参数不同函数必须各存各的 —— 撞键事故回归点"""
    c = TTLCache()

    @c.cached(ttl=5.0, namespace='collide')
    def fn_a(x):
        return ['list', x]

    @c.cached(ttl=5.0, namespace='collide')
    def fn_b(x):
        return {'dict': x}

    assert fn_a(1) == ['list', 1]
    assert fn_b(1) == {'dict': 1}
    assert fn_a(1) == ['list', 1]
    # 顺序打乱后仍不得互相污染
    assert fn_b(1) == {'dict': 1}
    assert fn_a(1) == ['list', 1]


def test_custom_key_fn_isolated_per_function():
    """自定义 key_fn 同样按函数隔离（key_fn 只给业务参数，函数名由装饰器加前缀）"""
    c = TTLCache()

    @c.cached(ttl=5.0, namespace='kf', key_fn=lambda db, ids=None: (ids,))
    def names(db, ids=None):
        return ['n']

    @c.cached(ttl=5.0, namespace='kf', key_fn=lambda db, ids=None: (ids,))
    def types(db, ids=None):
        return {'t': 1}

    assert names('SESSION', [1, 2]) == ['n']
    assert types('SESSION', [1, 2]) == {'t': 1}


def test_invalidate_namespace():
    c = TTLCache()
    calls = []

    @c.cached(ttl=60.0, namespace='inv')
    def f(x):
        calls.append(x)
        return x

    f(1)
    f(1)
    assert len(calls) == 1
    c.invalidate('inv')
    f(1)
    assert len(calls) == 2, '失效后应重新执行'


def test_invalidate_all():
    c = TTLCache()
    calls = []

    @c.cached(ttl=60.0, namespace='a')
    def fa(x):
        calls.append('a')
        return x

    @c.cached(ttl=60.0, namespace='b')
    def fb(x):
        calls.append('b')
        return x

    fa(1), fb(1)
    c.invalidate()
    fa(1), fb(1)
    assert calls == ['a', 'b', 'a', 'b']


def test_ttl_expiry():
    c = TTLCache()
    calls = []

    @c.cached(ttl=0.05, namespace='exp')
    def f(x):
        calls.append(x)
        return x

    f(1)
    f(1)
    assert len(calls) == 1
    time.sleep(0.08)
    f(1)
    assert len(calls) == 2, 'TTL 到期后应重新执行'


def test_unhashable_arg_skips_cache_without_error():
    """含不可哈希参数（模拟 ORM Session）时直接执行，不抛异常、不污染缓存"""
    c = TTLCache()
    calls = []

    @c.cached(ttl=5.0, namespace='unhash')
    def f(db, x):
        calls.append(x)
        return x

    class FakeSession:
        __hash__ = None  # 显式不可哈希

    s = FakeSession()
    assert f(s, 1) == 1
    assert f(s, 1) == 1
    assert len(calls) == 2, '不可哈希参数应跳过缓存'


def test_maxsize_eviction_does_not_grow_unbounded():
    c = TTLCache()
    store = c._store('bound', 60.0, maxsize=10)

    @c.cached(ttl=60.0, namespace='bound', maxsize=10)
    def f(x):
        return x

    for i in range(50):
        f(i)
    assert store.size() <= 10, f'缓存不得无界增长，实际 {store.size()}'