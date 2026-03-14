# -*- coding: UTF-8 -*-
"""
Schema管理路由 - DDL解析和Schema管理
"""
import re
import csv
import io
import os
import sqlite3
import random
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


def generate_mock_value(column_type: str, column_name: str) -> any:
    """根据列类型生成模拟数据"""
    column_type_lower = column_type.lower() if column_type else ''
    column_name_lower = column_name.lower() if column_name else ''
    
    if 'int' in column_type_lower:
        return random.randint(1, 1000)
    elif 'float' in column_type_lower or 'double' in column_type_lower or 'decimal' in column_type_lower:
        return round(random.uniform(1, 10000), 2)
    elif 'date' in column_type_lower:
        return f"2024-{random.randint(1,12):02d}-{random.randint(1,28):02d}"
    elif 'time' in column_type_lower:
        return f"{random.randint(0,23):02d}:{random.randint(0,59):02d}:{random.randint(0,59):02d}"
    elif 'bool' in column_type_lower or 'tinyint(1)' in column_type_lower:
        return random.choice([0, 1])
    elif 'text' in column_type_lower or 'varchar' in column_type_lower or 'char' in column_type_lower:
        if 'name' in column_name_lower:
            return random.choice(['张三', '李四', '王五', '赵六', '钱七', '孙八'])
        elif 'email' in column_name_lower:
            return f"user{random.randint(1,100)}@example.com"
        elif 'phone' in column_name_lower or 'tel' in column_name_lower:
            return f"138{random.randint(10000000, 99999999)}"
        elif 'address' in column_name_lower:
            return random.choice(['北京市朝阳区', '上海市浦东新区', '广州市天河区', '深圳市南山区'])
        elif 'status' in column_name_lower:
            return random.choice(['active', 'inactive', 'pending'])
        elif 'desc' in column_name_lower or 'description' in column_name_lower:
            return f"描述信息{random.randint(1, 100)}"
        else:
            return f"数据{random.randint(1, 100)}"
    else:
        return f"值{random.randint(1, 100)}"


