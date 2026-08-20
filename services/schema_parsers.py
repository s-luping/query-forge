# -*- coding: UTF-8 -*-
"""Schema 解析器 — CSV / JSON 两种导入格式（合并自 parsers/base.py + csv_formats.py + json_formats.py）

用法：
    from services.schema_parsers import parse_json_schema, parse_schema_csv, DDLParseError
"""
import csv
import io
import json
import re
from typing import Any, Dict, List


# ── 共享异常 ──────────────────────────────────────────────

class DDLParseError(Exception):
    """DDL 解析错误"""
    pass


def extract_table_spans(ddl: str, create_pattern: str):
    matches = list(re.finditer(create_pattern, ddl, re.IGNORECASE))
    spans = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(ddl)
        spans.append(ddl[start:end])
    return spans


def check_duplicate_tables(ddl: str, create_pattern: str, group: int = 1, normalize=None):
    names = []
    for m in re.finditer(create_pattern, ddl, re.IGNORECASE):
        name = m.group(group)
        if normalize:
            name = normalize(name)
        if name in names:
            raise DDLParseError(f"表名重复：{name}")
        names.append(name)
    return names


# ── CSV 格式解析 ──────────────────────────────────────────

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
    """解析规范 CSV 内容"""
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
            "CSV 表头必须包含 table_name（表名）和 column_name（字段名）两列")

    results: List[dict] = []
    errors = []
    for idx, row in enumerate(reader, start=2):
        if not row or not any(cell and cell.strip() for cell in row):
            continue
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


# ── JSON 格式解析 ──────────────────────────────────────────

def parse_spider_json(json_data: Dict[str, Any], user_id: int, default_schema: str = None) -> List[dict]:
    """解析 Spider 数据集格式的 JSON"""
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
                fk_map[f"{src_table}.{src_col}"] = f"{tgt_table}.{tgt_col}"

    for i, col_info in enumerate(column_names_original):
        if not isinstance(col_info, list) or len(col_info) < 2:
            continue
        table_idx = col_info[0]
        column_name = col_info[1]
        if table_idx == -1 or column_name == '*':
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
            'user_id': user_id, 'schema_name': schema_name, 'table_name': table_name,
            'table_description': table_description if table_description != table_name else '',
            'column_name': column_name, 'column_type': column_type,
            'column_description': column_description if column_description != column_name else '',
            'column_key': 'PRI' if is_pk else '',
            'foreign_key': fk_map.get(f"{table_name}.{column_name}", ''),
            'is_nullable': True, 'default_value': None, 'sample_values': None,
        })
    return results


def parse_custom_json(data: Dict[str, Any], user_id: int, default_schema: str = None) -> List[dict]:
    """解析自定义 JSON 格式"""
    results = []
    schema_name = data.get('schema_name', data.get('db_id', default_schema or 'default'))
    for table in data.get('tables', []):
        table_name = table.get('name', '')
        table_description = table.get('description', '')
        for col in table.get('columns', []):
            results.append({
                'user_id': user_id, 'schema_name': schema_name, 'table_name': table_name,
                'table_description': table_description, 'column_name': col.get('name', ''),
                'column_type': col.get('type', 'text'), 'column_description': col.get('description', ''),
                'column_key': 'PRI' if col.get('primary_key', False) else '',
                'foreign_key': col.get('foreign_key', ''), 'is_nullable': col.get('nullable', True),
                'default_value': col.get('default', None), 'sample_values': None,
            })
    return results


def parse_json_schema(json_text: str, user_id: int, default_schema: str = None) -> List[dict]:
    """解析 JSON 格式的 schema（支持 Spider 格式和自定义格式）"""
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as e:
        raise DDLParseError(f"JSON 格式错误: {e}")

    if isinstance(data, list):
        all_results = []
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


# ── 注册表 ─────────────────────────────────────────────────

SUPPORTED_DB_TYPES = [
    "mysql", "mariadb", "postgresql", "postgres", "oracle",
    "sqlserver", "sqlite", "hive", "doris", "clickhouse"
]

__all__ = [
    'DDLParseError', 'SUPPORTED_DB_TYPES',
    'parse_json_schema', 'parse_spider_json', 'parse_custom_json', 'parse_schema_csv',
]
