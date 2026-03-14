# -*- coding: UTF-8 -*-
"""
Schema 管理路由 - DDL 解析和 Schema 管理
"""
import re
import csv
import io
import os
import sqlite3
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import datetime

from models import SessionLocal, SqlSessionLocal, get_db
from models.schema_parse import SchemaParse
from models.user import User
from app.logger import logger
from app.auth import create_access_token, get_current_user
from app.config import TEMP_DB_PATH
from fastapi import Request


router = APIRouter()


def get_user_temp_db_path(user_id: int) -> str:
    """获取用户临时数据库路径"""
    return os.path.join(TEMP_DB_PATH, f'user_{user_id}_temp.db')


class DDLParseRequest(BaseModel):
    """DDL 解析请求"""
    ddl_text: str
    schema_name: str = "default"


class SchemaParseItem(BaseModel):
    """Schema 解析项"""
    id: int
    schema_name: str
    table_name: str
    table_description: Optional[str]
    column_name: str
    column_type: Optional[str]
    column_description: Optional[str]
    column_key: Optional[str]
    is_nullable: Optional[bool] = True
    default_value: Optional[str] = None
    sample_values: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


class UpdateSampleValuesRequest(BaseModel):
    """更新示例值请求"""
    sample_values: str


class SchemaParseListResponse(BaseModel):
    """Schema 解析列表响应"""
    items: List[SchemaParseItem]
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


def parse_ddl(ddl: str, schema_name: str, user_id: int, db: Session) -> List[dict]:
    """解析 DDL 语句并返回解析结果（仅支持单库，表名不能重复）"""
    results = []
    
    use_pattern = r'USE\s+`?([^`\s;]+)`?\s*;'
    use_matches = list(re.finditer(use_pattern, ddl, re.IGNORECASE))
    if use_matches:
        dbs = [m.group(1).strip('`') for m in use_matches]
        raise DDLParseError(f"不支持多库 DDL，检测到 USE 语句切换数据库：{', '.join(set(dbs))}。请仅上传单个数据库的 DDL。")
    
    create_db_pattern = r'CREATE\s+DATABASE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?([^`\s;]+)`?'
    create_db_matches = list(re.finditer(create_db_pattern, ddl, re.IGNORECASE))
    if len(create_db_matches) > 1:
        dbs = [m.group(1).strip('`') for m in create_db_matches]
        raise DDLParseError(f"不支持多库 DDL，检测到多个 CREATE DATABASE 语句：{', '.join(dbs)}。请仅上传单个数据库的 DDL。")
    
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
        table_results = parse_single_table(table_ddl, schema_name, user_id)
        results.extend(table_results)
    
    return results


