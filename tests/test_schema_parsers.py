# -*- coding: UTF-8 -*-
"""元数据解析测试 — services/schema_parsers.py"""
import pytest

from services.schema_parsers import DDLParseError, parse_schema_csv

CSV_OK = """schema_name,table_name,table_description,column_name,data_type,column_description
ods,orders,订单表,order_id,BIGINT,订单ID
ods,orders,订单表,user_id,BIGINT,用户ID
ods,users,用户表,user_id,BIGINT,用户ID
"""

CSV_MISSING_COLUMN = """table_name,column_name
orders,
"""


def test_parse_csv_basic():
    results = parse_schema_csv(CSV_OK, user_id=1)
    assert len(results) == 3
    first = results[0]
    assert first['schema_name'] == 'ods'
    assert first['table_name'] == 'orders'
    assert first['column_name'] == 'order_id'
    assert first['column_type'] == 'BIGINT'


def test_parse_csv_default_schema():
    csv_text = 'table_name,column_name\nt1,c1\n'
    results = parse_schema_csv(csv_text, user_id=1)
    assert results[0]['schema_name'] == 'default'


def test_parse_csv_empty():
    with pytest.raises(DDLParseError):
        parse_schema_csv('', user_id=1)


def test_parse_csv_bad_header():
    with pytest.raises(DDLParseError):
        parse_schema_csv('foo,bar\n1,2\n', user_id=1)


def test_parse_csv_missing_column_name():
    with pytest.raises(DDLParseError):
        parse_schema_csv(CSV_MISSING_COLUMN, user_id=1)


def test_parse_csv_blank_rows_skipped():
    csv_text = CSV_OK + ',,,,\n'
    assert len(parse_schema_csv(csv_text, user_id=1)) == 3
