# -*- coding: UTF-8 -*-
"""全库模式方言推断（_resolve_involved_db_type / _refine_dialect_db_type）回归

依赖本地元数据注册表现状：falcon_dev_14 注册类型为 mysql。
"""
import pytest

from core.gen_chat import _refine_dialect_db_type, _resolve_involved_db_type


def test_resolve_single_involved_schema():
    assert _resolve_involved_db_type({'falcon_dev_14'}) == 'mysql'


def test_resolve_empty_returns_none():
    assert _resolve_involved_db_type(set()) is None
    assert _resolve_involved_db_type(None) is None


def test_resolve_unregistered_schema_returns_none():
    assert _resolve_involved_db_type({'no_such_schema_xx'}) is None


def _agg(*schemas):
    return {'all_fields': {f'{s}.t.c': {'schema_name': s}
                           for s in schemas}}


def test_refine_skipped_for_bound_schema():
    """绑库模式路由层已按库类型精确解析，不得覆盖"""
    agg = _agg('falcon_dev_14')
    assert _refine_dialect_db_type(agg, 'falcon_dev_14', 'sqlite') == 'sqlite'


def test_refine_overrides_fallback_in_full_library_mode():
    agg = _agg('falcon_dev_14')
    assert _refine_dialect_db_type(agg, None, 'sqlite') == 'mysql'


def test_refine_no_involved_schemas_keeps_original():
    assert _refine_dialect_db_type({'all_fields': {}}, None, 'sqlite') == 'sqlite'


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