def create_temp_table_and_mock_data(user_id: int, ddl_text: str, table_name: str, columns: List[dict]):
    """创建临时数据库表并生成模拟数据"""
    temp_db_path = get_user_temp_db_path(user_id)
    
    if not os.path.exists(TEMP_DB_PATH):
        os.makedirs(TEMP_DB_PATH)
        logger.info(f"创建临时数据库目录: {TEMP_DB_PATH}")
    
    conn = sqlite3.connect(temp_db_path)
    cursor = conn.cursor()
    
    try:
        # 删除已存在的表
        cursor.execute(f"DROP TABLE IF EXISTS `{table_name}`")
        
        # 创建表 - 转换MySQL语法到SQLite
        create_sql = convert_mysql_to_sqlite(ddl_text, table_name, columns)
        logger.info(f"创建临时表SQL: {create_sql}")
        cursor.execute(create_sql)
        
        # 生成模拟数据 (每个表生成5-10条)
        mock_count = random.randint(5, 10)
        for _ in range(mock_count):
            col_names = []
            values = []
            placeholders = []
            for col in columns:
                if col.get('column_key') == 'PRI' and 'int' in (col.get('column_type') or '').lower():
                    # 主键自增，跳过
                    continue
                col_names.append(f"`{col.get('column_name')}`")
                values.append(generate_mock_value(col.get('column_type'), col.get('column_name')))
                placeholders.append('?')
            
            if values:
                insert_sql = f"INSERT INTO `{table_name}` ({','.join(col_names)}) VALUES ({','.join(placeholders)})"
                cursor.execute(insert_sql, values)
        
        conn.commit()
        logger.info(f"临时数据库创建成功: {temp_db_path}, 表: {table_name}, 模拟数据: {mock_count}条")
        
    except Exception as e:
        logger.error(f"创建临时表失败: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


def convert_mysql_to_sqlite(ddl_text: str, table_name: str, columns: List[dict]) -> str:
    """将MySQL DDL转换为SQLite兼容的DDL"""
    column_defs = []
    primary_keys = []
    
    for col in columns:
        col_name = col.get('column_name')
        col_type = col.get('column_type', 'TEXT')
        col_key = col.get('column_key')
        
        # 转换数据类型
        col_type_lower = col_type.lower()
        if 'int' in col_type_lower:
            sqlite_type = 'INTEGER'
        elif 'varchar' in col_type_lower or 'char' in col_type_lower or 'text' in col_type_lower:
            sqlite_type = 'TEXT'
        elif 'float' in col_type_lower or 'double' in col_type_lower or 'decimal' in col_type_lower:
            sqlite_type = 'REAL'
        elif 'date' in col_type_lower or 'time' in col_type_lower:
            sqlite_type = 'TEXT'
        elif 'bool' in col_type_lower or 'tinyint(1)' in col_type_lower:
            sqlite_type = 'INTEGER'
        else:
            sqlite_type = 'TEXT'
        
        # 构建列定义
        col_def = f"`{col_name}` {sqlite_type}"
        
        # 主键自增
        if col_key == 'PRI' and 'int' in col_type_lower:
            col_def += ' PRIMARY KEY AUTOINCREMENT'
        else:
            if col_key == 'PRI':
                primary_keys.append(col_name)
        
        column_defs.append(col_def)
    
    # 添加复合主键
    if primary_keys:
        column_defs.append(f"PRIMARY KEY ({','.join([f'`{pk}`' for pk in primary_keys])})")
    
    return f"CREATE TABLE `{table_name}` ({','.join(column_defs)})"


class DDLParseRequest(BaseModel):
    """DDL解析请求"""
    ddl_text: str
    schema_name: str = "default"


class SchemaParseItem(BaseModel):
    """Schema解析项"""
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
    """Schema解析列表响应"""
    items: List[SchemaParseItem]
    total: int
    message: Optional[str] = None


class SchemaCheckResponse(BaseModel):
    """Schema检查响应"""
    has_schema: bool
    schema_count: int
    table_count: int


def parse_ddl(ddl: str, schema_name: str, user_id: int, db: Session) -> List[dict]:
    """解析DDL语句并返回解析结果"""
    results = []
    
    table_name_match = re.search(r'CREATE TABLE\s+`?([^`\s(]+)`?', ddl, re.IGNORECASE)
    if not table_name_match:
        table_name_match = re.search(r'CREATE TABLE\s+(\w+)', ddl, re.IGNORECASE)
    table_name = table_name_match.group(1).strip('`') if table_name_match else ''
    
    if not table_name:
        return results
    
    table_comment_match = re.search(r"COMMENT\s*=?\s*['\"]([^'\"]+)['\"]", ddl, re.IGNORECASE)
    table_comment = table_comment_match.group(1) if table_comment_match else ''
    
    pk_match = re.search(r'PRIMARY KEY\s*\(([^)]+)\)', ddl, re.IGNORECASE)
    primary_keys = []
    if pk_match:
        pk_str = pk_match.group(1)
        primary_keys = [pk.strip().strip('`') for pk in pk_str.split(',')]
    
    table_struct_match = re.search(r'\(([\s\S]+)\)\s*(?:ENGINE|;|$)', ddl, re.IGNORECASE)
    if not table_struct_match:
        return results
    
    table_struct = table_struct_match.group(1)
    
    for line in table_struct.split('\n'):
        line = line.strip()
        if not line or re.match(r'^(PRIMARY|FOREIGN|KEY|UNIQUE|INDEX|CONSTRAINT)', line, re.IGNORECASE):
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
        comment_match = re.search(r"COMMENT\s+['\"]([^'\"]+)['\"]", rest, re.IGNORECASE)
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
    """解析DDL文本"""
    try:
        user_id = user['user_id']
        db = SqlSessionLocal()
        
        try:
            parsed_results = parse_ddl(request.ddl_text, request.schema_name, user_id, db)
            
            if not parsed_results:
                raise HTTPException(status_code=400, detail="无法解析DDL，请检查格式")
            
            # 保存到数据库（去重：已存在的跳过）
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
            
            # 创建临时数据库表并生成模拟数据
            table_name = parsed_results[0]['table_name']
            create_temp_table_and_mock_data(user_id, request.ddl_text, table_name, parsed_results)
            
            # 构建提示消息
            message = f"成功插入 {new_count} 条记录"
            if duplicate_count > 0:
                message += f"，跳过 {duplicate_count} 条重复记录"
            
            # 返回解析结果
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
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"DDL解析失败: {e}")
        raise HTTPException(status_code=500, detail=f"解析失败: {str(e)}")


