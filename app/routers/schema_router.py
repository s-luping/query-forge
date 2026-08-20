# -*- coding: UTF-8 -*-
"""Schema 管理路由（薄层）— 解析逻辑在 services/schema/parsers，读写逻辑在 services/schema/service

URL 与响应结构与旧版完全一致，前端无感切换。
"""
import csv
import io
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.auth import AdminUser, CurrentUser
from app.logger import logger, log_audit
from app.permissions import get_visible_schema_ids, get_table_grants_by_schema
from services.vector_service import auto_build_vector_index, mark_index_stale  # 从服务层导入（消除路由层职责过重）
from models.schema import DbSchema, DbColumn
from models.datasource import DataSource
from services.schema_parsers import (
    parse_json_schema, parse_schema_csv, DDLParseError, SUPPORTED_DB_TYPES,
)
from services import schema_service
from crud.base import session_scope

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════
# Pydantic 模型（响应契约保持不变）
# ═══════════════════════════════════════════════════════════════════

class JSONParseRequest(BaseModel):
    """JSON 解析请求（数据库类型、数据源必填）"""
    json_text: str
    schema_name: str = "default"
    db_type: str
    datasource_id: int


class CSVParseRequest(BaseModel):
    """规范 CSV 解析请求（数据库类型、数据源必填）"""
    csv_text: str
    schema_name: str = "default"
    db_type: str
    datasource_id: int


class SchemaItem(BaseModel):
    """Schema 解析项（平铺视图）"""
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


class BuildIndexRequest(BaseModel):
    """构建索引请求"""
    schema_name: Optional[str] = None
    rebuild: bool = False
    llm_config_id: Optional[int] = None


def _validate_db_type(db_type: str):
    """数据库类型必填且须为支持的类型（存储层保证 db_type 非空）"""
    if not db_type or db_type.strip() not in SUPPORTED_DB_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"数据库类型为必填项，且需为支持的类型: {', '.join(SUPPORTED_DB_TYPES)}")


class IndexInfoResponse(BaseModel):
    """索引信息响应"""
    vector_dir: str
    field_count: int
    should_build_index: bool
    threshold: int
    indexes: dict
    status: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════
# 内部辅助
# ═══════════════════════════════════════════════════════════════════

def _check_embedding_ready():
    """检查嵌入模型是否就绪，未就绪则抛出 400 错误"""
    from core.ret_vector_store import EmbeddingModel
    if not EmbeddingModel.is_ready():
        raise HTTPException(
            status_code=400,
            detail="Embedding 模型未就绪，请先在系统设置中下载模型"
        )


# 向量索引构建逻辑已下沉到 services/vector/service.py
# 此处保留兼容别名（如有外部引用）
_auto_build_vector_index = auto_build_vector_index
_mark_index_stale = mark_index_stale


def _items_in_schemas(db, schema_names: List[str], fallback_schema: str) -> List[SchemaItem]:
    """查询指定 schema 集合的全部字段（平铺）"""
    q = schema_service._base_query(db)
    if schema_names:
        q = q.filter(DbSchema.name.in_(schema_names))
    else:
        q = q.filter(DbSchema.name == fallback_schema)
    rows = q.order_by(DbColumn.created_at.desc(), DbColumn.id.desc()).all()
    return [SchemaItem.model_validate(schema_service._to_flat(r)) for r in rows]


def _ingest_and_respond(parsed_results, user, db_type, source, fallback_schema,
                        extra_fk_line=False, datasource_id=None) -> SchemaListResponse:
    """解析结果入库 + 触发自动索引 + 组装响应（/parse-csv /parse-json /upload 共用）"""
    with session_scope() as db:
        if datasource_id is not None:
            ds = db.query(DataSource).filter(DataSource.id == datasource_id).first()
            if not ds:
                raise HTTPException(status_code=400, detail="数据源不存在，请先创建数据源")
        new_count, duplicate_count, schema_names = schema_service.save_parsed_results(
            parsed_results, user['user_id'], db, db_type=db_type, source=source,
            datasource_id=datasource_id)
    
        message = f"成功插入 {new_count} 条记录"
        if duplicate_count > 0:
            message += f"，跳过 {duplicate_count} 条重复记录"
        if schema_names:
            message += f"，涉及 Schema: {', '.join(schema_names)}"
        if extra_fk_line:
            fk_count = sum(1 for r in parsed_results if r.get('foreign_key'))
            if fk_count > 0:
                message += f"，外键 {fk_count} 条"
    
        items = _items_in_schemas(db, schema_names, fallback_schema)
    
        index_messages = []
        for schema_name in schema_names:
            schema_field_count = schema_service.field_count(schema_name)
            index_message = _auto_build_vector_index(schema_name, schema_field_count)
            if index_message:
                index_messages.append(index_message)
    
        if index_messages:
            message += "。" + "；".join(index_messages)
    
        return SchemaListResponse(items=items, total=len(items), message=message)
