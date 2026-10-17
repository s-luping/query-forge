# -*- coding: UTF-8 -*-
"""Schema 管理路由（薄层）— 解析逻辑在 services/schema/parsers，读写逻辑在 services/schema/service

URL 与响应结构与旧版完全一致，前端无感切换。
"""
import csv
import io
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from app.auth import AdminUser, CurrentUser
from app.limiter import LIMIT_HEAVY, LIMIT_READ, LIMIT_WRITE, limiter
from app.logger import log_audit, logger
from app.permissions import get_table_grants_by_schema, get_visible_schema_ids, is_schema_visible
from app.response import ok, ok_msg
from crud.base import session_scope
from models.datasource import DataSource
from models.schema import DbColumn, DbSchema
from services import schema_service
from services.schema_parsers import (
    SUPPORTED_DB_TYPES,
    DDLParseError,
    parse_json_schema,
    parse_schema_csv,
)
from services.vector_service import mark_index_stale  # 从服务层导入（消除路由层职责过重）

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
    sensitive_level: str = 'public'
    is_dimension: bool = False
    is_measure: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


class UpdateSampleValuesRequest(BaseModel):
    """更新示例值请求"""
    sample_values: str


class UpdateColumnMetaRequest(BaseModel):
    """更新字段维度/度量/描述请求"""
    is_dimension: Optional[bool] = None
    is_measure: Optional[bool] = None
    description: Optional[str] = None


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


# 向量索引构建逻辑已下沉到 services/vector_service.py
# 此处保留兼容别名（如有外部引用）
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
    """解析结果入库 + 标记索引过期 + 组装响应（/parse-csv /parse-json /upload 共用）"""
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

        # 不再自动构建：只标记全库索引过期，由定时任务「向量索引重建」按需执行
        if schema_names:
            mark_index_stale('default')
            message += "。向量索引已标记过期，将由定时任务自动重建"

        return SchemaListResponse(items=items, total=len(items), message=message)
# ═══════════════════════════════════════════════════════════════════
# 解析与导入端点
# ═══════════════════════════════════════════════════════════════════

@router.post("/parse-csv", response_model=SchemaListResponse)
@limiter.limit(LIMIT_WRITE)
def parse_csv_text(
        request: Request,
        payload: CSVParseRequest,
        user: AdminUser
):
    """解析规范 CSV 文本（仅管理员；数据库类型必填）"""
    # (权限由 AdminUser 依赖统一校验)
    _validate_db_type(payload.db_type)
    log_audit(user, "parse_schema_csv", f"schema_name={payload.schema_name} db_type={payload.db_type}")
    try:
        parsed_results = parse_schema_csv(
            payload.csv_text, user['user_id'], payload.schema_name)

        if not parsed_results:
            raise HTTPException(status_code=400, detail="无法解析 CSV，请检查表头与内容格式")

        return _ingest_and_respond(parsed_results, user, payload.db_type, 'csv',
                                   payload.schema_name, datasource_id=payload.datasource_id)
    except DDLParseError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"CSV 解析失败：{e}")
        raise HTTPException(status_code=500, detail=f"解析失败：{str(e)}")


@router.post("/parse-json", response_model=SchemaListResponse)
@limiter.limit(LIMIT_WRITE)
def parse_json_text(
        request: Request,
        payload: JSONParseRequest,
        user: AdminUser
):
    """解析 JSON 格式的 Schema（仅管理员）"""
    # (权限由 AdminUser 依赖统一校验)
    _validate_db_type(payload.db_type)
    try:
        parsed_results = parse_json_schema(payload.json_text, user['user_id'], payload.schema_name)

        if not parsed_results:
            raise HTTPException(status_code=400, detail="无法解析 JSON，请检查格式")

        return _ingest_and_respond(parsed_results, user, payload.db_type, 'json',
                                   payload.schema_name, extra_fk_line=True,
                                   datasource_id=payload.datasource_id)
    except DDLParseError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"JSON 解析失败：{e}")
        raise HTTPException(status_code=500, detail=f"解析失败：{str(e)}")


