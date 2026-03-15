# -*- coding: UTF-8 -*-
"""
表数据管理路由 - 数据查看、编辑和 SQL 查询
"""
import sqlite3
import os
import pandas as pd
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import List, Dict, Any, Optional

from app.logger import logger
from app.auth import get_current_user
from app.config import TEMP_DB_PATH
from core.models import TextToSqlRequest, SqlValidationResponse, ChartDataResponse
from core.DatabaseManager import DatabaseManager
from models import SchemaSessionLocal, HistorySessionLocal
from models.schema import Schema
from models.historical_sql import HistoricalSQL
from app.routers.history_router import add_history, get_successful_queries


router = APIRouter()


def get_user_temp_db_path(user_id: int) -> str:
    """获取用户临时数据库路径"""
    return os.path.join(TEMP_DB_PATH, f'user_{user_id}_temp.db')


def create_temp_table(user_id: int, ddl_text: str, table_name: str, columns: List[dict]):
    """创建临时数据库表"""
    temp_db_path = get_user_temp_db_path(user_id)
    
    if not os.path.exists(TEMP_DB_PATH):
        os.makedirs(TEMP_DB_PATH)
        logger.info(f"创建临时数据库目录：{TEMP_DB_PATH}")
    
    conn = sqlite3.connect(temp_db_path)
    cursor = conn.cursor()
    
    try:
        cursor.execute(f"DROP TABLE IF EXISTS `{table_name}`")
        
        create_sql = convert_mysql_to_sqlite(ddl_text, table_name, columns)
        logger.info(f"创建临时表 SQL: {create_sql}")
        cursor.execute(create_sql)
        
        conn.commit()
        logger.info(f"临时数据库表创建成功：{temp_db_path}, 表：{table_name}")
        
    except Exception as e:
        logger.error(f"创建临时表失败：{e}")
        conn.rollback()
        raise
    finally:
        conn.close()


def convert_mysql_to_sqlite(ddl_text: str, table_name: str, columns: List[dict]) -> str:
    """将 MySQL DDL 转换为 SQLite 兼容的 DDL"""
    column_defs = []
    primary_keys = []
    
    for col in columns:
        col_name = col.get('column_name')
        col_type = col.get('column_type', 'TEXT')
        col_key = col.get('column_key')
        
        col_type_lower = col_type.lower()
        if 'int' in col_type_lower:
            sqlite_type = 'INTEGER'
        elif 'varchar' in col_type_lower or 'char' in col_type_lower or 'text' in col_type_lower:
            sqlite_type = 'TEXT'
        elif 'float' in col_type_lower or 'double' in col_type_lower or 'decimal' in col_type_lower:
            sqlite_type = 'REAL'
        elif 'date' in col_type_lower or 'time' in col_type_lower:
            sqlite_type = 'TEXT'
        else:
            sqlite_type = 'TEXT'
        
        col_def = f"`{col_name}` {sqlite_type}"
        
        if col_key == 'PRI' and 'int' in col_type_lower:
            col_def += ' PRIMARY KEY AUTOINCREMENT'
        else:
            if col_key == 'PRI':
                primary_keys.append(col_name)
        
        column_defs.append(col_def)
    
    if primary_keys:
        column_defs.append(f"PRIMARY KEY ({','.join([f'`{pk}`' for pk in primary_keys])})")
    
    return f"CREATE TABLE `{table_name}` ({','.join(column_defs)})"


class TableDataUpdateRequest(BaseModel):
    """表数据更新请求"""
    rows: List[Dict[str, Any]]


class TableDataResponse(BaseModel):
    """表数据响应"""
    columns: List[str]
    data: List[List[Any]]
    total: int


class SqlExecuteRequest(BaseModel):
    """SQL 执行请求"""
    query: str
    db_type: str = "sqlite"
    limit: int = 100


class SqlExecuteResponse(BaseModel):
    """SQL 执行响应"""
    columns: List[str]
    data: List[List[Any]]
    row_count: int


class TableExistsResponse(BaseModel):
    """表存在响应"""
    exists: bool
    table_name: str


class CreateTableRequest(BaseModel):
    """建表请求"""
    schema_name: str
    table_name: str


class CreateTableResponse(BaseModel):
    """建表响应"""
    success: bool
    message: str
    table_name: str