# ═══════════════════════════════════════════════════════════════════
# 解析与导入端点
# ═══════════════════════════════════════════════════════════════════

@router.post("/parse-csv", response_model=SchemaListResponse)
def parse_csv_text(
        request: CSVParseRequest,
        user: AdminUser
):
    """解析规范 CSV 文本（仅管理员；数据库类型必填）"""
    # (权限由 AdminUser 依赖统一校验)
    _validate_db_type(request.db_type)
    log_audit(user, "parse_schema_csv", f"schema_name={request.schema_name} db_type={request.db_type}")
    try:
        parsed_results = parse_schema_csv(
            request.csv_text, user['user_id'], request.schema_name)

        if not parsed_results:
            raise HTTPException(status_code=400, detail="无法解析 CSV，请检查表头与内容格式")

        return _ingest_and_respond(parsed_results, user, request.db_type, 'csv',
                                   request.schema_name, datasource_id=request.datasource_id)
    except DDLParseError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"CSV 解析失败：{e}")
        raise HTTPException(status_code=500, detail=f"解析失败：{str(e)}")


@router.post("/parse-json", response_model=SchemaListResponse)
def parse_json_text(
        request: JSONParseRequest,
        user: AdminUser
):
    """解析 JSON 格式的 Schema（仅管理员）"""
    # (权限由 AdminUser 依赖统一校验)
    _validate_db_type(request.db_type)
    try:
        parsed_results = parse_json_schema(request.json_text, user['user_id'], request.schema_name)

        if not parsed_results:
            raise HTTPException(status_code=400, detail="无法解析 JSON，请检查格式")

        return _ingest_and_respond(parsed_results, user, request.db_type, 'json',
                                   request.schema_name, extra_fk_line=True,
                                   datasource_id=request.datasource_id)
    except DDLParseError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"JSON 解析失败：{e}")
        raise HTTPException(status_code=500, detail=f"解析失败：{str(e)}")


@router.post("/upload", response_model=SchemaListResponse)
async def upload_schema_file(
        user: AdminUser,
        file: UploadFile = File(...),
        schema_name: str = Form("default"),
        db_type: str = Form("mysql"),
        datasource_id: int = Form(...),
):
    """上传规范 CSV 或 JSON 文件并解析（仅管理员；数据库类型、数据源必填；≤5MB）"""
    # (权限由 AdminUser 依赖统一校验)
    _validate_db_type(db_type)
    try:
        content = await file.read()
        if len(content) > 5 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="文件过大，仅支持 5MB 以内的 CSV/JSON 文件")

        file_content = content.decode('utf-8')

        filename = (file.filename or '').lower()

        if filename.endswith('.csv'):
            parsed_results = parse_schema_csv(file_content, user['user_id'], schema_name)
            source = 'csv'
        elif filename.endswith('.json'):
            parsed_results = parse_json_schema(file_content, user['user_id'], schema_name)
            source = 'json'
        else:
            raise HTTPException(status_code=400, detail="仅支持 .csv 或 .json 格式文件")

        if not parsed_results:
            raise HTTPException(status_code=400, detail="无法解析文件，请检查格式")

        return _ingest_and_respond(parsed_results, user, db_type, source,
                                   schema_name, extra_fk_line=filename.endswith('.json'),
                                   datasource_id=datasource_id)
    except DDLParseError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"文件上传解析失败：{e}")
        raise HTTPException(status_code=500, detail=f"解析失败：{str(e)}")


