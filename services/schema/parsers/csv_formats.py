# -*- coding: UTF-8 -*-
"""CSV 格式 Schema 解析器 — 规范表头 CSV

规范格式（第一行为表头，列名大小写不敏感，支持别名）：
    schema_name | table_name | column_name | data_type | column_description
    table_description | is_nullable | default_value | column_key | foreign_key | sample_values

必需列：table_name、column_name（其余可空；schema_name 为空时使用 default_schema）
示例：
    schema_name,table_name,column_name,data_type,column_description,column_key
    shop,users,id,INT,用户ID,PRI
    shop,users,name,VARCHAR(50),用户名,
"""
import csv
import io
from typing import Any, Dict, List

from services.schema.parsers.base import DDLParseError

# 表头别名归一
_HEADER_ALIASES = {
    'schema_name': ('schema_name', 'database', 'db', '库名', '数据库'),
    'table_name': ('table_name', 'table', '表名'),
    'column_name': ('column_name', 'column', 'field', '字段名'),
    'data_type': ('data_type', 'column_type', 'type', '字段类型'),
    'column_description': ('column_description', 'description', 'comment', '字段描述', '字段说明'),
    'table_description': ('table_description', 'table_comment', '表描述', '表说明'),
    'is_nullable': ('is_nullable', 'nullable', '可空'),
    'default_value': ('default_value', 'default', '默认值'),
    'column_key': ('column_key', 'key', '键类型', '主键'),
    'foreign_key': ('foreign_key', 'fk', '外键'),
    'sample_values': ('sample_values', 'samples', '示例值'),
}


def _norm_header(raw: str) -> str:
    return raw.strip().strip('\ufeff').strip('"').strip("'").lower().replace(' ', '_')


def _resolve_header(name: str) -> str:
    n = _norm_header(name)
    for canonical, aliases in _HEADER_ALIASES.items():
        if n in aliases or n == canonical:
            return canonical
    return n


def _parse_bool(val: str):
    return str(val).strip().lower() in ('1', 'true', 'yes', 'y', '是')


def parse_schema_csv(csv_text: str, user_id: int,
                     default_schema: str = None) -> List[dict]:
    """解析规范 CSV 内容，返回与 JSON 解析器一致的解析结果列表"""
    if not csv_text or not csv_text.strip():
        raise DDLParseError("CSV 内容为空")

    reader = csv.reader(io.StringIO(csv_text.strip('\ufeff')), skipinitialspace=True)
    try:
        header_row = next(reader)
    except StopIteration:
        raise DDLParseError("CSV 为空，请检查内容")

    headers = [_resolve_header(h) for h in header_row]
    if 'table_name' not in headers or 'column_name' not in headers:
        raise DDLParseError(
            "CSV 表头必须包含 table_name（表名）和 column_name（字段名）两列；"
            "支持列：schema_name/table_name/column_name/data_type/column_description/...")

    results: List[dict] = []
    errors = []
    for idx, row in enumerate(reader, start=2):  # 第1行是表头
        if not row or not any(cell and cell.strip() for cell in row):
            continue  # 跳过空行
        record = {}
        for i, header in enumerate(headers):
            val = row[i].strip() if i < len(row) else ''
            if header == 'is_nullable':
                record[header] = _parse_bool(val) if val else True
            else:
                record[header] = val
        table_name = record.get('table_name', '')
        column_name = record.get('column_name', '')
        if not table_name or not column_name:
            errors.append(f"第 {idx} 行缺少表名或字段名")
            continue
        results.append({
            'schema_name': record.get('schema_name') or default_schema or 'default',
            'table_name': table_name,
            'table_description': record.get('table_description') or '',
            'column_name': column_name,
            'column_type': record.get('data_type') or '',
            'column_description': record.get('column_description') or '',
            'is_nullable': record.get('is_nullable', True),
            'default_value': record.get('default_value') or None,
            'column_key': record.get('column_key') or '',
            'foreign_key': record.get('foreign_key') or '',
            'sample_values': record.get('sample_values') or None,
        })

    if not results and errors:
        raise DDLParseError("；".join(errors[:5]))
    return results
