# -*- coding: UTF-8 -*-
"""
向量索引元数据与构建 — 从原 sql_pipeline.py 拆出

职责：
  - set_index_meta / get_index_meta：VectorIndexMeta 表读写（状态机 building/ready/stale/error）
  - build_vector_index：全量构建某个 schema 的字段向量索引
  - get_vector_index_info：查询索引状态（优先 DB 元数据，回退磁盘检查）
"""
from datetime import datetime
from typing import Optional, Dict
from app.timezone import now_beijing
from crud.base import session_scope


def set_index_meta(schema_name: str, status: str, field_count: int = 0,
                   table_count: int = 0, file_path: str = '', error_msg: str = ''):
    """写入向量索引元数据到数据库"""
    try:
        from models.vector_index import VectorIndexMeta

        with session_scope() as db:
            row = db.query(VectorIndexMeta).filter(
                VectorIndexMeta.schema_name == schema_name
            ).first()
            if row is not None:
                # 构建期间有新数据导入导致 stale，不覆盖为 ready
                current = str(row.status)
                if status == 'ready' and current == 'stale':
                    db.close()
                    return
                row.status = status  # type: ignore[assignment]
                if field_count:
                    row.field_count = field_count  # type: ignore[assignment]
                if table_count:
                    row.table_count = table_count  # type: ignore[assignment]
                if file_path:
                    row.file_path = file_path  # type: ignore[assignment]
                if error_msg:
                    row.error_message = error_msg  # type: ignore[assignment]
                if status == 'ready':
                    row.built_at = now_beijing()  # type: ignore[assignment]
            else:
                db.add(VectorIndexMeta(
                    schema_name=schema_name,
                    status=status,
                    field_count=field_count,
                    table_count=table_count,
                    file_path=file_path,
                    error_message=error_msg,
                    built_at=now_beijing() if status == 'ready' else None
                ))
            db.commit()
    except Exception:
        pass  # 元数据写入失败不影响索引构建


def get_index_meta(schema_name: str) -> Optional[dict]:
    """从数据库读取向量索引元数据"""
    try:
        from models.vector_index import VectorIndexMeta

        with session_scope() as db:
            row = db.query(VectorIndexMeta).filter(
                VectorIndexMeta.schema_name == schema_name
            ).first()
            if row is not None:
                built = str(row.built_at) if row.built_at is not None else None  # type: ignore[union-attr]
                return {
                    'schema_name': str(row.schema_name),
                    'status': str(row.status),
                    'field_count': int(row.field_count),  # type: ignore[arg-type]
                    'table_count': int(row.table_count),  # type: ignore[arg-type]
                    'dimension': int(row.dimension),  # type: ignore[arg-type]
                    'file_path': str(row.file_path),
                    'error_message': str(row.error_message),
                    'built_at': built
                }
    except Exception:
        pass
    return None


def build_vector_index(schema_name: Optional[str] = None) -> Dict:
    """构建向量索引（全库统一构建，不再按库区分）

    对话为全库模式（schema_name=None），召回使用无前缀 fields 全库索引。
    schema_name 参数仅用于记录来源（兼容调用方），构建内容始终为全库字段。
    """
    from core.ret_vector_store import SchemaVectorStore
    from services import schema_service

    # 全库统一构建：target 固定为全库索引（None），元数据 key 用 'default'
    target_schema = 'default'
    try:
        store = SchemaVectorStore()
        rows = schema_service.iter_field_rows(schema_name=None)
        if not rows:
            return {'success': False, 'message': '没有数据'}

        schema_list = [{
            'schema_name': r.schema_name or '',
            'table_name': r.table_name,
            'table_description': r.table_description or '',
            'column_name': r.column_name,
            'column_description': r.column_description,
            'column_type': r.column_type,
            'column_key': r.column_key,
            'foreign_key': r.foreign_key,
            'sample_values': r.sample_values,
        } for r in rows]

        # 写入构建中状态
        set_index_meta(target_schema, 'building')

        result = store.build_from_schemas(schema_list, None)

        if result.get('success'):
            table_count = len(set(s.get('table_name', '') for s in schema_list))
            file_path = store.field_index._last_save_path or ''
            set_index_meta(
                target_schema, 'ready',
                field_count=result.get('field_count', len(schema_list)),
                table_count=table_count,
                file_path=file_path
            )

        return result
    except Exception as e:
        set_index_meta(target_schema, 'error', error_msg=str(e))
        raise


def get_vector_index_info(schema_name: Optional[str] = None) -> Dict:
    """获取向量索引信息（优先读数据库元数据）"""
    from core.ret_vector_store import SchemaVectorStore

    target = schema_name or 'default'
    meta = get_index_meta(target)

    if meta and meta['status'] == 'ready':
        return {
            'vector_dir': meta.get('file_path', ''),
            'field_count': meta.get('field_count', 0),
            'should_build_index': meta.get('field_count', 0) >= 50,
            'threshold': 50,
            'indexes': {
                'count': meta.get('field_count', 0),
                'is_built': True,
                'filepath': meta.get('file_path', ''),
                'built_at': meta.get('built_at'),
                'table_count': meta.get('table_count', 0)
            },
            'status': meta['status']
        }

    # 元数据不可用，回退到从磁盘加载检查
    store = SchemaVectorStore()
    store.load(schema_name)
    return store.get_info(schema_name)