@router.post("/create-table", response_model=CreateTableResponse)
async def create_table_from_schema(
    request: CreateTableRequest,
    user = Depends(get_current_user)
):
    """根据解析的 Schema 创建临时表"""
    try:
        user_id = user['user_id']
        db = SchemaSessionLocal()
        
        try:
            schema_name = request.schema_name
            table_name = request.table_name
            
            if not schema_name or not table_name:
                raise HTTPException(status_code=400, detail="缺少 schema_name 或 table_name")
            
            columns = db.query(Schema).filter(
                Schema.user_id == user_id,
                Schema.schema_name == schema_name,
                Schema.table_name == table_name
            ).all()
            
            if not columns:
                raise HTTPException(status_code=404, detail=f"表 {table_name} 的字段信息不存在，请先在 Schema 管理中解析 DDL")
            
            columns_dict = []
            for col in columns:
                columns_dict.append({
                    'column_name': col.column_name,
                    'column_type': col.column_type,
                    'column_key': col.column_key,
                    'is_nullable': col.is_nullable,
                    'default_value': col.default_value
                })
            
            ddl_text = f"CREATE TABLE `{table_name}` (placeholder)"
            create_temp_table(user_id, ddl_text, table_name, columns_dict)
            
            return CreateTableResponse(
                success=True,
                message=f"表 {table_name} 创建成功",
                table_name=table_name
            )
        finally:
            db.close()
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建表失败：{e}")
        raise HTTPException(status_code=500, detail=f"创建失败：{str(e)}")


@router.get("/{table_name}/exists", response_model=TableExistsResponse)
async def check_table_exists(
    table_name: str,
    user = Depends(get_current_user)
):
    """检查表是否存在"""
    try:
        user_id = user['user_id']
        db_path = get_user_temp_db_path(user_id)
        
        if not os.path.exists(db_path):
            return TableExistsResponse(exists=False, table_name=table_name)
        
        conn = sqlite3.connect(db_path)
        
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
            exists = cursor.fetchone() is not None
            
            return TableExistsResponse(exists=exists, table_name=table_name)
        finally:
            conn.close()
            
    except Exception as e:
        logger.error(f"检查表存在失败：{e}")
        return TableExistsResponse(exists=False, table_name=table_name)


@router.get("/{table_name}/preview", response_model=TableDataResponse)
async def preview_table_data(
    table_name: str,
    limit: int = 10,
    user = Depends(get_current_user)
):
    """预览表数据（最多返回 10 行）"""
    try:
        user_id = user['user_id']
        db_path = get_user_temp_db_path(user_id)
        
        limit = min(limit, 10)
        
        if not os.path.exists(db_path):
            raise HTTPException(status_code=404, detail="临时数据库不存在，请先创建表")
        
        conn = sqlite3.connect(db_path)
        
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail=f"表 {table_name} 不存在")
            
            query = f"SELECT * FROM `{table_name}` LIMIT ?"
            df = pd.read_sql_query(query, conn, params=[limit])
            
            columns = df.columns.tolist()
            data = df.values.tolist()
            
            cursor.execute(f"SELECT COUNT(*) FROM `{table_name}`")
            total = cursor.fetchone()[0]
            
            return TableDataResponse(
                columns=columns,
                data=data,
                total=total
            )
        finally:
            conn.close()
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"预览表数据失败：{e}")
        raise HTTPException(status_code=500, detail=f"查询失败：{str(e)}")


@router.post("/{table_name}/update")
async def update_table_data(
    table_name: str,
    request: TableDataUpdateRequest,
    user = Depends(get_current_user)
):
    """更新或插入表数据（最多插入 10 行）"""
    try:
        user_id = user['user_id']
        db_path = get_user_temp_db_path(user_id)
        
        if not os.path.exists(db_path):
            raise HTTPException(status_code=404, detail="临时数据库不存在")
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail=f"表 {table_name} 不存在")
            
            cursor.execute(f"SELECT COUNT(*) FROM `{table_name}`")
            current_count = cursor.fetchone()[0]
            
            new_rows_count = sum(1 for row in request.rows if row.get('__is_new__'))
            
            if current_count + new_rows_count > 10:
                raise HTTPException(status_code=400, detail=f"数据行数超过限制，当前已有 {current_count} 行，最多允许 10 行")
            
            cursor.execute(f"PRAGMA table_info(`{table_name}`)")
            columns_info = cursor.fetchall()
            column_names = [col[1] for col in columns_info]
            
            pk_columns = [col[1] for col in columns_info if col[5] > 0]
            
            updated_count = 0
            inserted_count = 0
            
            for row_data in request.rows:
                if row_data.get('__is_new__'):
                    insert_data = {k: v for k, v in row_data.items() if not k.startswith('__')}
                    
                    cols = list(insert_data.keys())
                    placeholders = ', '.join(['?' for _ in cols])
                    col_names = ', '.join([f"`{col}`" for col in cols])
                    values = [insert_data.get(col) for col in cols]
                    
                    insert_sql = f"INSERT INTO `{table_name}` ({col_names}) VALUES ({placeholders})"
                    cursor.execute(insert_sql, values)
                    inserted_count += 1
                else:
                    if pk_columns:
                        where_conditions = []
                        where_values = []
                        for pk_col in pk_columns:
                            if pk_col in row_data:
                                where_conditions.append(f"`{pk_col}` = ?")
                                where_values.append(row_data[pk_col])
                        where_clause = " AND ".join(where_conditions)
                    else:
                        first_col = column_names[0]
                        where_clause = f"`{first_col}` = ?"
                        where_values = [row_data.get(first_col)]
                    
                    update_columns = [col for col in column_names if col not in pk_columns]
                    if update_columns:
                        set_clause = ", ".join([f"`{col}` = ?" for col in update_columns])
                        update_values = [row_data.get(col) for col in update_columns] + where_values
                        
                        update_sql = f"UPDATE `{table_name}` SET {set_clause} WHERE {where_clause}"
                        cursor.execute(update_sql, update_values)
                        updated_count += 1
            
            conn.commit()
            
            message = []
            if updated_count > 0:
                message.append(f"更新 {updated_count} 条记录")
            if inserted_count > 0:
                message.append(f"插入 {inserted_count} 条记录")
            
            return {"success": True, "message": "，".join(message) if message else "操作成功"}
            
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新表数据失败：{e}")
        raise HTTPException(status_code=500, detail=f"更新失败：{str(e)}")


