# -*- coding: UTF-8 -*-
"""JSON 格式 Schema 解析器（Spider 数据集格式 + 自定义格式）"""
import json
from typing import Any, Dict, List

from services.schema.parsers.base import DDLParseError


def parse_spider_json(json_data: Dict[str, Any], user_id: int, default_schema: str = None) -> List[dict]:
    """
    解析 Spider 数据集格式的 JSON
    格式说明：
    - db_id: 数据库名称
    - table_names_original: 原始表名列表
    - table_names: 表名描述列表
    - column_names_original: [[表索引, 列名], ...] (-1 表示全局)
    - column_names: [[表索引, 列描述], ...]
    - column_types: 列类型列表
    - primary_keys: 主键索引列表
    - foreign_keys: [[源列索引, 目标列索引], ...]
    """
    results = []

    schema_name = json_data.get('db_id', default_schema or 'default')

    table_names_original = json_data.get('table_names_original', [])
    table_names = json_data.get('table_names', table_names_original)
    column_names_original = json_data.get('column_names_original', [])
    column_names = json_data.get('column_names', column_names_original)
    column_types = json_data.get('column_types', [])
    primary_keys = json_data.get('primary_keys', [])
    foreign_keys = json_data.get('foreign_keys', [])

    table_desc_map = {}
    for i, tname in enumerate(table_names_original):
        table_desc_map[i] = table_names[i] if i < len(table_names) else tname

    col_idx_map = {}
    for i, col_info in enumerate(column_names_original):
        if isinstance(col_info, list) and len(col_info) >= 2:
            col_idx_map[i] = (col_info[0], col_info[1])

    fk_map = {}
    for fk in foreign_keys:
        if isinstance(fk, list) and len(fk) >= 2:
            src_idx, tgt_idx = fk[0], fk[1]
            src_table_idx, src_col = col_idx_map.get(src_idx, (None, None))
            tgt_table_idx, tgt_col = col_idx_map.get(tgt_idx, (None, None))
            if src_table_idx is not None and tgt_table_idx is not None:
                src_table = table_names_original[src_table_idx] if src_table_idx < len(table_names_original) else f"table_{src_table_idx}"
                tgt_table = table_names_original[tgt_table_idx] if tgt_table_idx < len(table_names_original) else f"table_{tgt_table_idx}"
                fk_key = f"{src_table}.{src_col}"
                fk_map[fk_key] = f"{tgt_table}.{tgt_col}"

    for i, col_info in enumerate(column_names_original):
        if not isinstance(col_info, list) or len(col_info) < 2:
            continue

        table_idx = col_info[0]
        column_name = col_info[1]

        if table_idx == -1:
            continue

        if column_name == '*':
            continue

        table_name = table_names_original[table_idx] if table_idx < len(table_names_original) else f"table_{table_idx}"
        table_description = table_desc_map.get(table_idx, '')

        col_desc_info = column_names[i] if i < len(column_names) else col_info
        column_description = col_desc_info[1] if isinstance(col_desc_info, list) and len(col_desc_info) > 1 else ''

        column_type = column_types[i] if i < len(column_types) else 'text'

        is_pk = False
        for pk in primary_keys:
            if isinstance(pk, list):
                if i in pk:
                    is_pk = True
                    break
            elif pk == i:
                is_pk = True
                break

        results.append({
            'user_id': user_id,
            'schema_name': schema_name,
            'table_name': table_name,
            'table_description': table_description if table_description != table_name else '',
            'column_name': column_name,
            'column_type': column_type,
            'column_description': column_description if column_description != column_name else '',
            'column_key': 'PRI' if is_pk else '',
            'foreign_key': fk_map.get(f"{table_name}.{column_name}", ''),
            'is_nullable': True,
            'default_value': None,
            'sample_values': None
        })

    return results


def parse_custom_json(data: Dict[str, Any], user_id: int, default_schema: str = None) -> List[dict]:
    """
    解析自定义 JSON 格式
    格式示例：
    {
        "schema_name": "mydb",
        "tables": [
            {
                "name": "user",
                "description": "用户表",
                "columns": [
                    {"name": "id", "type": "int", "description": "用户ID", "primary_key": true},
                    {"name": "name", "type": "varchar(100)", "description": "用户名"}
                ]
            }
        ]
    }
    """
    results = []

    schema_name = data.get('schema_name', data.get('db_id', default_schema or 'default'))
    tables = data.get('tables', [])

    for table in tables:
        table_name = table.get('name', '')
        table_description = table.get('description', '')
        columns = table.get('columns', [])

        for col in columns:
            results.append({
                'user_id': user_id,
                'schema_name': schema_name,
                'table_name': table_name,
                'table_description': table_description,
                'column_name': col.get('name', ''),
                'column_type': col.get('type', 'text'),
                'column_description': col.get('description', ''),
                'column_key': 'PRI' if col.get('primary_key', False) else '',
                'foreign_key': col.get('foreign_key', ''),
                'is_nullable': col.get('nullable', True),
                'default_value': col.get('default', None),
                'sample_values': None
            })

    return results


def parse_json_schema(json_text: str, user_id: int, default_schema: str = None) -> List[dict]:
    """
    解析 JSON 格式的 schema（支持 Spider 格式和自定义格式，支持多数据库）
    """
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as e:
        raise DDLParseError(f"JSON 格式错误: {e}")

    all_results = []

    if isinstance(data, list):
        for item in data:
            if 'table_names_original' in item or 'column_names_original' in item:
                all_results.extend(parse_spider_json(item, user_id, default_schema))
            elif 'tables' in item:
                all_results.extend(parse_custom_json(item, user_id, default_schema))
        return all_results

    if 'table_names_original' in data or 'column_names_original' in data:
        return parse_spider_json(data, user_id, default_schema)

    if 'tables' in data:
        return parse_custom_json(data, user_id, default_schema)

    raise DDLParseError("无法识别的 JSON 格式，请使用 Spider 格式或自定义格式")
