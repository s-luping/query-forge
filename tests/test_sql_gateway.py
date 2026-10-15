# -*- coding: UTF-8 -*-
"""SQL 权限网关测试 — services/sql_gateway.py（纯 AST 部分，不依赖数据库）"""
import pytest
import sqlglot

from services.sql_gateway import SqlGateway, SqlGatewayResult

ADMIN = {'user_id': 1, 'username': 'tester', 'role': 'admin'}


@pytest.fixture()
def gateway(monkeypatch):
    """屏蔽 DB 权限加载，仅测 AST 静态校验"""
    monkeypatch.setattr(SqlGateway, '_load_permissions',
                        lambda self, schema_name, tables: None)
    return SqlGateway(ADMIN)


def test_select_star_blocked(gateway):
    """纲领 §2：禁止 SELECT *"""
    result = gateway.process('SELECT * FROM users', schema_name='test')
    assert not result.is_allowed
    assert 'SELECT *' in result.block_reason


def test_table_star_blocked(gateway):
    result = gateway.process('SELECT u.* FROM users u', schema_name='test')
    assert not result.is_allowed


def test_count_star_allowed(gateway):
    """函数内星号（COUNT(*)）放行"""
    result = gateway.process('SELECT COUNT(*) FROM users', schema_name='test')
    assert result.is_allowed


def test_invalid_sql_blocked(gateway):
    result = gateway.process('SELECT FROM WHERE (((', schema_name='test')
    assert not result.is_allowed
    assert '解析失败' in result.block_reason


def test_extract_tables():
    gateway = SqlGateway(ADMIN)
    tree = sqlglot.parse_one('SELECT a FROM db1.t1 JOIN db2.t2 ON 1=1')
    tables = gateway._extract_tables(tree)
    assert 'db1.t1' in tables
    assert 'db2.t2' in tables


def test_result_to_dict():
    r = SqlGatewayResult()
    d = r.to_dict()
    assert d['is_allowed'] is True and d['sql'] == ''