@router.post("/chat-to-sql/execute", response_model=SqlExecuteResponse)
async def execute_sql(
    request: SqlExecuteRequest,
    user = Depends(get_current_user)
):
    """执行 SQL 查询"""
    try:
        user_id = user['user_id']
        db_path = get_user_temp_db_path(user_id)
        
        if not os.path.exists(db_path):
            raise HTTPException(status_code=404, detail="临时数据库不存在，请先创建表")
        
        conn = sqlite3.connect(db_path)
        
        try:
            # 安全检查：只允许 SELECT 语句
            sql_upper = request.query.strip().upper()
            if not sql_upper.startswith('SELECT'):
                raise HTTPException(status_code=400, detail="只允许执行 SELECT 查询语句")
            
            # 添加 LIMIT 限制
            query = request.query
            if 'LIMIT' not in sql_upper:
                query = f"{request.query} LIMIT {request.limit}"
            
            # 执行查询
            df = pd.read_sql_query(query, conn)
            
            # 转换为列表格式
            columns = df.columns.tolist()
            data = df.values.tolist()
            
            return SqlExecuteResponse(
                columns=columns,
                data=data,
                row_count=len(data)
            )
        finally:
            conn.close()
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"执行 SQL 查询失败：{e}")
        raise HTTPException(status_code=500, detail=f"查询失败：{str(e)}")


@router.get("/chat-to-sql/history")
async def get_query_history(
    limit: int = 20,
    offset: int = 0,
    user = Depends(get_current_user)
):
    """获取查询历史"""
    try:
        user_id = user['user_id']
        
        items = get_successful_queries(user_id, limit)
        
        return {
            "items": items,
            "total": len(items),
            "limit": limit,
            "offset": offset
        }
            
    except Exception as e:
        logger.error(f"获取查询历史失败：{e}")
        raise HTTPException(status_code=500, detail=f"获取失败：{str(e)}")


@router.post("/chat-to-sql/history")
async def add_query_history(
    query: str,
    sql: str,
    result_summary: str = "",
    rating: Optional[int] = None,
    user = Depends(get_current_user)
):
    """添加查询历史"""
    try:
        user_id = user['user_id']
        
        from app.routers.history_router import add_history
        
        add_history(
            user_id=user_id,
            query=query,
            sql=sql,
            result_summary=result_summary,
            rating=rating,
            status='success'
        )
        
        return {"success": True, "message": "历史记录已保存"}
        
    except Exception as e:
        logger.error(f"添加查询历史失败：{e}")
        raise HTTPException(status_code=500, detail=f"保存失败：{str(e)}")

@router.post("/execute_sql", response_model=ChartDataResponse)
async def execute_sql_with_sqlite(
    request: Request,
    user = Depends(get_current_user)
):
    """执行历史SQL查询并返回结果"""
    try:
        data = await request.json()
        history_id = data.get('history_id')
        
        if not history_id:
            raise HTTPException(status_code=400, detail="history_id 不能为空")
        
        user_id = user['user_id']

        db = HistorySessionLocal()
        try:
            sql_history = db.query(HistoricalSQL).filter(
                HistoricalSQL.id == history_id,
                HistoricalSQL.user_id == str(user_id)
            ).first()
            if not sql_history:
                raise HTTPException(status_code=404, detail="历史记录不存在或不属于该用户")

            generated_sql = sql_history.sql_query
        finally:
            db.close()

        temp_db_path = get_user_temp_db_path(user_id)
        if not os.path.exists(temp_db_path):
            raise HTTPException(
                status_code=400,
                detail="临时数据库不存在，请先在Schema管理中建表"
            )
        
        db_manager = DatabaseManager(temp_db_path)
        query_results = db_manager.execute_query(generated_sql, 100)

        return ChartDataResponse(
            sql_query=generated_sql,
            data=query_results,
            chart_type='table',
            chart_config={},
            total_rows=len(query_results),
            possible_chart_types=['table']
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"SQL执行失败: {e}")
        raise HTTPException(status_code=500, detail=f"执行失败: {str(e)}")