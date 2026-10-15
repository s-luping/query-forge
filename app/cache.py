# -*- coding: UTF-8 -*-
"""短 TTL 缓存 — 纲领 §1「公共能力下沉共享层」、§3.2「列表/详情短 TTL 缓存」

统一实现，供权限判定（app/permissions.py）、元库查询（services/schema_service.py）
等高频重复读取场景复用；避免各模块各自手搓一份缓存逻辑。

设计要点：
    - 进程级、线程安全（threading.RLock），适合单进程 uvicorn 部署；
    - 短 TTL：只消除"同一请求/同一页面内重复查询"，不追求长期缓存；
    - 主动失效：写操作后调用 invalidate_* 立即清空，不依赖 TTL 到期；
    - maxsize 上限 + 过期清理，防无界增长（纲领 §6.1 反模式：无保留策略）。

用法：
    from app.cache import ttl_cache

    @ttl_cache(ttl=10.0, namespace='schema')
    def list_schema_names(visible_ids):
        ...

    ttl_cache.invalidate('schema')     # 写操作后主动失效该命名空间
"""
import functools
import threading
import time
from typing import Any, Callable, Dict, Hashable, Optional, Tuple


class _Store:
    """单个命名空间的 TTL 存储"""

    __slots__ = ('ttl', 'maxsize', '_data', '_lock', 'hits', 'misses')

    def __init__(self, ttl: float, maxsize: int = 1024):
        self.ttl = ttl
        self.maxsize = maxsize
        self._data: Dict[Hashable, Tuple[float, Any]] = {}
        self._lock = threading.RLock()
        self.hits = 0
        self.misses = 0

    def get(self, key: Hashable, default=None):
        with self._lock:
            item = self._data.get(key)
            if item is None:
                self.misses += 1
                return default
            ts, val = item
            if time.time() - ts > self.ttl:
                self._data.pop(key, None)
                self.misses += 1
                return default
            self.hits += 1
            return val

    def set(self, key: Hashable, value: Any) -> None:
        with self._lock:
            if len(self._data) >= self.maxsize:
                self._evict()
            self._data[key] = (time.time(), value)

    def _evict(self) -> None:
        """先清过期项；仍超限则按写入时间淘汰最旧的一批（调用方已持锁）"""
        now = time.time()
        expired = [k for k, (ts, _) in self._data.items() if now - ts > self.ttl]
        for k in expired:
            self._data.pop(k, None)
        if len(self._data) >= self.maxsize:
            oldest = sorted(self._data.items(), key=lambda kv: kv[1][0])
            for k, _ in oldest[: max(1, self.maxsize // 4)]:
                self._data.pop(k, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._data)

    def stats(self) -> dict:
        with self._lock:
            total = self.hits + self.misses
            return {'size': len(self._data), 'hits': self.hits,
                    'misses': self.misses,
                    'hit_rate': round(self.hits / total, 3) if total else 0.0}


class TTLCache:
    """多命名空间 TTL 缓存注册表"""

    def __init__(self):
        self._stores: Dict[str, _Store] = {}
        self._lock = threading.RLock()

    def _store(self, namespace: str, ttl: float, maxsize: int) -> _Store:
        with self._lock:
            st = self._stores.get(namespace)
            if st is None:
                st = self._stores[namespace] = _Store(ttl, maxsize)
            return st

    def get(self, namespace: str, key: Hashable, default=None):
        with self._lock:
            st = self._stores.get(namespace)
        return st.get(key, default) if st else default

    def set(self, namespace: str, key: Hashable, value: Any,
            ttl: float = 60.0, maxsize: int = 1024) -> None:
        self._store(namespace, ttl, maxsize).set(key, value)

    def invalidate(self, namespace: Optional[str] = None) -> None:
        """失效指定命名空间；namespace 为空时清空全部"""
        with self._lock:
            if namespace is None:
                for st in self._stores.values():
                    st.clear()
                return
            st = self._stores.get(namespace)
        if st:
            st.clear()

    def stats(self) -> dict:
        with self._lock:
            return {ns: st.stats() for ns, st in self._stores.items()}

    def cached(self, ttl: float, namespace: str, maxsize: int = 1024,
               key_fn: Optional[Callable] = None):
        """装饰器 — 按参数生成缓存键

        自动跳过不可哈希的参数（如 SQLAlchemy Session）：调用时若 key_fn 未提供，
        则对所有位置/关键字参数做 hashable 化尝试，任一不可哈希即整键退化为
        "不缓存"（直接执行原函数），保证正确性优先。
        """
        def deco(fn: Callable):
            store = self._store(namespace, ttl, maxsize)
            fn_name = getattr(fn, '__qualname__', fn.__name__)

            @functools.wraps(fn)
            def wrapper(*args, **kwargs):
                if key_fn is not None:
                    try:
                        raw = key_fn(*args, **kwargs)
                    except Exception:
                        return fn(*args, **kwargs)
                    key = _hashable(raw)
                    if key is _UNHASHABLE:
                        return fn(*args, **kwargs)
                else:
                    key = _default_key(fn, args, kwargs)
                    if key is None:
                        return fn(*args, **kwargs)
                # 统一前缀函数名：防止不同函数在相同参数下互相撞键
                # （key_fn 只按业务参数生成键时，同命名空间内会冲突）
                key = (fn_name, key)
                sentinel = _SENTINEL
                hit = store.get(key, sentinel)
                if hit is not sentinel:
                    return hit
                val = fn(*args, **kwargs)
                store.set(key, val)
                return val

            wrapper.cache_invalidate = store.clear  # type: ignore[attr-defined]
            wrapper.cache_stats = store.stats        # type: ignore[attr-defined]
            return wrapper

        return deco


_SENTINEL = object()


def _hashable(v: Any) -> Any:
    """把常见容器转为可哈希形式；不可哈希（含 ORM Session）返回 _UNHASHABLE"""
    if isinstance(v, (str, int, float, bool, bytes, type(None))):
        return v
    if isinstance(v, (list, tuple, set, frozenset)):
        out = []
        for i in v:
            h = _hashable(i)
            if h is _UNHASHABLE:
                return _UNHASHABLE
            out.append(h)
        return tuple(out)
    if isinstance(v, dict):
        out = []
        for k, val in sorted(v.items(), key=lambda kv: str(kv[0])):
            hk, hv = _hashable(k), _hashable(val)
            if hk is _UNHASHABLE or hv is _UNHASHABLE:
                return _UNHASHABLE
            out.append((hk, hv))
        return tuple(out)
    return _UNHASHABLE


_UNHASHABLE = object()


def _default_key(fn: Callable, args: tuple, kwargs: dict):
    """由函数名 + 参数生成缓存键；含不可哈希参数时返回 None（调用方不缓存）"""
    parts = [getattr(fn, '__qualname__', fn.__name__)]
    for a in args:
        h = _hashable(a)
        if h is _UNHASHABLE:
            return None
        parts.append(h)
    for k in sorted(kwargs):
        h = _hashable(kwargs[k])
        if h is _UNHASHABLE:
            return None
        parts.append((k, h))
    return tuple(parts)


# 全局注册表
ttl_cache = TTLCache()