# ═══════════════════════════════════════════════════════════════════
# 查询端点
# ═══════════════════════════════════════════════════════════════════

@router.get("/list", response_model=SchemaListResponse)
def get_schema_list(
        user: CurrentUser,
        schema_name: Optional[str] = None,
        table_name: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
):
    """获取用户的 Schema 解析列表，支持按库名、表名、字段名、描述模糊搜索"""
    try:
        with session_scope() as db:
            visible_ids = get_visible_schema_ids(user)
            rows, total = schema_service.query_flat(
                db, schema_name=schema_name, table_name=table_name, search=search,
                visible_schema_ids=visible_ids,
                table_grants_by_schema=get_table_grants_by_schema(user),
                limit=limit, offset=offset)
    
            return SchemaListResponse(
                items=[SchemaItem.model_validate(r) for r in rows],
                total=total
            )
    except Exception as e:
        logger.error(f"获取 Schema 列表失败：{e}")
        raise HTTPException(status_code=500, detail=f"获取失败：{str(e)}")


@router.get("/stats")
def get_schema_stats(user: CurrentUser):
    """获取用户 Schema 统计数据"""
    try:
        with session_scope() as db:
            return schema_service.stats(
                db, get_visible_schema_ids(user),
                table_grants_by_schema=get_table_grants_by_schema(user))
    except Exception as e:
        logger.error(f"获取 Schema 统计失败：{e}")
        raise HTTPException(status_code=500, detail=f"统计失败：{str(e)}")


@router.get("/check", response_model=SchemaCheckResponse)
def check_schema(user: CurrentUser):
    """检查用户是否有 Schema 数据"""
    try:
        with session_scope() as db:
            s = schema_service.stats(
                db, get_visible_schema_ids(user),
                table_grants_by_schema=get_table_grants_by_schema(user))
            return SchemaCheckResponse(
                has_schema=s["column_count"] > 0,
                schema_count=s["schema_count"],
                table_count=s["table_count"]
            )
    except Exception as e:
        logger.error(f"检查 Schema 失败：{e}")
        raise HTTPException(status_code=500, detail=f"检查失败：{str(e)}")


@router.get("/export")
def export_schema(
        user: CurrentUser,
        schema_name: Optional[str] = None,
        table_name: Optional[str] = None,
):
    """导出 Schema 为 CSV"""
    try:
        with session_scope() as db:
            rows, _total = schema_service.query_flat(
                db, schema_name=schema_name, table_name=table_name,
                visible_schema_ids=get_visible_schema_ids(user),
                table_grants_by_schema=get_table_grants_by_schema(user))
    
            output = io.StringIO()
            writer = csv.writer(output)
    
            writer.writerow([
                'schema_name', 'table_name', 'table_description',
                'column_name', 'column_type', 'column_description',
                'column_key', 'is_nullable', 'default_value', 'sample_values'
            ])
    
            for item in rows:
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
    except Exception as e:
        logger.error(f"导出 Schema 失败：{e}")
        raise HTTPException(status_code=500, detail=f"导出失败：{str(e)}")


@router.get("/schemas")
def get_schemas(user: CurrentUser):
    """获取用户可见的 schema 列表（含 db_type 映射与数据源分组，供级联选择）"""
    try:
        with session_scope() as db:
            visible = get_visible_schema_ids(user)
            names = schema_service.list_schema_names(db, visible)
            types = schema_service.list_schema_types(db, visible)
            rows = schema_service.list_schemas_with_datasource(db, visible)
    
            # 数据源 → 库 分组（datasource_id 为空 = 手动导入/未关联）
            groups: dict = {}
            for r in rows:
                key = r['datasource_id'] if r['datasource_id'] is not None else -1
                g = groups.setdefault(key, {
                    "datasource_id": r['datasource_id'],
                    "datasource_name": r['datasource_name'] or '未关联数据源',
                    "schemas": [],
                })
                g["schemas"].append(r['name'])
            datasources = [groups[k] for k in sorted(groups.keys())]
    
            return {"schemas": names, "schema_types": types, "datasources": datasources}
    except Exception as e:
        logger.error(f"获取 schema 列表失败：{e}")
        raise HTTPException(status_code=500, detail=f"获取失败：{str(e)}")