@router.post("/upload", response_model=SchemaListResponse)
@limiter.limit(LIMIT_HEAVY)
async def upload_schema_file(
        request: Request,
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
@limiter.limit(LIMIT_READ)
def get_schema_list(
        request: Request,
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
@limiter.limit(LIMIT_READ)
def get_schema_stats(request: Request, user: CurrentUser):
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
@limiter.limit(LIMIT_READ)
def check_schema(request: Request, user: CurrentUser):
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
@limiter.limit(LIMIT_HEAVY)
def export_schema(
        request: Request,
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
@limiter.limit(LIMIT_READ)
def get_schemas(request: Request, user: CurrentUser):
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

            # 库名 → id 映射（供知识作用域等场景按 id 关联）
            _id_map = schema_service.get_schema_name_map(db)
            schema_ids = {name: sid for sid, name in _id_map.items()}

            return {"schemas": names, "schema_types": types,
                    "datasources": datasources, "schema_ids": schema_ids}
    except Exception as e:
        logger.error(f"获取 schema 列表失败：{e}")
        raise HTTPException(status_code=500, detail=f"获取失败：{str(e)}")


@router.get("/tables")
@limiter.limit(LIMIT_READ)
def get_tables(
        request: Request,
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
@limiter.limit(LIMIT_READ)
def get_supported_db_types(request: Request):
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
@limiter.limit(LIMIT_WRITE)
def delete_schema(
        request: Request,
        schema_name: str,
        user: AdminUser
):
    """删除指定 schema 的所有数据（仅管理员）"""
    # (权限由 AdminUser 依赖统一校验)
    try:
        with session_scope() as db:
            count = schema_service.delete_schema_by_name(db, schema_name)
            return ok_msg(f"已删除 schema '{schema_name}' 的 {count} 条记录")
    except Exception as e:
        logger.error(f"删除 schema 失败：{e}")
        raise HTTPException(status_code=500, detail=f"删除失败：{str(e)}")


@router.delete("/table")
@limiter.limit(LIMIT_WRITE)
def delete_table(
        request: Request,
        schema_name: str,
        table_name: str,
        user: AdminUser
):
    """删除指定表的所有字段（仅管理员）"""
    # (权限由 AdminUser 依赖统一校验)
    try:
        with session_scope() as db:
            count = schema_service.delete_table(db, schema_name, table_name)
            return ok_msg(f"已删除表 '{table_name}' 的 {count} 条记录")
    except Exception as e:
        logger.error(f"删除表失败：{e}")
        raise HTTPException(status_code=500, detail=f"删除失败：{str(e)}")


@router.delete("/{schema_id}")
@limiter.limit(LIMIT_WRITE)
def delete_schema_item(
        request: Request,
        schema_id: int,
        user: AdminUser
):
    """删除单个字段（仅管理员）"""
    # (权限由 AdminUser 依赖统一校验)
    try:
        with session_scope() as db:
            if not schema_service.delete_column_by_id(db, schema_id):
                raise HTTPException(status_code=404, detail="Schema 项不存在")
            return ok_msg("删除成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除 Schema 项失败：{e}")
        raise HTTPException(status_code=500, detail=f"删除失败：{str(e)}")


@router.put("/{schema_id}/sample-values")
@limiter.limit(LIMIT_WRITE)
def update_sample_values(
        schema_id: int,
        payload: UpdateSampleValuesRequest,
        request: Request,
        user: AdminUser
):
    """更新字段的示例值（仅管理员）"""
    # (权限由 AdminUser 依赖统一校验)
    try:
        with session_scope() as db:
            if not schema_service.update_sample_values(db, schema_id, payload.sample_values):
                raise HTTPException(status_code=404, detail="Schema 项不存在")
            return ok_msg("更新成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新示例值失败：{e}")
        raise HTTPException(status_code=500, detail=f"更新失败：{str(e)}")


@router.put("/column/{column_id}")
@limiter.limit(LIMIT_WRITE)
def update_column_meta(
        column_id: int,
        payload: UpdateColumnMetaRequest,
        request: Request,
        user: AdminUser
):
    """更新字段的维度/度量标记与描述（仅管理员）"""
    # (权限由 AdminUser 依赖统一校验)
    try:
        with session_scope() as db:
            if not schema_service.update_column_metadata(
                db, column_id,
                is_dimension=payload.is_dimension,
                is_measure=payload.is_measure,
                description=payload.description,
            ):
                raise HTTPException(status_code=404, detail="字段不存在")
            return ok_msg("更新成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新字段元数据失败：{e}")
        raise HTTPException(status_code=500, detail=f"更新失败：{str(e)}")


# ═══════════════════════════════════════════════════════════════════
# 表关系维护
# ═══════════════════════════════════════════════════════════════════

from crud.schema import column_crud, relation_crud, schema_crud, table_crud

ALLOWED_JOIN_TYPES = {'INNER JOIN', 'LEFT JOIN', 'RIGHT JOIN', 'FULL JOIN'}
ALLOWED_RELATION_TYPES = {'1:1', '1:N', 'N:1', 'N:N'}


class RelationCreateRequest(BaseModel):
    """新建表关系请求（同数据源可跨库：左右两侧各自选库）"""
    left_schema_name: str
    left_table: str
    left_column: str
    right_schema_name: str
    right_table: str
    right_column: str
    join_type: str = 'INNER JOIN'
    relation_type: str = '1:N'
    description: str = ''


class RelationUpdateRequest(BaseModel):
    """更新表关系请求（全字段覆盖，前端弹窗回显后整体提交）"""
    left_schema_name: str
    left_table: str
    left_column: str
    right_schema_name: str
    right_table: str
    right_column: str
    join_type: str = 'INNER JOIN'
    relation_type: str = '1:N'
    description: str = ''


class RelationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    left_schema_id: int
    right_schema_id: int
    left_schema_name: str = ''
    right_schema_name: str = ''
    left_table: str
    left_column: str
    right_table: str
    right_column: str
    join_type: str
    relation_type: str
    description: Optional[str] = ''
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


def _validate_relation_payload(left_schema, right_schema, left_table, left_column,
                               right_table, right_column, join_type, relation_type):
    """校验关系字段：连接方式/基数合法 + 两侧表与字段在各自 schema 中真实存在"""
    if join_type not in ALLOWED_JOIN_TYPES:
        raise HTTPException(400, f"连接方式无效，可选: {', '.join(sorted(ALLOWED_JOIN_TYPES))}")
    if relation_type not in ALLOWED_RELATION_TYPES:
        raise HTTPException(400, f"关系基数无效，可选: {', '.join(sorted(ALLOWED_RELATION_TYPES))}")
    if left_schema.id == right_schema.id and left_table == right_table and left_column == right_column:
        raise HTTPException(400, "两侧连接字段不能是同一字段")

    # 左表/左字段在左库校验
    ltable = table_crud.get_by_schema_and_name(left_schema.id, left_table)
    if not ltable:
        raise HTTPException(400, f"左表不存在: {left_schema.name}.{left_table}")
    lcol = column_crud.get_by_table_and_name(ltable.id, left_column)
    if not lcol:
        raise HTTPException(400, f"左字段不存在: {left_schema.name}.{left_table}.{left_column}")
    # 右表/右字段在右库校验（跨库时与左库不同）
    rtable = table_crud.get_by_schema_and_name(right_schema.id, right_table)
    if not rtable:
        raise HTTPException(400, f"右表不存在: {right_schema.name}.{right_table}")
    rcol = column_crud.get_by_table_and_name(rtable.id, right_column)
    if not rcol:
        raise HTTPException(400, f"右字段不存在: {right_schema.name}.{right_table}.{right_column}")


@router.get("/relations")
@limiter.limit(LIMIT_READ)
def list_relations(request: Request, user: CurrentUser, schema_name: Optional[str] = None):
    """表关系列表（按用户可见 schema 过滤；可再按库名筛选，左右任一侧命中即匹配）"""
    try:
        visible = get_visible_schema_ids(user)
        relations = relation_crud.list_by_schemas(visible) if visible is not None \
            else relation_crud.list_all(order_by='id')
        # 注意：visible=None 表示管理员可见全部，必须传 None 给 list_visible（传 [] 会返回空）
        name_map = {s.id: s.name for s in schema_crud.list_visible(visible)}
        if schema_name:
            relations = [r for r in relations
                         if name_map.get(r.left_schema_id) == schema_name
                         or name_map.get(r.right_schema_id) == schema_name]

        items = []
        for r in relations:
            out = RelationOut.model_validate(r)
            out.left_schema_name = name_map.get(r.left_schema_id, '')
            out.right_schema_name = name_map.get(r.right_schema_id, '')
            items.append(out)
        return ok({"items": items, "total": len(items)})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取表关系列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")


@router.post("/relations")
@limiter.limit(LIMIT_WRITE)
def create_relation(request: Request, req: RelationCreateRequest, user: AdminUser):
    """新建表关系（仅管理员；表/字段须真实存在，支持跨库）"""
    log_audit(user, "create_table_relation",
              f"{req.left_schema_name}.{req.left_table}.{req.left_column}"
              f"={req.right_schema_name}.{req.right_table}.{req.right_column}")
    try:
        left_schema = schema_crud.get_by_name(req.left_schema_name.strip())
        if not left_schema:
            raise HTTPException(400, f"左库不存在: {req.left_schema_name}")
        right_schema = schema_crud.get_by_name(req.right_schema_name.strip())
        if not right_schema:
            raise HTTPException(400, f"右库不存在: {req.right_schema_name}")

        left_table, left_column = req.left_table.strip(), req.left_column.strip()
        right_table, right_column = req.right_table.strip(), req.right_column.strip()
        _validate_relation_payload(left_schema, right_schema, left_table, left_column,
                                   right_table, right_column,
                                   req.join_type, req.relation_type)

        if relation_crud.exists_same(left_schema.id, left_table, left_column,
                                     right_schema.id, right_table, right_column):
            raise HTTPException(400, "该连接关系已存在（两侧字段相同即视为重复）")

        rel = relation_crud.create(
            schema_id=left_schema.id,
            left_schema_id=left_schema.id, right_schema_id=right_schema.id,
            left_table=left_table, left_column=left_column,
            right_table=right_table, right_column=right_column,
            join_type=req.join_type, relation_type=req.relation_type,
            description=req.description, created_by=user['user_id'],
        )
        out = RelationOut.model_validate(rel)
        out.left_schema_name = left_schema.name
        out.right_schema_name = right_schema.name
        return out
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"新建表关系失败: {e}")
        raise HTTPException(status_code=500, detail=f"创建失败: {str(e)}")


@router.put("/relations/{relation_id}")
@limiter.limit(LIMIT_WRITE)
def update_relation(request: Request, relation_id: int, req: RelationUpdateRequest, user: AdminUser):
    """更新表关系（仅管理员；支持跨库，可改两侧库）"""
    log_audit(user, "update_table_relation", f"id={relation_id}")
    try:
        rel = relation_crud.get_by_id(relation_id)
        if not rel:
            raise HTTPException(404, "表关系不存在")
        left_schema = schema_crud.get_by_name(req.left_schema_name.strip())
        if not left_schema:
            raise HTTPException(400, f"左库不存在: {req.left_schema_name}")
        right_schema = schema_crud.get_by_name(req.right_schema_name.strip())
        if not right_schema:
            raise HTTPException(400, f"右库不存在: {req.right_schema_name}")

        left_table, left_column = req.left_table.strip(), req.left_column.strip()
        right_table, right_column = req.right_table.strip(), req.right_column.strip()
        _validate_relation_payload(left_schema, right_schema, left_table, left_column,
                                   right_table, right_column,
                                   req.join_type, req.relation_type)

        if relation_crud.exists_same(left_schema.id, left_table, left_column,
                                     right_schema.id, right_table, right_column,
                                     exclude_id=relation_id):
            raise HTTPException(400, "该连接关系已存在（两侧字段相同即视为重复）")

        rel = relation_crud.update(relation_id,
                                   schema_id=left_schema.id,
                                   left_schema_id=left_schema.id,
                                   right_schema_id=right_schema.id,
                                   left_table=left_table, left_column=left_column,
                                   right_table=right_table, right_column=right_column,
                                   join_type=req.join_type, relation_type=req.relation_type,
                                   description=req.description)
        out = RelationOut.model_validate(rel)
        out.left_schema_name = left_schema.name
        out.right_schema_name = right_schema.name
        return out
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新表关系失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新失败: {str(e)}")


@router.delete("/relations/{relation_id}")
@limiter.limit(LIMIT_WRITE)
def delete_relation(request: Request, relation_id: int, user: AdminUser):
    """删除表关系（仅管理员）"""
    log_audit(user, "delete_table_relation", f"id={relation_id}")
    try:
        if not relation_crud.delete(relation_id):
            raise HTTPException(404, "表关系不存在")
        return ok_msg("表关系已删除")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除表关系失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")


@router.get("/table-columns")
@limiter.limit(LIMIT_READ)
def get_table_columns(request: Request, user: CurrentUser, schema_name: str, table_name: str):
    """获取指定表的字段列表（表关系维护下拉用，含权限校验）"""
    try:
        if not is_schema_visible(user, schema_name):
            raise HTTPException(403, "无权访问该数据库")
        schema = schema_crud.get_by_name(schema_name)
        if not schema:
            return {"columns": []}
        table = table_crud.get_by_schema_and_name(schema.id, table_name)
        if not table:
            return {"columns": []}
        cols = column_crud.list_by_table(table.id)
        return {"columns": [
            {"name": c.name, "data_type": c.data_type or '', "description": c.description or ''}
            for c in cols
        ]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取表字段失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")


# ═══════════════════════════════════════════════════════════════════
# 向量索引端点
# ═══════════════════════════════════════════════════════════════════

@router.post("/build-vector-index")
@limiter.limit(LIMIT_HEAVY)
def build_vector_index(
    request: Request,
    payload: BuildIndexRequest,
    user: AdminUser
):
    """构建向量索引（仅管理员，重接口：全库重建耗时以分钟计）

    注意：body 参数命名为 payload，request 名留给 slowapi 定位 Request。
    """
    # (权限由 AdminUser 依赖统一校验)
    _check_embedding_ready()
    try:
        from core.ret_index_meta import build_vector_index as do_build
        from scheduler.jobs.vector_index import vector_build_lock

        # 非阻塞拿锁：已有构建（手动或定时）在进行时直接拒绝，避免并发全量构建
        if not vector_build_lock.acquire(blocking=False):
            return ok({'result': None}, '已有构建任务在进行中，请稍后再试')

        try:
            result = do_build(payload.schema_name)
        finally:
            vector_build_lock.release()
        message = "向量索引重建成功" if payload.rebuild else "向量索引构建成功"

        return ok({'result': result}, message)

    except Exception as e:
        logger.error(f"构建向量索引失败：{e}")
        raise HTTPException(status_code=500, detail=f"构建失败：{str(e)}")


@router.get("/vector-index-info", response_model=IndexInfoResponse)
@limiter.limit(LIMIT_READ)
def get_vector_index_info(
    request: Request,
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
@limiter.limit(LIMIT_READ)
def list_vector_indexes(request: Request, user: AdminUser):
    """列出向量索引元数据（仅管理员）

    对话为全库模式，统一维护 'default' 全库索引一行；历史按库索引行
    一并返回但标记 legacy（前端仅展示 default）。
    """
    # (权限由 AdminUser 依赖统一校验)
    try:
        from models.vector_index import VectorIndexMeta

        with session_scope() as db:
            rows = db.query(VectorIndexMeta).order_by(
                VectorIndexMeta.schema_name.asc()
            ).all()
            # 仅返回全库索引（default）行；历史按库行保留在 DB 但不展示
            rows = [r for r in rows if r.schema_name in ('default', '')] or rows[:0]
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
