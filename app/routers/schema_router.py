# -*- coding: UTF-8 -*-
"""
Schema 管理路由 - 支持多种数据库 DDL 解析和 JSON 格式解析
支持的数据库类型：
- MySQL / MariaDB
- PostgreSQL
- Oracle
- SQL Server
- SQLite
- Hive
- Doris
- ClickHouse
"""
import csv
import io
import json
import re
import threading
from datetime import datetime
from typing import List, Optional, Dict, Any

_vector_build_lock = threading.Lock()

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.logger import logger, log_audit
from app.permissions import get_visible_schema_names


def _filter_by_schema_names(query, user: dict, model):
    """对读查询追加 schema 可见性过滤"""
    names = get_visible_schema_names(user)
    if names is not None:  # None=全部可见，list=仅这些
        if not names:
            return query.filter(model.id < 0)  # 空列表 → 无可见数据
        return query.filter(model.schema_name.in_(names))
    return query


def _admin_only(user: dict):
    """非管理员拒绝访问"""
    from fastapi import HTTPException
    if user.get('role') != 'admin':
        raise HTTPException(status_code=403, detail="仅管理员可执行此操作")
from models import SchemaSessionLocal
from models.schema import Schema

router = APIRouter()


class DDLParseRequest(BaseModel):
    """DDL 解析请求"""
    ddl_text: str
    schema_name: str = "default"
    db_type: str = "mysql"


class JSONParseRequest(BaseModel):
    """JSON 解析请求"""
    json_text: str
    schema_name: str = "default"


class SchemaItem(BaseModel):
    """Schema 解析项"""
    id: int
    schema_name: str
    table_name: str
    table_description: Optional[str]
    column_name: str
    column_type: Optional[str]
    column_description: Optional[str]
    column_key: Optional[str]
    foreign_key: Optional[str] = None
    is_nullable: Optional[bool] = True
    default_value: Optional[str] = None
    sample_values: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class UpdateSampleValuesRequest(BaseModel):
    """更新示例值请求"""
    sample_values: str


class SchemaListResponse(BaseModel):
    """Schema 解析列表响应"""
    items: List[SchemaItem]
    total: int
    message: Optional[str] = None


class SchemaCheckResponse(BaseModel):
    """Schema 检查响应"""
    has_schema: bool
    schema_count: int
    table_count: int


class CreateTableRequest(BaseModel):
    """建表请求"""
    schema_name: Optional[str] = None
    table_name: Optional[str] = None
    ids: Optional[List[int]] = None


class CreateTableResponse(BaseModel):
    """建表响应"""
    success: bool
    message: str
    table_name: str


class DDLParseError(Exception):
    """DDL 解析错误"""
    pass


SUPPORTED_DB_TYPES = [
    "mysql", "mariadb", "postgresql", "postgres", "oracle", 
    "sqlserver", "sqlite", "hive", "doris", "clickhouse"
]


def _check_embedding_ready():
    """检查嵌入模型是否就绪，未就绪则抛出 400 错误"""
    from core.VectorStore import EmbeddingModel
    if not EmbeddingModel.is_ready():
        raise HTTPException(
            status_code=400,
            detail="Embedding 模型未就绪，请先在系统设置中下载模型"
        )


def _mark_index_stale(schema_name: str):
    """标记索引为过期（数据有新增但索引未更新）"""
    try:
        from core.SQLPipeline import _set_index_meta
        _set_index_meta(schema_name, 'stale')
    except Exception:
        pass


def _auto_build_vector_index(schema_name: str, schema_field_count: int) -> Optional[str]:
    from core.VectorStore import EmbeddingModel, get_vector_config

    if not EmbeddingModel.is_ready():
        logger.warning(f"Embedding 模型未就绪，跳过自动索引构建: {schema_name}")
        return None

    threshold = get_vector_config('VECTOR_INDEX_THRESHOLD')
    if schema_field_count < threshold:
        logger.info(f"Schema {schema_name} 字段数量 {schema_field_count} 未达到阈值 {threshold}，跳过自动索引构建")
        return None

    # 先标记为过期（新数据已入库，索引待更新）
    _mark_index_stale(schema_name)

    def _build_in_background():
        from core.SQLPipeline import build_vector_index, _get_index_meta
        max_retries = 3
        for attempt in range(max_retries):
            with _vector_build_lock:
                # 检查是否仍需构建（可能被上一轮修复了）
                meta = _get_index_meta(schema_name)
                if meta and meta['status'] == 'ready':
                    logger.info(f"Schema {schema_name} 索引已就绪，跳过构建（attempt {attempt+1}）")
                    return

                try:
                    logger.info(f"开始构建向量索引: {schema_name} (attempt {attempt+1})")
                    result = build_vector_index(schema_name)
                    if result.get('success'):
                        logger.info(f"Schema {schema_name} 向量索引构建完成")
                except Exception as e:
                    logger.warning(f"后台构建向量索引失败: {e}")
                    return  # 构建失败不重试

            # 释放锁后再次检查：构建期间是否有新数据导入导致索引再次过期
            if attempt < max_retries - 1:
                import time
                time.sleep(0.5)  # 短暂等待，让并发导入有时间标记 stale
                meta = _get_index_meta(schema_name)
                if meta and meta['status'] != 'stale':
                    return  # 索引已是最新，无需再构建

    thread = threading.Thread(target=_build_in_background, daemon=True)
    thread.start()
    return f"Schema {schema_name} 正在后台创建向量索引（字段数: {schema_field_count}）"


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
    relations = []

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
    
    col_idx = 0
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


def parse_json_schema(json_text: str, user_id: int, default_schema: str = None) -> List[dict]:
    """
    解析 JSON 格式的 schema（支持 Spider 格式和自定义格式，支持多数据库）

    如果 JSON 中包含 db_id 或 schema_name，则使用该值作为 schema_name
    如果是数组，则解析所有数据库定义
    """
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as e:
        raise DDLParseError(f"JSON 格式错误: {e}")

    all_results = []

    if isinstance(data, list):
        for item in data:
            if 'table_names_original' in item or 'column_names_original' in item:
                results = parse_spider_json(item, user_id, default_schema)
                all_results.extend(results)
            elif 'tables' in item:
                results = parse_custom_json(item, user_id, default_schema)
                all_results.extend(results)
        return all_results

    if 'table_names_original' in data or 'column_names_original' in data:
        return parse_spider_json(data, user_id, default_schema)

    if 'tables' in data:
        return parse_custom_json(data, user_id, default_schema)

    raise DDLParseError("无法识别的 JSON 格式，请使用 Spider 格式或自定义格式")


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
            column_name = col.get('name', '')
            column_type = col.get('type', 'text')
            column_description = col.get('description', '')
            is_pk = col.get('primary_key', False)
            is_nullable = col.get('nullable', True)
            default_value = col.get('default', None)
            
            results.append({
                'user_id': user_id,
                'schema_name': schema_name,
                'table_name': table_name,
                'table_description': table_description,
                'column_name': column_name,
                'column_type': column_type,
                'column_description': column_description,
                'column_key': 'PRI' if is_pk else '',
                'is_nullable': is_nullable,
                'default_value': default_value,
                'sample_values': None
            })
    
    return results


