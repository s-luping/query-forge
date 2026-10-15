# -*- coding: UTF-8 -*-
"""Diff 引擎 — 对比源库元数据 vs 本系统存储的三层模型

输出标准化变更记录列表，供 SyncEngine 应用和记录。
"""
import json
from dataclasses import dataclass
from typing import Dict, List

from models.schema import DbColumn, DbTable
from services.sync_connectors import ColumnMetadata, TableMetadata


@dataclass
class ChangeRecord:
    """一条变更记录"""
    change_type: str           # add / modify / remove
    object_type: str            # table / column
    object_name: str            # table_name 或 table.column
    old_value: str = ''         # JSON
    new_value: str = ''         # JSON
    is_high_risk: bool = False  # 删除/类型变更为高风险


def _col_to_dict(col) -> dict:
    """DbColumn → dict"""
    return {
        'name': col.name,
        'data_type': col.data_type or '',
        'description': col.description or '',
        'is_nullable': bool(col.is_nullable),
        'default_value': col.default_value or '',
        'column_key': col.column_key or '',
        'foreign_key': col.foreign_key or '',
    }


def _src_col_to_dict(col: ColumnMetadata) -> dict:
    """ColumnMetadata → dict"""
    return {
        'name': col.name,
        'data_type': col.data_type,
        'description': col.description,
        'is_nullable': col.is_nullable,
        'default_value': col.default_value,
        'column_key': col.column_key,
        'foreign_key': col.foreign_key,
    }


def _table_to_dict(table) -> dict:
    """DbTable → dict"""
    return {
        'name': table.name,
        'description': table.description or '',
    }


def diff_metadata(
    source_tables: List[TableMetadata],
    stored_tables: List[DbTable],
    stored_columns_by_table: Dict[int, List[DbColumn]],  # {table_id: [DbColumn]}
) -> List[ChangeRecord]:
    """对比源库元数据 vs 存储元数据，返回变更列表

    Args:
        source_tables: 连接器读取的源库表列表
        stored_tables: 本系统存储的 DbTable 列表
        stored_columns_by_table: {table_id: [DbColumn]}
    """
    changes: List[ChangeRecord] = []

    # 构建存储表名 → DbTable 映射
    stored_map: Dict[str, DbTable] = {t.name: t for t in stored_tables}

    # 构建存储表名 → {列名: DbColumn} 映射
    stored_col_map: Dict[str, Dict[str, DbColumn]] = {}
    for t in stored_tables:
        cols = stored_columns_by_table.get(t.id, [])
        stored_col_map[t.name] = {c.name: c for c in cols}

    # 1. 遍历源库表
    for src_table in source_tables:
        table_name = src_table.name

        if table_name not in stored_map:
            # 新增表 + 全部字段
            changes.append(ChangeRecord(
                change_type='add', object_type='table',
                object_name=table_name,
                new_value=json.dumps(_table_to_dict_from_src(src_table), ensure_ascii=False),
                is_high_risk=False,
            ))
            for col in src_table.columns:
                changes.append(ChangeRecord(
                    change_type='add', object_type='column',
                    object_name=f"{table_name}.{col.name}",
                    new_value=json.dumps(_src_col_to_dict(col), ensure_ascii=False),
                    is_high_risk=False,
                ))
            continue

        # 表已存在 — 检查表注释是否变更
        stored_table = stored_map[table_name]
        if (stored_table.description or '') != src_table.description:
            changes.append(ChangeRecord(
                change_type='modify', object_type='table',
                object_name=table_name,
                old_value=json.dumps({'description': stored_table.description or ''}, ensure_ascii=False),
                new_value=json.dumps({'description': src_table.description}, ensure_ascii=False),
                is_high_risk=False,
            ))

        # 检查字段级变更
        stored_cols = stored_col_map.get(table_name, {})
        src_col_names = set()

        for src_col in src_table.columns:
            src_col_names.add(src_col.name)

            if src_col.name not in stored_cols:
                # 新增字段
                changes.append(ChangeRecord(
                    change_type='add', object_type='column',
                    object_name=f"{table_name}.{src_col.name}",
                    new_value=json.dumps(_src_col_to_dict(src_col), ensure_ascii=False),
                    is_high_risk=False,
                ))
                continue

            # 对比已有字段
            stored_col = stored_cols[src_col.name]
            old_dict = _col_to_dict(stored_col)
            new_dict = _src_col_to_dict(src_col)

            # 检查是否真的有变更（忽略 description 变更 — 源库注释更新也应同步）
            significant_fields = ['data_type', 'is_nullable', 'default_value', 'column_key', 'foreign_key']
            has_change = False
            for f in significant_fields:
                if old_dict.get(f) != new_dict.get(f):
                    has_change = True
                    break
            # 注释变更也要同步
            if old_dict.get('description') != new_dict.get('description'):
                has_change = True

            if has_change:
                # 类型变更 = 高风险
                is_high_risk = old_dict.get('data_type', '') != new_dict.get('data_type', '')
                changes.append(ChangeRecord(
                    change_type='modify', object_type='column',
                    object_name=f"{table_name}.{src_col.name}",
                    old_value=json.dumps(old_dict, ensure_ascii=False),
                    new_value=json.dumps(new_dict, ensure_ascii=False),
                    is_high_risk=is_high_risk,
                ))

        # 检查源库已删除的字段
        for stored_col_name, stored_col in stored_cols.items():
            if stored_col_name not in src_col_names:
                changes.append(ChangeRecord(
                    change_type='remove', object_type='column',
                    object_name=f"{table_name}.{stored_col_name}",
                    old_value=json.dumps(_col_to_dict(stored_col), ensure_ascii=False),
                    is_high_risk=True,  # 删除字段 = 高风险
                ))

    # 2. 检查源库已删除的表
    src_table_names = {t.name for t in source_tables}
    for stored_name in stored_map:
        if stored_name not in src_table_names:
            changes.append(ChangeRecord(
                change_type='remove', object_type='table',
                object_name=stored_name,
                old_value=json.dumps(_table_to_dict(stored_map[stored_name]), ensure_ascii=False),
                is_high_risk=True,  # 删除表 = 高风险
            ))

    return changes


def _table_to_dict_from_src(table: TableMetadata) -> dict:
    """TableMetadata → dict"""
    return {'name': table.name, 'description': table.description}
