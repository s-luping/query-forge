# -*- coding: UTF-8 -*-
"""Schema 解析器包 — 仅保留规范 CSV / JSON 两种导入格式（DDL 解析已移除）

用法：
    from services.schema.parsers import parse_json_schema, parse_schema_csv, DDLParseError
"""
from typing import List

from services.schema.parsers.base import DDLParseError
from services.schema.parsers import json_formats, csv_formats

# 支持的数据库类型（用于导入时必填校验 / 前端下拉）
SUPPORTED_DB_TYPES = [
    "mysql", "mariadb", "postgresql", "postgres", "oracle",
    "sqlserver", "sqlite", "hive", "doris", "clickhouse"
]

# JSON 格式解析
parse_json_schema = json_formats.parse_json_schema
parse_spider_json = json_formats.parse_spider_json
parse_custom_json = json_formats.parse_custom_json

# CSV 格式解析
parse_schema_csv = csv_formats.parse_schema_csv

__all__ = [
    'DDLParseError', 'SUPPORTED_DB_TYPES',
    'parse_json_schema', 'parse_spider_json', 'parse_custom_json',
    'parse_schema_csv',
]