@router.post("/schema/upload", response_model=SchemaParseListResponse)
async def upload_ddl_file(
    file: UploadFile = File(...),
    schema_name: str = Form("default"),
    user = Depends(get_current_user)
):
    """上传DDL文件并解析"""
    try:
        user_id = user['user_id']
        
        # 读取文件内容
        content = await file.read()
        ddl_text = content.decode('utf-8')
        
        db = SqlSessionLocal()
        
        try:
            parsed_results = parse_ddl(ddl_text, schema_name, user_id, db)
            
            if not parsed_results:
                raise HTTPException(status_code=400, detail="无法解析DDL文件，请检查格式")
            
            # 保存到数据库（去重：已存在的跳过）
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
            
            # 创建临时数据库表并生成模拟数据
            table_name = parsed_results[0]['table_name']
            create_temp_table_and_mock_data(user_id, ddl_text, table_name, parsed_results)
            
            # 构建提示消息
            message = f"成功插入 {new_count} 条记录"
            if duplicate_count > 0:
                message += f"，跳过 {duplicate_count} 条重复记录"
            
            # 返回解析结果
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
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"DDL文件上传解析失败: {e}")
        raise HTTPException(status_code=500, detail=f"解析失败: {str(e)}")


@router.get("/schema/list", response_model=SchemaParseListResponse)
async def get_schema_list(
    schema_name: Optional[str] = None,
    table_name: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    user = Depends(get_current_user)
):
    """获取用户的Schema解析列表"""
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
        logger.error(f"获取Schema列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")


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
                raise HTTPException(status_code=404, detail="Schema项不存在")
            
            item.sample_values = request.sample_values
            db.commit()
            
            return {"success": True, "message": "更新成功"}
        finally:
            db.close()
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新示例值失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新失败: {str(e)}")


@router.get("/schema/check", response_model=SchemaCheckResponse)
async def check_user_schema(user = Depends(get_current_user)):
    """检查用户是否有Schema"""
    try:
        user_id = user['user_id']
        db = SqlSessionLocal()
        
        try:
            schema_count = db.query(SchemaParse.schema_name).filter(
                SchemaParse.user_id == user_id
            ).distinct().count()
            
            # 获取不重复的表数量
            table_count = db.query(SchemaParse.table_name).filter(
                SchemaParse.user_id == user_id
            ).distinct().count()
            
            return SchemaCheckResponse(
                has_schema=schema_count > 0,
                schema_count=schema_count,
                table_count=table_count
            )
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"检查Schema失败: {e}")
        raise HTTPException(status_code=500, detail=f"检查失败: {str(e)}")


@router.delete("/schema/{schema_id}")
async def delete_schema_item(
    schema_id: int,
    user = Depends(get_current_user)
):
    """删除单个Schema解析项"""
    try:
        user_id = user['user_id']
        db = SqlSessionLocal()
        
        try:
            item = db.query(SchemaParse).filter(
                SchemaParse.id == schema_id,
                SchemaParse.user_id == user_id
            ).first()
            
            if not item:
                raise HTTPException(status_code=404, detail="Schema项不存在")
            
            db.delete(item)
            db.commit()
            
            return {"success": True, "message": "删除成功"}
        finally:
            db.close()
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除Schema失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")


