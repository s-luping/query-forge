# -*- coding: UTF-8 -*-
"""全库模式 SQL 漏前缀确定性修复（_repair_missing_schema_prefix）回归

覆盖：唯一归属补前缀 / 跨库同名不猜 / CTE 名不误补 / 已带前缀原样返回 /
无前缀但元数据无此表原样返回。依赖本地元数据注册表现状：
  - toy_sales 仅存在于 falcon_dev_14
  - products 同时存在于 milk_tea_sales 与 northwind（跨库同名）
"""
import pytest

from services.sql_executor import _repair_missing_schema_prefix


def test_repairs_unique_owner_table():
    sql = 'SELECT city FROM toy_sales JOIN toy_stores USING (Store_ID)'
    out = _repair_missing_schema_prefix(sql, 'mysql')
    assert 'falcon_dev_14.toy_sales' in out
    assert 'falcon_dev_14.toy_stores' in out


def test_ambiguous_table_left_untouched():
    sql = 'SELECT price FROM products'
    out = _repair_missing_schema_prefix(sql, 'mysql')
    assert out == sql, '跨库同名表（milk_tea_sales/northwind 均有 products）不得猜测补前缀'


def test_cte_name_not_rewritten():
    sql = ('WITH toy_sales AS (SELECT 1 AS id) '
           'SELECT id FROM toy_sales')
    out = _repair_missing_schema_prefix(sql, 'mysql')
    assert 'falcon_dev_14' not in out, 'CTE 名与真实表同名时不得误补前缀'


def test_fully_prefixed_sql_returned_unchanged():
    sql = 'SELECT s.Store_City FROM falcon_dev_14.toy_sales s'
    out = _repair_missing_schema_prefix(sql, 'mysql')
    assert out == sql, '已带前缀无需修补时应原样返回（不做 round-trip）'


def test_unknown_table_returned_unchanged():
    sql = 'SELECT * FROM no_such_table_anywhere'
    out = _repair_missing_schema_prefix(sql, 'mysql')
    assert out == sql, '元数据无此表（幻觉表）时保持原样，走既有报错路径'


def test_mixed_prefix_repaired_for_bare_only():
    sql = ('SELECT s.Store_City FROM toy_sales s '
           'JOIN falcon_dev_14.toy_stores s2 ON s.Store_ID = s2.Store_ID')
    out = _repair_missing_schema_prefix(sql, 'mysql')
    assert 'falcon_dev_14.toy_sales' in out
    assert 'falcon_dev_14.toy_stores' in out
    # 已带前缀的表不重复改写（sqlglot 会把别名渲染为 AS s）
    assert out.count('falcon_dev_14.toy_sales') == 1
    assert out.count('falcon_dev_14.toy_stores') == 1


def test_parse_failure_returns_original():
    sql = 'SELECT FROM FROM WHERE (((('
    out = _repair_missing_schema_prefix(sql, 'mysql')
    assert out == sql, '解析失败必须原样返回，不阻断执行主流程'


# ---------- info 留痕（P1 链路追踪 PREFIX_REPAIR 步，docs §5.2） ----------

def test_info_reports_repaired_tables():
    info = {}
    sql = 'SELECT city FROM toy_sales JOIN toy_stores USING (Store_ID)'
    _repair_missing_schema_prefix(sql, 'mysql', info=info)
    assert sorted(info['repaired']) == [
        'toy_sales → falcon_dev_14', 'toy_stores → falcon_dev_14']
    assert info['bare_tables'] == ['toy_sales', 'toy_stores']
    assert info['ambiguous'] == [] and info['unknown'] == []


def test_info_reports_ambiguous_and_unknown():
    info = {}
    _repair_missing_schema_prefix('SELECT price FROM products', 'mysql', info=info)
    assert info['repaired'] == []
    assert info['ambiguous'] == ['products'], '跨库同名表应记入 ambiguous（不猜）'

    info2 = {}
    _repair_missing_schema_prefix('SELECT * FROM no_such_table_anywhere', 'mysql', info=info2)
    assert info2['repaired'] == []
    assert info2['unknown'] == ['no_such_table_anywhere'], '元数据无此表应记入 unknown（幻觉表）'


def test_info_parse_failure_sets_error():
    info = {}
    _repair_missing_schema_prefix('SELECT FROM FROM WHERE ((((', 'mysql', info=info)
    assert '解析失败' in info['error']
    assert set(info.keys()) == {'error'}, '解析失败时不产出其他字段'


def test_info_no_bare_tables_clean_report():
    info = {}
    _repair_missing_schema_prefix(
        'SELECT s.Store_City FROM falcon_dev_14.toy_sales s', 'mysql', info=info)
    assert info == {'bare_tables': [], 'repaired': [], 'ambiguous': [], 'unknown': []}


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