def detect_db_type(ddl: str) -> str:
    """自动检测数据库类型"""
    ddl_upper = ddl.upper()
    
    if 'ENGINE=' in ddl_upper or 'AUTO_INCREMENT' in ddl_upper:
        return 'mysql'
    
    if 'SERIAL' in ddl_upper or 'BIGSERIAL' in ddl_upper or 'RETURNING' in ddl_upper:
        return 'postgresql'
    
    if 'NUMBER(' in ddl_upper or 'VARCHAR2' in ddl_upper:
        return 'oracle'
    
    if 'IDENTITY(' in ddl_upper or 'NVARCHAR' in ddl_upper:
        return 'sqlserver'
    
    if 'STORED AS' in ddl_upper or 'ROW FORMAT' in ddl_upper or 'TBLPROPERTIES' in ddl_upper:
        return 'hive'
    
    if 'DUPLICATE KEY' in ddl_upper or 'AGGREGATE KEY' in ddl_upper or 'DISTRIBUTED BY' in ddl_upper:
        return 'doris'
    
    if 'ENGINE = MergeTree' in ddl_upper or 'ORDER BY' in ddl_upper and 'MergeTree' in ddl_upper:
        return 'clickhouse'
    
    return 'mysql'


def extract_db_names_from_ddl(ddl: str) -> List[str]:
    """从 DDL 中提取数据库名称"""
    db_names = []
    
    create_db_pattern = r'CREATE\s+DATABASE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?([^`\s;]+)`?'
    for m in re.finditer(create_db_pattern, ddl, re.IGNORECASE):
        db_name = m.group(1).strip('`')
        if db_name not in db_names:
            db_names.append(db_name)
    
    use_pattern = r'USE\s+`?([^`\s;]+)`?\s*;'
    for m in re.finditer(use_pattern, ddl, re.IGNORECASE):
        db_name = m.group(1).strip('`')
        if db_name not in db_names:
            db_names.append(db_name)
    
    return db_names


def split_ddl_by_database(ddl: str) -> Dict[str, str]:
    """
    按 CREATE DATABASE 或 USE 语句分割 DDL
    返回 {schema_name: ddl_content} 的映射
    """
    result = {}
    
    create_db_pattern = r'CREATE\s+DATABASE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?([^`\s;]+)`?[^;]*;'
    use_pattern = r'USE\s+`?([^`\s;]+)`?\s*;'
    
    markers = []
    
    for m in re.finditer(create_db_pattern, ddl, re.IGNORECASE):
        db_name = m.group(1).strip('`')
        markers.append((m.end(), db_name))
    
    for m in re.finditer(use_pattern, ddl, re.IGNORECASE):
        db_name = m.group(1).strip('`')
        markers.append((m.end(), db_name))
    
    markers.sort(key=lambda x: x[0])
    
    if not markers:
        return {'default': ddl}
    
    for i, (pos, db_name) in enumerate(markers):
        start = pos
        end = markers[i + 1][0] if i + 1 < len(markers) else len(ddl)
        content = ddl[start:end].strip()
        if content:
            if db_name not in result:
                result[db_name] = ''
            result[db_name] += '\n' + content
    
    return result


def parse_ddl(ddl: str, user_id: int, default_schema: str = None, db_type: str = "mysql") -> List[dict]:
    """
    解析 DDL 语句并返回解析结果（支持多数据库）
    
    如果 DDL 中包含 CREATE DATABASE 或 USE 语句，则使用该数据库名作为 schema_name
    否则使用 default_schema 或 'default'
    """
    results = []
    
    db_names = extract_db_names_from_ddl(ddl)
    
    if len(db_names) > 1:
        ddl_parts = split_ddl_by_database(ddl)
        for schema_name, ddl_content in ddl_parts.items():
            if ddl_content.strip():
                part_results = parse_ddl_single_db(ddl_content, schema_name, user_id, db_type)
                results.extend(part_results)
        return results
    
    schema_name = db_names[0] if db_names else (default_schema or 'default')
    return parse_ddl_single_db(ddl, schema_name, user_id, db_type)


def parse_ddl_single_db(ddl: str, schema_name: str, user_id: int, db_type: str = "mysql") -> List[dict]:
    """解析单个数据库的 DDL"""
    if not db_type or db_type == "auto":
        db_type = detect_db_type(ddl)
    
    db_type = db_type.lower()
    
    if db_type in ['hive', 'doris', 'clickhouse']:
        return parse_ddl_data_warehouse(ddl, schema_name, user_id, db_type)
    elif db_type in ['postgresql', 'postgres']:
        return parse_ddl_postgresql(ddl, schema_name, user_id)
    elif db_type == 'oracle':
        return parse_ddl_oracle(ddl, schema_name, user_id)
    elif db_type == 'sqlserver':
        return parse_ddl_sqlserver(ddl, schema_name, user_id)
    else:
        return parse_ddl_mysql(ddl, schema_name, user_id)