@router.delete("/schema/table/{table_name}")
async def delete_schema_by_table(
    table_name: str,
    schema_name: Optional[str] = None,
    user = Depends(get_current_user)
):
    """删除指定表的所有Schema解析项"""
    try:
        user_id = user['user_id']
        db = SqlSessionLocal()
        
        try:
            query = db.query(SchemaParse).filter(
                SchemaParse.user_id == user_id,
                SchemaParse.table_name == table_name
            )
            
            if schema_name:
                query = query.filter(SchemaParse.schema_name == schema_name)
            
            count = query.count()
            query.delete()
            db.commit()
            
            return {"success": True, "message": f"已删除 {count} 条记录"}
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"删除Schema表失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")


@router.delete("/schema/schema/{schema_name}")
async def delete_schema_by_name(
    schema_name: str,
    user = Depends(get_current_user)
):
    """删除指定schema的所有解析项"""
    try:
        user_id = user['user_id']
        db = SqlSessionLocal()
        
        try:
            count = db.query(SchemaParse).filter(
                SchemaParse.user_id == user_id,
                SchemaParse.schema_name == schema_name
            ).delete()
            db.commit()
            
            return {"success": True, "message": f"已删除 {count} 条记录"}
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"删除Schema失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")


@router.get("/schema/export")
async def export_schema_csv(
    schema_name: Optional[str] = None,
    user = Depends(get_current_user)
):
    """导出Schema为CSV"""
    try:
        user_id = user['user_id']
        db = SqlSessionLocal()
        
        try:
            query = db.query(SchemaParse).filter(SchemaParse.user_id == user_id)
            
            if schema_name:
                query = query.filter(SchemaParse.schema_name == schema_name)
            
            items = query.order_by(SchemaParse.table_name, SchemaParse.column_name).all()
            
            if not items:
                raise HTTPException(status_code=404, detail="没有可导出的Schema")
            
            # 生成CSV
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(['schema_name', 'table_name', 'table_description', 
                           'column_name', 'column_type', 'column_description', 'column_key'])
            
            for item in items:
                writer.writerow([
                    item.schema_name,
                    item.table_name,
                    item.table_description or '',
                    item.column_name,
                    item.column_type or '',
                    item.column_description or '',
                    item.column_key or ''
                ])
            
            output.seek(0)
            
            return StreamingResponse(
                io.BytesIO(output.getvalue().encode('utf-8')),
                media_type='text/csv',
                headers={'Content-Disposition': f'attachment; filename=schema_{schema_name or "export"}.csv'}
            )
        finally:
            db.close()
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"导出Schema失败: {e}")
        raise HTTPException(status_code=500, detail=f"导出失败: {str(e)}")


@router.get("/schema/tables")
async def get_user_tables(
    schema_name: Optional[str] = None,
    user = Depends(get_current_user)
):
    """获取用户的表列表"""
    try:
        user_id = user['user_id']
        db = SqlSessionLocal()
        
        try:
            query = db.query(
                SchemaParse.table_name,
                SchemaParse.table_description
            ).filter(SchemaParse.user_id == user_id)
            
            if schema_name:
                query = query.filter(SchemaParse.schema_name == schema_name)
            
            tables = query.distinct().all()
            
            return {
                "tables": [
                    {"table_name": t.table_name, "table_description": t.table_description}
                    for t in tables
                ]
            }
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"获取表列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")


@router.get("/schema/schemas")
async def get_user_schemas(user = Depends(get_current_user)):
    """获取用户的schema名称列表"""
    try:
        user_id = user['user_id']
        db = SqlSessionLocal()
        
        try:
            schemas = db.query(SchemaParse.schema_name).filter(
                SchemaParse.user_id == user_id
            ).distinct().all()
            
            return {
                "schemas": [s.schema_name for s in schemas]
            }
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"获取Schema列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")