def parse_single_table(table_ddl: str, schema_name: str, user_id: int) -> List[dict]:
    """解析单个 CREATE TABLE 语句"""
    results = []
    
    table_name_match = re.search(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?([^`\s(]+)`?\s*\(', table_ddl, re.IGNORECASE)
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
    table_comment_match = re.search(r"COMMENT\s*=?\s*['\"]([^'\"]+)['\"]", rest_of_ddl, re.IGNORECASE)
    if table_comment_match:
        table_comment = table_comment_match.group(1)
    
    pk_match = re.search(r'PRIMARY KEY\s*\(([^)]+)\)', table_struct, re.IGNORECASE)
    primary_keys = []
    if pk_match:
        pk_str = pk_match.group(1)
        primary_keys = [pk.strip().strip('`') for pk in pk_str.split(',')]
    
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
        comment_match = re.search(r"COMMENT\s*=?\s*['\"]([^'\"]+)['\"]", rest, re.IGNORECASE)
        if comment_match:
            column_desc = comment_match.group(1)
        
        is_nullable = True
        if re.search(r'\bNOT\s+NULL\b', rest, re.IGNORECASE):
            is_nullable = False
        
        default_value = None
        default_match = re.search(r"DEFAULT\s+(['\"]?)([^'\"\s,]+)\1", rest, re.IGNORECASE)
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
            'is_nullable': is_nullable,
            'default_value': default_value,
            'sample_values': None
        })
    
    return results


@router.post("/schema/parse", response_model=SchemaParseListResponse)
async def parse_ddl_text(
    request: DDLParseRequest,
    user = Depends(get_current_user)
):
    """解析 DDL 文本"""
    try:
        user_id = user['user_id']
        db = SqlSessionLocal()
        
        try:
            parsed_results = parse_ddl(request.ddl_text, request.schema_name, user_id, db)
            
            if not parsed_results:
                raise HTTPException(status_code=400, detail="无法解析 DDL，请检查格式")
            
            new_count = 0
            duplicate_count = 0
            for result in parsed_results:
                existing = db.query(SchemaParse).filter(
                    SchemaParse.user_id == user_id,
                    SchemaParse.schema_name == result['schema_name'],
                    SchemaParse.table_name == result['table_name'],
                    SchemaParse.column_name == result['column_name']
                ).first()
                
                if existing:
                    duplicate_count += 1
                    continue
                
                schema_parse = SchemaParse(**result)
                db.add(schema_parse)
                new_count += 1
            
            db.commit()
            
            message = f"成功插入 {new_count} 条记录"
            if duplicate_count > 0:
                message += f"，跳过 {duplicate_count} 条重复记录"
            
            items = db.query(SchemaParse).filter(
                SchemaParse.user_id == user_id,
                SchemaParse.schema_name == request.schema_name
            ).all()
            
            return SchemaParseListResponse(
                items=[SchemaParseItem.model_validate(item) for item in items],
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


@router.post("/schema/upload", response_model=SchemaParseListResponse)
async def upload_ddl_file(
    file: UploadFile = File(...),
    schema_name: str = Form("default"),
    user = Depends(get_current_user)
):
    """上传 DDL 文件并解析"""
    try:
        user_id = user['user_id']
        
        content = await file.read()
        ddl_text = content.decode('utf-8')
        
        db = SqlSessionLocal()
        
        try:
            parsed_results = parse_ddl(ddl_text, schema_name, user_id, db)
            
            if not parsed_results:
                raise HTTPException(status_code=400, detail="无法解析 DDL 文件，请检查格式")
            
            new_count = 0
            duplicate_count = 0
            for result in parsed_results:
                existing = db.query(SchemaParse).filter(
                    SchemaParse.user_id == user_id,
                    SchemaParse.schema_name == result['schema_name'],
                    SchemaParse.table_name == result['table_name'],
                    SchemaParse.column_name == result['column_name']
                ).first()
                
                if existing:
                    duplicate_count += 1
                    continue
                
                schema_parse = SchemaParse(**result)
                db.add(schema_parse)
                new_count += 1
            
            db.commit()
            
            message = f"成功插入 {new_count} 条记录"
            if duplicate_count > 0:
                message += f"，跳过 {duplicate_count} 条重复记录"
            
            items = db.query(SchemaParse).filter(
                SchemaParse.user_id == user_id,
                SchemaParse.schema_name == schema_name
            ).all()
            
            return SchemaParseListResponse(
                items=[SchemaParseItem.model_validate(item) for item in items],
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
        logger.error(f"DDL 文件上传解析失败：{e}")
        raise HTTPException(status_code=500, detail=f"解析失败：{str(e)}")


@router.get("/schema/list", response_model=SchemaParseListResponse)
async def get_schema_list(
    schema_name: Optional[str] = None,
    table_name: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    user = Depends(get_current_user)
):
    """获取用户的 Schema 解析列表"""
    try:
        user_id = user['user_id']
        db = SqlSessionLocal()
        
        try:
            query = db.query(SchemaParse).filter(SchemaParse.user_id == user_id)
            
            if schema_name:
                query = query.filter(SchemaParse.schema_name == schema_name)
            if table_name:
                query = query.filter(SchemaParse.table_name == table_name)
            
            total = query.count()
            items = query.order_by(SchemaParse.created_at.desc()).limit(limit).offset(offset).all()
            
            return SchemaParseListResponse(
                items=[SchemaParseItem.model_validate(item) for item in items],
                total=total
            )
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"获取 Schema 列表失败：{e}")
        raise HTTPException(status_code=500, detail=f"获取失败：{str(e)}")


@router.put("/schema/{schema_id}/sample-values")
async def update_sample_values(
    schema_id: int,
    request: UpdateSampleValuesRequest,
    user = Depends(get_current_user)
):
    """更新字段的示例值"""
    try:
        user_id = user['user_id']
        db = SqlSessionLocal()
        
        try:
            item = db.query(SchemaParse).filter(
                SchemaParse.id == schema_id,
                SchemaParse.user_id == user_id
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


@router.get("/schema/stats")
async def get_schema_stats(
    user = Depends(get_current_user)
):
    """获取用户 Schema 统计数据"""
    try:
        user_id = user['user_id']
        db = SqlSessionLocal()
        
        try:
            # 统计字段总数
            column_count = db.query(SchemaParse).filter(SchemaParse.user_id == user_id).count()
            
            # 统计不重复的 schema 数量
            schema_count = db.query(SchemaParse.schema_name).filter(
                SchemaParse.user_id == user_id
            ).distinct().count()
            
            # 统计不重复的表数量
            table_count = db.query(SchemaParse.table_name).filter(
                SchemaParse.user_id == user_id
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


@router.get("/schema/check", response_model=SchemaCheckResponse)
async def check_schema(
    user = Depends(get_current_user)
):
    """检查用户是否有 Schema 数据"""
    try:
        user_id = user['user_id']
        db = SqlSessionLocal()
        
        try:
            total = db.query(SchemaParse).filter(SchemaParse.user_id == user_id).count()
            
            tables = db.query(SchemaParse.schema_name, SchemaParse.table_name).filter(
                SchemaParse.user_id == user_id
            ).distinct().all()
            
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


@router.get("/schema/export")
async def export_schema(
    schema_name: Optional[str] = None,
    table_name: Optional[str] = None,
    user = Depends(get_current_user)
):
    """导出 Schema 为 CSV"""
    try:
        user_id = user['user_id']
        db = SqlSessionLocal()
        
        try:
            query = db.query(SchemaParse).filter(SchemaParse.user_id == user_id)
            
            if schema_name:
                query = query.filter(SchemaParse.schema_name == schema_name)
            if table_name:
                query = query.filter(SchemaParse.table_name == table_name)
            
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
            
            filename = f"schema_{schema_name or 'all'}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            
            return StreamingResponse(
                output,
                media_type="text/csv",
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"导出 Schema 失败：{e}")
        raise HTTPException(status_code=500, detail=f"导出失败：{str(e)}")


class BatchDeleteRequest(BaseModel):
    """批量删除请求"""
    ids: List[int]


@router.post("/schema/batch-delete")
async def batch_delete_schema(
    request: BatchDeleteRequest,
    user = Depends(get_current_user)
):
    """批量删除 Schema 项"""
    try:
        user_id = user['user_id']
        db = SqlSessionLocal()
        
        try:
            deleted_count = 0
            for schema_id in request.ids:
                item = db.query(SchemaParse).filter(
                    SchemaParse.id == schema_id,
                    SchemaParse.user_id == user_id
                ).first()
                
                if item:
                    db.delete(item)
                    deleted_count += 1
            
            db.commit()
            
            return {"success": True, "message": f"成功删除 {deleted_count} 条记录", "deleted_count": deleted_count}
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"批量删除 Schema 失败：{e}")
        raise HTTPException(status_code=500, detail=f"删除失败：{str(e)}")


@router.delete("/schema/table/{schema_name}/{table_name}")
async def delete_table(
    schema_name: str,
    table_name: str,
    user = Depends(get_current_user)
):
    """按表删除所有字段"""
    try:
        user_id = user['user_id']
        db = SqlSessionLocal()
        
        try:
            deleted = db.query(SchemaParse).filter(
                SchemaParse.user_id == user_id,
                SchemaParse.schema_name == schema_name,
                SchemaParse.table_name == table_name
            ).delete()
            
            db.commit()
            
            return {"success": True, "message": f"成功删除表 {schema_name}.{table_name} 的 {deleted} 个字段", "deleted_count": deleted}
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"删除表失败：{e}")
        raise HTTPException(status_code=500, detail=f"删除失败：{str(e)}")


@router.delete("/schema/schema/{schema_name}")
async def delete_schema_by_name(
    schema_name: str,
    user = Depends(get_current_user)
):
    """按 Schema 名称删除所有字段"""
    try:
        user_id = user['user_id']
        db = SqlSessionLocal()
        
        try:
            deleted = db.query(SchemaParse).filter(
                SchemaParse.user_id == user_id,
                SchemaParse.schema_name == schema_name
            ).delete()
            
            db.commit()
            
            return {"success": True, "message": f"成功删除 Schema {schema_name} 的 {deleted} 个字段", "deleted_count": deleted}
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"删除 Schema 失败：{e}")
        raise HTTPException(status_code=500, detail=f"删除失败：{str(e)}")


@router.delete("/schema/{schema_id}")
async def delete_schema(
    schema_id: int,
    user = Depends(get_current_user)
):
    """删除 Schema 项"""
    try:
        user_id = user['user_id']
        db = SqlSessionLocal()
        
        try:
            item = db.query(SchemaParse).filter(
                SchemaParse.id == schema_id,
                SchemaParse.user_id == user_id
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
        logger.error(f"删除 Schema 失败：{e}")
        raise HTTPException(status_code=500, detail=f"删除失败：{str(e)}")


@router.get("/schema/table-names")
async def get_table_names(
    schema_name: Optional[str] = None,
    user = Depends(get_current_user)
):
    """获取所有表名"""
    try:
        user_id = user['user_id']
        db = SqlSessionLocal()
        
        try:
            query = db.query(SchemaParse.table_name).filter(
                SchemaParse.user_id == user_id
            ).distinct()
            
            if schema_name:
                query = query.filter(SchemaParse.schema_name == schema_name)
            
            tables = query.all()
            
            return {"tables": [t.table_name for t in tables]}
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"获取表名失败：{e}")
        raise HTTPException(status_code=500, detail=f"获取失败：{str(e)}")


@router.get("/schema/schema-names")
async def get_schema_names(
    user = Depends(get_current_user)
):
    """获取所有 schema 名称"""
    try:
        user_id = user['user_id']
        db = SqlSessionLocal()
        
        try:
            schemas = db.query(SchemaParse.schema_name).filter(
                SchemaParse.user_id == user_id
            ).distinct().all()
            
            return {"schemas": [s.schema_name for s in schemas]}
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"获取 schema 名称失败：{e}")
        raise HTTPException(status_code=500, detail=f"获取失败：{str(e)}")