def parse_ddl_mysql(ddl: str, schema_name: str, user_id: int) -> List[dict]:
    """解析 MySQL/MariaDB DDL"""
    results = []
    
    create_table_pattern = r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?([^`\s(]+)`?\s*\('
    create_matches = list(re.finditer(create_table_pattern, ddl, re.IGNORECASE))

    if not create_matches:
        return results

    table_names = []
    for m in create_matches:
        table_name = m.group(1).strip('`')
        if table_name in table_names:
            raise DDLParseError(f"表名重复：{table_name}。DDL 中存在同名表，请检查 DDL 内容。")
        table_names.append(table_name)

    for i, match in enumerate(create_matches):
        start_pos = match.start()

        if i + 1 < len(create_matches):
            end_pos = create_matches[i + 1].start()
        else:
            end_pos = len(ddl)

        table_ddl = ddl[start_pos:end_pos]
        table_results = parse_single_table_mysql(table_ddl, schema_name, user_id)
        results.extend(table_results)

    return results


def parse_single_table_mysql(table_ddl: str, schema_name: str, user_id: int) -> List[dict]:
    """解析单个 MySQL CREATE TABLE 语句"""
    results = []

    table_name_match = re.search(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?([^`\s(]+)`?\s*\(', table_ddl,
                                 re.IGNORECASE)
    if not table_name_match:
        return results

    table_name = table_name_match.group(1).strip('`')

    paren_start = table_name_match.end() - 1

    paren_count = 0
    paren_end = -1
    for i in range(paren_start, len(table_ddl)):
        if table_ddl[i] == '(':
            paren_count += 1
        elif table_ddl[i] == ')':
            paren_count -= 1
            if paren_count == 0:
                paren_end = i
                break

    if paren_end == -1:
        return results

    table_struct = table_ddl[paren_start + 1:paren_end]

    table_comment = ''
    rest_of_ddl = table_ddl[paren_end + 1:]
    table_comment_match = re.search(
        r"COMMENT\s*=?\s*['\"]([^'\"]+)['\"]", rest_of_ddl, re.IGNORECASE)
    if table_comment_match:
        table_comment = table_comment_match.group(1)

    pk_match = re.search(
        r'PRIMARY KEY\s*\(([^)]+)\)', table_struct, re.IGNORECASE)
    primary_keys = []
    if pk_match:
        pk_str = pk_match.group(1)
        primary_keys = [pk.strip().strip('`') for pk in pk_str.split(',')]

    fk_pattern = r'FOREIGN\s+KEY\s*\(`?([^`)]+)`?\)\s*REFERENCES\s+`?([^`\s(]+)`?\s*\(`?([^`)]+)`?\)'
    fk_matches = re.finditer(fk_pattern, table_struct, re.IGNORECASE)
    fk_map = {}
    for fk in fk_matches:
        col_name = fk.group(1).strip('`')
        ref_table = fk.group(2).strip('`')
        ref_col = fk.group(3).strip('`')
        fk_map[col_name] = f"{ref_table}.{ref_col}"

    for line in table_struct.split('\n'):
        line = line.strip()
        if not line:
            continue
        if re.match(r'^(PRIMARY|FOREIGN|KEY|UNIQUE|INDEX|CONSTRAINT)', line, re.IGNORECASE):
            continue
        if line.endswith(','):
            line = line[:-1].strip()

        col_name_match = re.match(r'`([^`]+)`', line)
        if not col_name_match:
            col_name_match = re.match(r'(\w+)\s+', line)
            if not col_name_match:
                continue
        column_name = col_name_match.group(1).strip('`')

        rest = line[col_name_match.end():].strip() if col_name_match.end() < len(line) else ''

        type_match = re.match(r'([a-zA-Z0-9_]+(?:\([^)]*\))?)', rest)
        column_type = type_match.group(1) if type_match else ''

        rest = rest[type_match.end():].strip() if type_match and type_match.end() < len(rest) else ''

        column_desc = ''
        comment_match = re.search(
            r"COMMENT\s*=?\s*['\"]([^'\"]+)['\"]", rest, re.IGNORECASE)
        if comment_match:
            column_desc = comment_match.group(1)

        is_nullable = True
        if re.search(r'\bNOT\s+NULL\b', rest, re.IGNORECASE):
            is_nullable = False

        default_value = None
        default_match = re.search(
            r"DEFAULT\s+(['\"]?)([^'\"\s,]+)\1", rest, re.IGNORECASE)
        if default_match:
            default_value = default_match.group(2)
        elif re.search(r'\bDEFAULT\s+NULL\b', rest, re.IGNORECASE):
            default_value = 'NULL'

        column_key = 'PRI' if column_name in primary_keys else ''

        results.append({
            'user_id': user_id,
            'schema_name': schema_name,
            'table_name': table_name,
            'table_description': table_comment,
            'column_name': column_name,
            'column_type': column_type,
            'column_description': column_desc,
            'column_key': column_key,
            'foreign_key': fk_map.get(column_name, ''),
            'is_nullable': is_nullable,
            'default_value': default_value,
            'sample_values': None
        })

    return results


def parse_ddl_postgresql(ddl: str, schema_name: str, user_id: int) -> List[dict]:
    """解析 PostgreSQL DDL"""
    results = []
    
    create_table_pattern = r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?["\']?([^"\s(]+)["\']?\s*\('
    create_matches = list(re.finditer(create_table_pattern, ddl, re.IGNORECASE))

    if not create_matches:
        return results

    table_names = []
    for m in create_matches:
        table_name = m.group(1).strip('"\'')
        if table_name in table_names:
            raise DDLParseError(f"表名重复：{table_name}")
        table_names.append(table_name)

    for i, match in enumerate(create_matches):
        start_pos = match.start()
        end_pos = create_matches[i + 1].start() if i + 1 < len(create_matches) else len(ddl)
        table_ddl = ddl[start_pos:end_pos]
        table_results = parse_single_table_postgresql(table_ddl, schema_name, user_id)
        results.extend(table_results)

    return results


def parse_single_table_postgresql(table_ddl: str, schema_name: str, user_id: int) -> List[dict]:
    """解析单个 PostgreSQL CREATE TABLE 语句"""
    results = []

    table_name_match = re.search(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?["\']?([^"\s(]+)["\']?\s*\(', 
                                  table_ddl, re.IGNORECASE)
    if not table_name_match:
        return results

    table_name = table_name_match.group(1).strip('"\'')

    paren_start = table_name_match.end() - 1
    paren_count = 0
    paren_end = -1
    
    for i in range(paren_start, len(table_ddl)):
        if table_ddl[i] == '(':
            paren_count += 1
        elif table_ddl[i] == ')':
            paren_count -= 1
            if paren_count == 0:
                paren_end = i
                break

    if paren_end == -1:
        return results

    table_struct = table_ddl[paren_start + 1:paren_end]

    pk_match = re.search(r'PRIMARY KEY\s*\(([^)]+)\)', table_struct, re.IGNORECASE)
    primary_keys = []
    if pk_match:
        pk_str = pk_match.group(1)
        primary_keys = [pk.strip().strip('"\'') for pk in pk_str.split(',')]

    for line in table_struct.split('\n'):
        line = line.strip().rstrip(',')
        if not line:
            continue
        if re.match(r'^(PRIMARY|FOREIGN|UNIQUE|CHECK|EXCLUDE|CONSTRAINT)', line, re.IGNORECASE):
            continue

        col_name_match = re.match(r'"([^"]+)"', line)
        if not col_name_match:
            col_name_match = re.match(r'(\w+)\s+', line)
        if not col_name_match:
            continue
            
        column_name = col_name_match.group(1).strip('"\'')
        rest = line[col_name_match.end():].strip() if col_name_match.end() < len(line) else ''

        type_match = re.match(r'([a-zA-Z0-9_]+(?:\([^)]*\))?)', rest)
        column_type = type_match.group(1) if type_match else ''
        rest = rest[type_match.end():].strip() if type_match and type_match.end() < len(rest) else ''

        is_nullable = True
        if re.search(r'\bNOT\s+NULL\b', rest, re.IGNORECASE):
            is_nullable = False

        default_value = None
        default_match = re.search(r"DEFAULT\s+([^,\s]+(?:\([^)]*\))?)", rest, re.IGNORECASE)
        if default_match:
            default_value = default_match.group(1)

        column_key = 'PRI' if column_name in primary_keys else ''

        results.append({
            'user_id': user_id,
            'schema_name': schema_name,
            'table_name': table_name,
            'table_description': '',
            'column_name': column_name,
            'column_type': column_type,
            'column_description': '',
            'column_key': column_key,
            'is_nullable': is_nullable,
            'default_value': default_value,
            'sample_values': None
        })

    comment_pattern = r"COMMENT\s+ON\s+(?:TABLE|COLUMN)\s+[^.]+\.?[^.]*\s+IS\s+'([^']+)'"
    for match in re.finditer(comment_pattern, table_ddl, re.IGNORECASE):
        pass

    return results


def parse_ddl_oracle(ddl: str, schema_name: str, user_id: int) -> List[dict]:
    """解析 Oracle DDL"""
    results = []
    
    create_table_pattern = r'CREATE\s+TABLE\s+["\']?([^"\s(]+)["\']?\s*\('
    create_matches = list(re.finditer(create_table_pattern, ddl, re.IGNORECASE))

    if not create_matches:
        return results

    table_names = []
    for m in create_matches:
        table_name = m.group(1).strip('"\'').upper()
        if table_name in table_names:
            raise DDLParseError(f"表名重复：{table_name}")
        table_names.append(table_name)

    for i, match in enumerate(create_matches):
        start_pos = match.start()
        end_pos = create_matches[i + 1].start() if i + 1 < len(create_matches) else len(ddl)
        table_ddl = ddl[start_pos:end_pos]
        table_results = parse_single_table_oracle(table_ddl, schema_name, user_id)
        results.extend(table_results)

    return results


def parse_single_table_oracle(table_ddl: str, schema_name: str, user_id: int) -> List[dict]:
    """解析单个 Oracle CREATE TABLE 语句"""
    results = []

    table_name_match = re.search(r'CREATE\s+TABLE\s+["\']?([^"\s(]+)["\']?\s*\(', 
                                  table_ddl, re.IGNORECASE)
    if not table_name_match:
        return results

    table_name = table_name_match.group(1).strip('"\'').upper()

    paren_start = table_name_match.end() - 1
    paren_count = 0
    paren_end = -1
    
    for i in range(paren_start, len(table_ddl)):
        if table_ddl[i] == '(':
            paren_count += 1
        elif table_ddl[i] == ')':
            paren_count -= 1
            if paren_count == 0:
                paren_end = i
                break

    if paren_end == -1:
        return results

    table_struct = table_ddl[paren_start + 1:paren_end]

    pk_match = re.search(r'PRIMARY KEY\s*\(([^)]+)\)', table_struct, re.IGNORECASE)
    primary_keys = []
    if pk_match:
        pk_str = pk_match.group(1)
        primary_keys = [pk.strip().strip('"\'').upper() for pk in pk_str.split(',')]

    for line in table_struct.split('\n'):
        line = line.strip().rstrip(',')
        if not line:
            continue
        if re.match(r'^(PRIMARY|FOREIGN|UNIQUE|CHECK|CONSTRAINT)', line, re.IGNORECASE):
            continue

        col_name_match = re.match(r'"([^"]+)"', line)
        if not col_name_match:
            col_name_match = re.match(r'(\w+)\s+', line)
        if not col_name_match:
            continue
            
        column_name = col_name_match.group(1).strip('"\'').upper()
        rest = line[col_name_match.end():].strip() if col_name_match.end() < len(line) else ''

        type_match = re.match(r'(NUMBER(?:\([^)]*\))?|VARCHAR2(?:\([^)]*\))?|CHAR(?:\([^)]*\))?|DATE|CLOB|BLOB|TIMESTAMP(?:\([^)]*\))?(?:\s+WITH\s+LOCAL\s+TIME\s+ZONE)?)', 
                              rest, re.IGNORECASE)
        column_type = type_match.group(1).upper() if type_match else ''
        rest = rest[type_match.end():].strip() if type_match and type_match.end() < len(rest) else ''

        is_nullable = True
        if re.search(r'\bNOT\s+NULL\b', rest, re.IGNORECASE):
            is_nullable = False

        default_value = None
        default_match = re.search(r"DEFAULT\s+([^,\s]+(?:\([^)]*\))?)", rest, re.IGNORECASE)
        if default_match:
            default_value = default_match.group(1)

        column_key = 'PRI' if column_name in primary_keys else ''

        results.append({
            'user_id': user_id,
            'schema_name': schema_name,
            'table_name': table_name,
            'table_description': '',
            'column_name': column_name,
            'column_type': column_type,
            'column_description': '',
            'column_key': column_key,
            'is_nullable': is_nullable,
            'default_value': default_value,
            'sample_values': None
        })

    return results


def parse_ddl_sqlserver(ddl: str, schema_name: str, user_id: int) -> List[dict]:
    """解析 SQL Server DDL"""
    results = []
    
    create_table_pattern = r'CREATE\s+TABLE\s+(?:\[([^\]]+)\]\.)?\[([^\]]+)\]\s*\('
    create_matches = list(re.finditer(create_table_pattern, ddl, re.IGNORECASE))

    if not create_matches:
        create_table_pattern = r'CREATE\s+TABLE\s+["\']?([^"\s.]+)["\']?\s*\('
        create_matches = list(re.finditer(create_table_pattern, ddl, re.IGNORECASE))

    if not create_matches:
        return results

    table_names = []
    for m in create_matches:
        if len(m.groups()) > 1 and m.group(2):
            table_name = m.group(2)
        else:
            table_name = m.group(1)
        table_name = table_name.strip('"\'[]')
        if table_name in table_names:
            raise DDLParseError(f"表名重复：{table_name}")
        table_names.append(table_name)

    for i, match in enumerate(create_matches):
        start_pos = match.start()
        end_pos = create_matches[i + 1].start() if i + 1 < len(create_matches) else len(ddl)
        table_ddl = ddl[start_pos:end_pos]
        table_results = parse_single_table_sqlserver(table_ddl, schema_name, user_id)
        results.extend(table_results)

    return results


def parse_single_table_sqlserver(table_ddl: str, schema_name: str, user_id: int) -> List[dict]:
    """解析单个 SQL Server CREATE TABLE 语句"""
    results = []

    table_name_match = re.search(r'CREATE\s+TABLE\s+(?:\[([^\]]+)\]\.)?\[([^\]]+)\]\s*\(', 
                                  table_ddl, re.IGNORECASE)
    if not table_name_match:
        table_name_match = re.search(r'CREATE\s+TABLE\s+["\']?([^"\s(]+)["\']?\s*\(', 
                                      table_ddl, re.IGNORECASE)
        if table_name_match:
            table_name = table_name_match.group(1).strip('"\'[]')
        else:
            return results
    else:
        table_name = table_name_match.group(2) if table_name_match.group(2) else table_name_match.group(1)

    paren_start = table_name_match.end() - 1
    paren_count = 0
    paren_end = -1
    
    for i in range(paren_start, len(table_ddl)):
        if table_ddl[i] == '(':
            paren_count += 1
        elif table_ddl[i] == ')':
            paren_count -= 1
            if paren_count == 0:
                paren_end = i
                break

    if paren_end == -1:
        return results

    table_struct = table_ddl[paren_start + 1:paren_end]

    pk_match = re.search(r'PRIMARY KEY\s*\(([^)]+)\)', table_struct, re.IGNORECASE)
    primary_keys = []
    if pk_match:
        pk_str = pk_match.group(1)
        primary_keys = [pk.strip().strip('[]') for pk in pk_str.split(',')]

    for line in table_struct.split('\n'):
        line = line.strip().rstrip(',')
        if not line:
            continue
        if re.match(r'^(PRIMARY|FOREIGN|UNIQUE|CHECK|CONSTRAINT)', line, re.IGNORECASE):
            continue

        col_name_match = re.match(r'\[([^\]]+)\]', line)
        if not col_name_match:
            col_name_match = re.match(r'(\w+)\s+', line)
        if not col_name_match:
            continue
            
        column_name = col_name_match.group(1).strip('[]')
        rest = line[col_name_match.end():].strip() if col_name_match.end() < len(line) else ''

        type_match = re.match(r'([a-zA-Z0-9_]+(?:\([^)]*\))?)', rest)
        column_type = type_match.group(1) if type_match else ''
        rest = rest[type_match.end():].strip() if type_match and type_match.end() < len(rest) else ''

        is_nullable = True
        if re.search(r'\bNOT\s+NULL\b', rest, re.IGNORECASE):
            is_nullable = False

        default_value = None
        default_match = re.search(r"DEFAULT\s+([^,\s]+(?:\([^)]*\))?)", rest, re.IGNORECASE)
        if default_match:
            default_value = default_match.group(1)

        identity_match = re.search(r'IDENTITY\s*\(([^)]+)\)', rest, re.IGNORECASE)
        if identity_match:
            column_key = 'PRI'
        else:
            column_key = 'PRI' if column_name in primary_keys else ''

        results.append({
            'user_id': user_id,
            'schema_name': schema_name,
            'table_name': table_name,
            'table_description': '',
            'column_name': column_name,
            'column_type': column_type,
            'column_description': '',
            'column_key': column_key,
            'is_nullable': is_nullable,
            'default_value': default_value,
            'sample_values': None
        })

    return results


def parse_ddl_data_warehouse(ddl: str, schema_name: str, user_id: int, db_type: str) -> List[dict]:
    """解析数据仓库 DDL（Hive/Doris/ClickHouse）"""
    results = []
    
    if db_type == 'hive':
        create_table_pattern = r'CREATE\s+(?:EXTERNAL\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`"\']?([^`\s(]+)[`"\']?\s*\('
    elif db_type == 'doris':
        create_table_pattern = r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`"\']?([^`\s(]+)[`"\']?\s*\('
    else:
        create_table_pattern = r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`"\']?([^`\s(]+)[`"\']?\s*\('

    create_matches = list(re.finditer(create_table_pattern, ddl, re.IGNORECASE))

    if not create_matches:
        return results

    table_names = []
    for m in create_matches:
        table_name = m.group(1).strip('`"\'')
        if '.' in table_name:
            table_name = table_name.split('.')[-1]
        if table_name in table_names:
            raise DDLParseError(f"表名重复：{table_name}")
        table_names.append(table_name)

    for i, match in enumerate(create_matches):
        start_pos = match.start()
        end_pos = create_matches[i + 1].start() if i + 1 < len(create_matches) else len(ddl)
        table_ddl = ddl[start_pos:end_pos]
        table_results = parse_single_table_data_warehouse(table_ddl, schema_name, user_id, db_type)
        results.extend(table_results)

    return results


def parse_single_table_data_warehouse(table_ddl: str, schema_name: str, user_id: int, db_type: str) -> List[dict]:
    """解析单个数据仓库 CREATE TABLE 语句"""
    results = []

    if db_type == 'hive':
        table_name_match = re.search(r'CREATE\s+(?:EXTERNAL\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`"\']?([^`\s(]+)[`"\']?\s*\(', 
                                      table_ddl, re.IGNORECASE)
    else:
        table_name_match = re.search(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`"\']?([^`\s(]+)[`"\']?\s*\(', 
                                      table_ddl, re.IGNORECASE)
    
    if not table_name_match:
        return results

    table_name = table_name_match.group(1).strip('`"\'')
    if '.' in table_name:
        table_name = table_name.split('.')[-1]

    paren_start = table_name_match.end() - 1
    paren_count = 0
    paren_end = -1
    
    for i in range(paren_start, len(table_ddl)):
        if table_ddl[i] == '(':
            paren_count += 1
        elif table_ddl[i] == ')':
            paren_count -= 1
            if paren_count == 0:
                paren_end = i
                break

    if paren_end == -1:
        return results

    table_struct = table_ddl[paren_start + 1:paren_end]

    table_comment = ''
    comment_match = re.search(r"COMMENT\s+['\"]([^'\"]+)['\"]", table_ddl[paren_end:], re.IGNORECASE)
    if comment_match:
        table_comment = comment_match.group(1)

    pk_match = re.search(r'PRIMARY KEY\s*\(([^)]+)\)', table_struct, re.IGNORECASE)
    primary_keys = []
    if pk_match:
        pk_str = pk_match.group(1)
        primary_keys = [pk.strip().strip('`"\'') for pk in pk_str.split(',')]

    for line in table_struct.split('\n'):
        line = line.strip().rstrip(',')
        if not line:
            continue
        if re.match(r'^(PRIMARY|FOREIGN|UNIQUE|INDEX|KEY)', line, re.IGNORECASE):
            continue

        col_name_match = re.match(r'[`"\']?([^`"\'\s]+)[`"\']?\s+', line)
        if not col_name_match:
            continue
            
        column_name = col_name_match.group(1).strip('`"\'')
        rest = line[col_name_match.end():].strip()

        type_match = re.match(r'([a-zA-Z0-9_]+(?:\([^)]*\))?)', rest)
        column_type = type_match.group(1) if type_match else ''
        rest = rest[type_match.end():].strip() if type_match and type_match.end() < len(rest) else ''

        column_desc = ''
        comment_match = re.search(r"COMMENT\s+['\"]([^'\"]+)['\"]", rest, re.IGNORECASE)
        if comment_match:
            column_desc = comment_match.group(1)

        is_nullable = True
        if re.search(r'\bNOT\s+NULL\b', rest, re.IGNORECASE):
            is_nullable = False

        column_key = 'PRI' if column_name in primary_keys else ''

        results.append({
            'user_id': user_id,
            'schema_name': schema_name,
            'table_name': table_name,
            'table_description': table_comment,
            'column_name': column_name,
            'column_type': column_type,
            'column_description': column_desc,
            'column_key': column_key,
            'is_nullable': is_nullable,
            'default_value': None,
            'sample_values': None
        })

    return results


def _save_parsed_results(parsed_results: List[dict], user_id: int, db: Session) -> tuple:
    """保存解析结果到数据库（批量优化，7个字段相同才算重复）"""
    if not parsed_results:
        return 0, 0, []

    new_count = 0
    duplicate_count = 0
    schema_names = set()

    existing_keys = set()
    schema_names_all = set(r['schema_name'] for r in parsed_results)
    for schema_name in schema_names_all:
        existing = db.query(
            Schema.table_name,
            Schema.column_name,
            Schema.column_type,
            Schema.column_key,
            Schema.foreign_key
        ).filter(
            Schema.user_id == user_id,
            Schema.schema_name == schema_name
        ).all()
        for record in existing:
            key = (schema_name, record.table_name, record.column_name, 
                   record.column_type, record.column_key, record.foreign_key)
            existing_keys.add(key)

    to_add = []
    for result in parsed_results:
        key = (result['schema_name'], result['table_name'], result['column_name'],
               result.get('column_type'), result.get('column_key'), result.get('foreign_key'))
        if key in existing_keys:
            duplicate_count += 1
        else:
            to_add.append(Schema(**result))
            new_count += 1
            schema_names.add(result['schema_name'])

    if to_add:
        db.bulk_save_objects(to_add)
        db.commit()

    return new_count, duplicate_count, list(schema_names)


@router.post("/parse", response_model=SchemaListResponse)
def parse_ddl_text(
        request: DDLParseRequest,
        user=Depends(get_current_user)
):
    """解析 DDL 文本（仅管理员）"""
    _admin_only(user)
    log_audit(user, "parse_schema", f"schema_name={request.schema_name}")
    try:
        user_id = user['user_id']
        db = SchemaSessionLocal()

        try:
            parsed_results = parse_ddl(
                request.ddl_text, user_id, request.schema_name, request.db_type)

            if not parsed_results:
                raise HTTPException(status_code=400, detail="无法解析 DDL，请检查格式")

            new_count, duplicate_count, schema_names = _save_parsed_results(parsed_results, user_id, db)

            message = f"成功插入 {new_count} 条记录"
            if duplicate_count > 0:
                message += f"，跳过 {duplicate_count} 条重复记录"
            if schema_names:
                message += f"，涉及 Schema: {', '.join(schema_names)}"

            items = db.query(Schema).filter(
                Schema.schema_name.in_(schema_names) if schema_names else Schema.schema_name == request.schema_name
            ).all()

            index_messages = []
            for schema_name in schema_names:
                schema_field_count = db.query(Schema).filter(
                        Schema.schema_name == schema_name
                ).count()
                index_message = _auto_build_vector_index(schema_name, schema_field_count)
                if index_message:
                    index_messages.append(index_message)
            
            if index_messages:
                message += "。" + "；".join(index_messages)

            return SchemaListResponse(
                items=[SchemaItem.model_validate(item) for item in items],
                total=len(items),
                message=message
            )
        finally:
            db.close()

    except DDLParseError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"DDL 解析失败：{e}")
        raise HTTPException(status_code=500, detail=f"解析失败：{str(e)}")


@router.post("/parse-json", response_model=SchemaListResponse)
def parse_json_text(
        request: JSONParseRequest,
        user=Depends(get_current_user)
):
    """解析 JSON 格式的 Schema（仅管理员）"""
    _admin_only(user)
    try:
        user_id = user['user_id']
        db = SchemaSessionLocal()

        try:
            parsed_results = parse_json_schema(request.json_text, user_id, request.schema_name)

            if not parsed_results:
                raise HTTPException(status_code=400, detail="无法解析 JSON，请检查格式")

            new_count, duplicate_count, schema_names = _save_parsed_results(parsed_results, user_id, db)

            fk_count = sum(1 for r in parsed_results if r.get('foreign_key'))

            message = f"成功插入 {new_count} 条记录"
            if duplicate_count > 0:
                message += f"，跳过 {duplicate_count} 条重复记录"
            if schema_names:
                message += f"，涉及 Schema: {', '.join(schema_names)}"
            if fk_count > 0:
                message += f"，外键 {fk_count} 条"

            items = db.query(Schema).filter(
                Schema.schema_name.in_(schema_names) if schema_names else Schema.schema_name == request.schema_name
            ).all()

            index_messages = []
            for schema_name in schema_names:
                schema_field_count = db.query(Schema).filter(
                        Schema.schema_name == schema_name
                ).count()
                index_message = _auto_build_vector_index(schema_name, schema_field_count)
                if index_message:
                    index_messages.append(index_message)
            
            if index_messages:
                message += "。" + "；".join(index_messages)

            return SchemaListResponse(
                items=[SchemaItem.model_validate(item) for item in items],
                total=len(items),
                message=message
            )
        finally:
            db.close()

    except JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"JSON 解析错误: {str(e)}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"JSON 解析失败：{e}")
        raise HTTPException(status_code=500, detail=f"解析失败：{str(e)}")


@router.post("/upload", response_model=SchemaListResponse)
async def upload_ddl_file(
        file: UploadFile = File(...),
        schema_name: str = Form("default"),
        db_type: str = Form("auto"),
        user=Depends(get_current_user)
):
    """上传 DDL 或 JSON 文件并解析（仅管理员）"""
    _admin_only(user)
    try:
        user_id = user['user_id']

        content = await file.read()
        file_content = content.decode('utf-8')
        
        filename = file.filename.lower() if file.filename else ""
        
        if filename.endswith('.json'):
            parsed_results = parse_json_schema(file_content, user_id, schema_name)
        else:
            parsed_results = parse_ddl(file_content, user_id, schema_name, db_type)

        if not parsed_results:
            raise HTTPException(status_code=400, detail="无法解析文件，请检查格式")

        db = SchemaSessionLocal()

        try:
            new_count, duplicate_count, schema_names = _save_parsed_results(parsed_results, user_id, db)

            fk_count = sum(1 for r in parsed_results if r.get('foreign_key'))

            message = f"成功插入 {new_count} 条记录"
            if duplicate_count > 0:
                message += f"，跳过 {duplicate_count} 条重复记录"
            if schema_names:
                message += f"，涉及 Schema: {', '.join(schema_names)}"
            if fk_count > 0:
                message += f"，外键 {fk_count} 条"

            items = db.query(Schema).filter(
                Schema.schema_name.in_(schema_names) if schema_names else Schema.schema_name == schema_name
            ).all()

            index_messages = []
            for sn in schema_names:
                schema_field_count = db.query(Schema).filter(
                        Schema.schema_name == sn
                ).count()
                index_message = _auto_build_vector_index(sn, schema_field_count)
                if index_message:
                    index_messages.append(index_message)
            
            if index_messages:
                message += "。" + "；".join(index_messages)

            return SchemaListResponse(
                items=[SchemaItem.model_validate(item) for item in items],
                total=len(items),
                message=message
            )
        finally:
            db.close()

    except DDLParseError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"文件上传解析失败：{e}")
        raise HTTPException(status_code=500, detail=f"解析失败：{str(e)}")


@router.get("/list", response_model=SchemaListResponse)
def get_schema_list(
        schema_name: Optional[str] = None,
        table_name: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        user=Depends(get_current_user)
):
    """获取用户的 Schema 解析列表，支持按库名、表名、字段名、描述模糊搜索"""
    try:
        user_id = user['user_id']
        db = SchemaSessionLocal()

        try:
            query = db.query(Schema).filter(Schema.id > 0)
            query = _filter_by_schema_names(query, user, Schema)

            if schema_name:
                query = query.filter(Schema.schema_name == schema_name)
            if table_name:
                query = query.filter(Schema.table_name == table_name)
            if search:
                search_pattern = f"%{search}%"
                query = query.filter(
                    or_(
                        Schema.schema_name.like(search_pattern),
                        Schema.table_name.like(search_pattern),
                        Schema.column_name.like(search_pattern),
                        Schema.column_description.like(search_pattern),
                        Schema.table_description.like(search_pattern),
                    )
                )

            total = query.count()
            items = query.order_by(Schema.created_at.desc()).limit(limit).offset(offset).all()

            return SchemaListResponse(
                items=[SchemaItem.model_validate(item) for item in items],
                total=total
            )
        finally:
            db.close()

    except Exception as e:
        logger.error(f"获取 Schema 列表失败：{e}")
        raise HTTPException(status_code=500, detail=f"获取失败：{str(e)}")


class BuildIndexRequest(BaseModel):
    """构建索引请求"""
    schema_name: Optional[str] = None
    rebuild: bool = False
    llm_config_id: Optional[int] = None


class IndexInfoResponse(BaseModel):
    """索引信息响应"""
    vector_dir: str
    field_count: int
    should_build_index: bool
    threshold: int
    indexes: dict
    status: Optional[str] = None


@router.post("/build-vector-index")
def build_vector_index(
    request: BuildIndexRequest,
    user=Depends(get_current_user)
):
    """构建向量索引（仅管理员）"""
    _admin_only(user)
    _check_embedding_ready()
    try:
        from core.SQLPipeline import build_vector_index as do_build

        result = do_build(request.schema_name)
        message = "向量索引重建成功" if request.rebuild else "向量索引构建成功"

        return {
            "success": True,
            "message": message,
            "result": result
        }

    except Exception as e:
        logger.error(f"构建向量索引失败：{e}")
        raise HTTPException(status_code=500, detail=f"构建失败：{str(e)}")


@router.get("/vector-index-info", response_model=IndexInfoResponse)
def get_vector_index_info(
    schema_name: Optional[str] = None,
    user=Depends(get_current_user)
):
    """获取向量索引信息"""
    _check_embedding_ready()
    try:
        from core.SQLPipeline import get_vector_index_info as do_get_info

        info = do_get_info(schema_name)
        fields = info.get('fields', {})
        info['field_count'] = fields.get('count', 0)
        info['indexes'] = fields
        info['threshold'] = fields.get('is_built', False) and 50 or 0
        info['should_build_index'] = fields.get('count', 0) >= 50

        return IndexInfoResponse(**info)

    except Exception as e:
        logger.error(f"获取向量索引信息失败：{e}")
        raise HTTPException(status_code=500, detail=f"获取失败：{str(e)}")


@router.get("/vector-index-list")
def list_vector_indexes(user=Depends(get_current_user)):
    """列出所有向量索引元数据（仅管理员）"""
    _admin_only(user)
    try:
        from models import AppSessionLocal
        from models.vector_index import VectorIndexMeta

        db = AppSessionLocal()
        try:
            rows = db.query(VectorIndexMeta).order_by(
                VectorIndexMeta.schema_name.asc()
            ).all()
            return [{
                'id': r.id,
                'schema_name': r.schema_name,
                'status': r.status,
                'field_count': r.field_count,
                'table_count': r.table_count,
                'dimension': r.dimension,
                'file_path': r.file_path,
                'error_message': r.error_message,
                'built_at': r.built_at.isoformat() if r.built_at else None,
                'created_at': r.created_at.isoformat() if r.created_at else None
            } for r in rows]
        finally:
            db.close()
    except Exception as e:
        logger.error(f"获取向量索引列表失败：{e}")
        raise HTTPException(status_code=500, detail=f"获取失败：{str(e)}")


@router.put("/{schema_id}/sample-values")
def update_sample_values(
        schema_id: int,
        request: UpdateSampleValuesRequest,
        user=Depends(get_current_user)
):
    """更新字段的示例值（仅管理员）"""
    _admin_only(user)
    try:
        user_id = user['user_id']
        db = SchemaSessionLocal()

        try:
            item = db.query(Schema).filter(
                Schema.id == schema_id,
                Schema.user_id == user_id
            ).first()

            if not item:
                raise HTTPException(status_code=404, detail="Schema 项不存在")

            item.sample_values = request.sample_values
            db.commit()

            return {"success": True, "message": "更新成功"}
        finally:
            db.close()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新示例值失败：{e}")
        raise HTTPException(status_code=500, detail=f"更新失败：{str(e)}")


@router.get("/stats")
def get_schema_stats(
        user=Depends(get_current_user)
):
    """获取用户 Schema 统计数据"""
    try:
        user_id = user['user_id']
        db = SchemaSessionLocal()

        try:
            query = _filter_by_schema_names(db.query(Schema), user, Schema)
            column_count = query.count()

            schema_count = _filter_by_schema_names(
                db.query(Schema.schema_name), user, Schema
            ).distinct().count()

            table_count = _filter_by_schema_names(
                db.query(Schema.table_name), user, Schema
            ).distinct().count()

            return {
                "schema_count": schema_count,
                "table_count": table_count,
                "column_count": column_count
            }
        finally:
            db.close()

    except Exception as e:
        logger.error(f"获取 Schema 统计失败：{e}")
        raise HTTPException(status_code=500, detail=f"统计失败：{str(e)}")


@router.get("/check", response_model=SchemaCheckResponse)
def check_schema(
        user=Depends(get_current_user)
):
    """检查用户是否有 Schema 数据"""
    try:
        user_id = user['user_id']
        db = SchemaSessionLocal()

        try:
            base = _filter_by_schema_names(db.query(Schema), user, Schema)
            total = base.count()
            tables = base.with_entities(Schema.schema_name, Schema.table_name).distinct().all()

            return SchemaCheckResponse(
                has_schema=total > 0,
                schema_count=len(set(t.schema_name for t in tables)),
                table_count=len(tables)
            )
        finally:
            db.close()

    except Exception as e:
        logger.error(f"检查 Schema 失败：{e}")
        raise HTTPException(status_code=500, detail=f"检查失败：{str(e)}")


@router.get("/export")
def export_schema(
        schema_name: Optional[str] = None,
        table_name: Optional[str] = None,
        user=Depends(get_current_user)
):
    """导出 Schema 为 CSV"""
    try:
        user_id = user['user_id']
        db = SchemaSessionLocal()

        try:
            query = db.query(Schema).filter(Schema.id > 0)
            query = _filter_by_schema_names(query, user, Schema)

            if schema_name:
                query = query.filter(Schema.schema_name == schema_name)
            if table_name:
                query = query.filter(Schema.table_name == table_name)

            items = query.all()

            output = io.StringIO()
            writer = csv.writer(output)

            writer.writerow([
                'schema_name', 'table_name', 'table_description',
                'column_name', 'column_type', 'column_description',
                'column_key', 'is_nullable', 'default_value', 'sample_values'
            ])

            for item in items:
                writer.writerow([
                    item.schema_name,
                    item.table_name,
                    item.table_description or '',
                    item.column_name,
                    item.column_type or '',
                    item.column_description or '',
                    item.column_key or '',
                    'YES' if item.is_nullable else 'NO',
                    item.default_value or '',
                    item.sample_values or ''
                ])

            output.seek(0)

            return StreamingResponse(
                io.BytesIO(output.getvalue().encode('utf-8')),
                media_type='text/csv',
                headers={'Content-Disposition': f'attachment; filename="schema_{schema_name or "all"}.csv"'}
            )
        finally:
            db.close()

    except Exception as e:
        logger.error(f"导出 Schema 失败：{e}")
        raise HTTPException(status_code=500, detail=f"导出失败：{str(e)}")


@router.get("/schemas")
def get_schemas(
        user=Depends(get_current_user)
):
    """获取用户所有的 schema 名称列表"""
    try:
        user_id = user['user_id']
        db = SchemaSessionLocal()

        try:
            query = _filter_by_schema_names(db.query(Schema.schema_name), user, Schema)
            schemas = query.distinct().all()

            return {"schemas": [s[0] for s in schemas]}
        finally:
            db.close()

    except Exception as e:
        logger.error(f"获取 schema 列表失败：{e}")
        raise HTTPException(status_code=500, detail=f"获取失败：{str(e)}")


@router.get("/tables")
def get_tables(
        schema_name: Optional[str] = None,
        user=Depends(get_current_user)
):
    """获取指定 schema 下的表名列表"""
    try:
        user_id = user['user_id']
        db = SchemaSessionLocal()

        try:
            query = db.query(Schema.table_name, Schema.table_description)
            query = _filter_by_schema_names(query, user, Schema)

            if schema_name:
                query = query.filter(Schema.schema_name == schema_name)

            tables = query.distinct().all()

            return {
                "tables": [
                    {"name": t[0], "description": t[1] or ""} 
                    for t in tables
                ]
            }
        finally:
            db.close()

    except Exception as e:
        logger.error(f"获取表列表失败：{e}")
        raise HTTPException(status_code=500, detail=f"获取失败：{str(e)}")


@router.delete("/schema/{schema_name}")
def delete_schema(
        schema_name: str,
        user=Depends(get_current_user)
):
    """删除指定 schema 的所有数据（仅管理员）"""
    _admin_only(user)
    try:
        user_id = user['user_id']
        db = SchemaSessionLocal()

        try:
            count = db.query(Schema).filter(
                Schema.schema_name == schema_name
            ).delete()
            
            db.commit()

            return {"success": True, "message": f"已删除 schema '{schema_name}' 的 {count} 条记录"}
        finally:
            db.close()

    except Exception as e:
        logger.error(f"删除 schema 失败：{e}")
        raise HTTPException(status_code=500, detail=f"删除失败：{str(e)}")


@router.delete("/table")
def delete_table(
        schema_name: str,
        table_name: str,
        user=Depends(get_current_user)
):
    """删除指定表的所有字段（仅管理员）"""
    _admin_only(user)
    try:
        user_id = user['user_id']
        db = SchemaSessionLocal()

        try:
            count = db.query(Schema).filter(
                Schema.schema_name == schema_name,
                Schema.table_name == table_name
            ).delete()
            
            db.commit()

            return {"success": True, "message": f"已删除表 '{table_name}' 的 {count} 条记录"}
        finally:
            db.close()

    except Exception as e:
        logger.error(f"删除表失败：{e}")
        raise HTTPException(status_code=500, detail=f"删除失败：{str(e)}")


@router.delete("/{schema_id}")
def delete_schema_item(
        schema_id: int,
        user=Depends(get_current_user)
):
    """删除单个字段（仅管理员）"""
    _admin_only(user)
    try:
        user_id = user['user_id']
        db = SchemaSessionLocal()

        try:
            item = db.query(Schema).filter(
                Schema.id == schema_id,
                Schema.user_id == user_id
            ).first()

            if not item:
                raise HTTPException(status_code=404, detail="Schema 项不存在")

            db.delete(item)
            db.commit()

            return {"success": True, "message": "删除成功"}
        finally:
            db.close()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除 Schema 项失败：{e}")
        raise HTTPException(status_code=500, detail=f"删除失败：{str(e)}")


@router.get("/supported-db-types")
def get_supported_db_types():
    """获取支持的数据库类型列表"""
    return {
        "db_types": SUPPORTED_DB_TYPES,
        "descriptions": {
            "mysql": "MySQL / MariaDB",
            "mariadb": "MariaDB",
            "postgresql": "PostgreSQL",
            "postgres": "PostgreSQL",
            "oracle": "Oracle Database",
            "sqlserver": "Microsoft SQL Server",
            "sqlite": "SQLite",
            "hive": "Apache Hive",
            "doris": "Apache Doris",
            "clickhouse": "ClickHouse"
        }
    }