@router.get("/tables")
def get_tables(
        user: CurrentUser,
        schema_name: Optional[str] = None,
):
    """获取指定 schema 下的表名列表"""
    try:
        with session_scope() as db:
            tables = schema_service.list_tables(
                db, schema_name=schema_name,
                visible_schema_ids=get_visible_schema_ids(user),
                table_grants_by_schema=get_table_grants_by_schema(user))
    
            return {
                "tables": [
                    {"name": t[0], "description": t[1]}
                    for t in tables
                ]
            }
    except Exception as e:
        logger.error(f"获取表列表失败：{e}")
        raise HTTPException(status_code=500, detail=f"获取失败：{str(e)}")


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


# ═══════════════════════════════════════════════════════════════════
# 删除 / 更新端点
# ═══════════════════════════════════════════════════════════════════

@router.delete("/schema/{schema_name}")
def delete_schema(
        schema_name: str,
        user: AdminUser
):
    """删除指定 schema 的所有数据（仅管理员）"""
    # (权限由 AdminUser 依赖统一校验)
    try:
        with session_scope() as db:
            count = schema_service.delete_schema_by_name(db, schema_name)
            return {"success": True, "message": f"已删除 schema '{schema_name}' 的 {count} 条记录"}
    except Exception as e:
        logger.error(f"删除 schema 失败：{e}")
        raise HTTPException(status_code=500, detail=f"删除失败：{str(e)}")


@router.delete("/table")
def delete_table(
        schema_name: str,
        table_name: str,
        user: AdminUser
):
    """删除指定表的所有字段（仅管理员）"""
    # (权限由 AdminUser 依赖统一校验)
    try:
        with session_scope() as db:
            count = schema_service.delete_table(db, schema_name, table_name)
            return {"success": True, "message": f"已删除表 '{table_name}' 的 {count} 条记录"}
    except Exception as e:
        logger.error(f"删除表失败：{e}")
        raise HTTPException(status_code=500, detail=f"删除失败：{str(e)}")


@router.delete("/{schema_id}")
def delete_schema_item(
        schema_id: int,
        user: AdminUser
):
    """删除单个字段（仅管理员）"""
    # (权限由 AdminUser 依赖统一校验)
    try:
        with session_scope() as db:
            if not schema_service.delete_column_by_id(db, schema_id):
                raise HTTPException(status_code=404, detail="Schema 项不存在")
            return {"success": True, "message": "删除成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除 Schema 项失败：{e}")
        raise HTTPException(status_code=500, detail=f"删除失败：{str(e)}")


@router.put("/{schema_id}/sample-values")
def update_sample_values(
        schema_id: int,
        request: UpdateSampleValuesRequest,
        user: AdminUser
):
    """更新字段的示例值（仅管理员）"""
    # (权限由 AdminUser 依赖统一校验)
    try:
        with session_scope() as db:
            if not schema_service.update_sample_values(db, schema_id, request.sample_values):
                raise HTTPException(status_code=404, detail="Schema 项不存在")
            return {"success": True, "message": "更新成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新示例值失败：{e}")
        raise HTTPException(status_code=500, detail=f"更新失败：{str(e)}")


# ═══════════════════════════════════════════════════════════════════
# 向量索引端点
# ═══════════════════════════════════════════════════════════════════

@router.post("/build-vector-index")
def build_vector_index(
    request: BuildIndexRequest,
    user: AdminUser
):
    """构建向量索引（仅管理员）"""
    # (权限由 AdminUser 依赖统一校验)
    _check_embedding_ready()
    try:
        from core.ret_index_meta import build_vector_index as do_build

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
    user: CurrentUser,
    schema_name: Optional[str] = None,
):
    """获取向量索引信息"""
    _check_embedding_ready()
    try:
        from core.ret_index_meta import get_vector_index_info as do_get_info

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
def list_vector_indexes(user: AdminUser):
    """列出所有向量索引元数据（仅管理员）"""
    # (权限由 AdminUser 依赖统一校验)
    try:
        from models.vector_index import VectorIndexMeta

        with session_scope() as db:
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
    except Exception as e:
        logger.error(f"获取向量索引列表失败：{e}")
        raise HTTPException(status_code=500, detail=f"获取失败：{str(e)}")
