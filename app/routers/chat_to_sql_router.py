# -*- coding: UTF-8 -*-
"""
Text to SQL 路由 - 智能数据分析
"""
import time
import os
import hashlib
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.security import HTTPBearer
from typing import List, Dict

from core.models import TextToSqlRequest, SqlValidationResponse, ChartDataResponse
from core.SQLGenerator import SqlGenerator
from core.DatabaseManager import DatabaseManager
from core.LLMClient import LLMClient
from app.logger import logger
from app.auth import get_current_user
from app.config import TEMP_DB_PATH
from app.routers.history_router import add_history, get_successful_queries
from app.routers.extra_router import get_extra_knowledge_for_llm, get_extra_knowledge_by_id
from models import SessionLocal, SqlSessionLocal
from models.schema_parse import SchemaParse


router = APIRouter()

sql_generator = SqlGenerator()
llm_client = LLMClient()

validation_cache = {}


def get_user_temp_db_path(user_id: int) -> str:
    """获取用户临时数据库路径"""
    return os.path.join(TEMP_DB_PATH, f'user_{user_id}_temp.db')


security = HTTPBearer(auto_error=False)


def check_user_schema(user_id: int) -> tuple:
    """检查用户是否有schema，返回 (has_schema, schema_info)"""
    db = SqlSessionLocal()
    try:
        schema_count = db.query(SchemaParse).filter(SchemaParse.user_id == user_id).count()
        table_count = db.query(SchemaParse.table_name).filter(
            SchemaParse.user_id == user_id
        ).distinct().count()
        return schema_count > 0, {"schema_count": schema_count, "table_count": table_count}
    finally:
        db.close()


def get_user_schema_csv(user_id: int) -> str:
    """获取用户的schema并生成CSV格式的内容"""
    db = SqlSessionLocal()
    try:
        items = db.query(SchemaParse).filter(
            SchemaParse.user_id == user_id
        ).order_by(SchemaParse.table_name, SchemaParse.column_name).all()
        
        if not items:
            return ""
        
        lines = ['db_id,db_type,table_name,column_name,column_types,column_descriptions,table_comment,primary_key,foreign_key,is_nullable,default_value']
        for item in items:
            lines.append(','.join([
                item.schema_name,
                'mysql',
                item.table_name,
                item.column_name,
                item.column_type or '',
                item.column_description or '',
                item.table_description or '',
                item.column_key or '',
                '',
                'YES' if item.is_nullable else 'NO',
                item.default_value or ''
            ]))
        
        return '\n'.join(lines)
    finally:
        db.close()


def get_sample_values(user_id: int) -> Dict[str, List[str]]:
    """获取用户的字段示例值"""
    db = SqlSessionLocal()
    try:
        items = db.query(SchemaParse).filter(
            SchemaParse.user_id == user_id,
            SchemaParse.sample_values.isnot(None)
        ).all()
        
        sample_values = {}
        for item in items:
            if item.sample_values:
                key = f"{item.table_name}.{item.column_name}"
                values = [v.strip() for v in item.sample_values.split(',') if v.strip()]
                if values:
                    sample_values[key] = values
        
        return sample_values
    finally:
        db.close()


def get_table_relations(user_id: int) -> List[Dict[str, str]]:
    """获取表间关系（基于外键信息）"""
    db = SqlSessionLocal()
    try:
        items = db.query(SchemaParse).filter(
            SchemaParse.user_id == user_id,
            SchemaParse.column_key == 'MUL'
        ).all()
        
        relations = []
        tables = db.query(SchemaParse.table_name).filter(
            SchemaParse.user_id == user_id
        ).distinct().all()
        table_names = [t[0] for t in tables]
        
        for item in items:
            col_name_lower = item.column_name.lower()
            for table_name in table_names:
                if table_name != item.table_name:
                    if col_name_lower.endswith('_id') or col_name_lower.endswith('_code'):
                        relations.append({
                            'from_table': item.table_name,
                            'from_column': item.column_name,
                            'to_table': table_name,
                            'to_column': item.column_name
                        })
        
        return relations[:20]
    finally:
        db.close()


@router.get("/check-schema")
async def check_schema_status(user = Depends(get_current_user)):
    """检查用户是否有schema"""
    user_id = user['user_id']
    has_schema, schema_info = check_user_schema(user_id)
    return {
        "has_schema": has_schema,
        "schema_count": schema_info["schema_count"],
        "table_count": schema_info["table_count"]
    }


@router.post("/validate")
async def validate_text_to_sql(
    request: TextToSqlRequest,
    user = Depends(get_current_user)
):
    """验证文本转SQL的功能"""
    try:
        user_id = user['user_id']
        
        has_schema, schema_info = check_user_schema(user_id)
        if not has_schema:
            raise HTTPException(
                status_code=400, 
                detail="您还没有维护Schema，请先在【Schema管理】中上传DDL解析表结构"
            )

        cache_key = hashlib.md5(
            f"{user_id}_{request.query}_{request.max_results}_{request.knowledge_id}".encode()).hexdigest()

        if cache_key in validation_cache:
            cached_result, timestamp = validation_cache[cache_key]
            if time.time() - timestamp < 300:
                logger.info(f"使用缓存的验证结果: {request.query[:50]}...")
                return cached_result

        schema_csv = get_user_schema_csv(user_id)
        if not schema_csv:
            raise HTTPException(
                status_code=400,
                detail="获取Schema失败，请检查您的Schema配置"
            )
        
        sample_values = get_sample_values(user_id)
        table_relations = get_table_relations(user_id)
        history_queries = get_successful_queries(user_id)
        
        domain_knowledge = ""
        if request.knowledge_id:
            extra = get_extra_knowledge_by_id(user_id, request.knowledge_id)
            if extra:
                if extra.get('domain_knowledge_section'):
                    domain_knowledge = extra['domain_knowledge_section']
                if extra.get('sample_values_section'):
                    domain_knowledge += "\n【补充字段示例值】\n" + extra['sample_values_section']
                if extra.get('table_relations_section'):
                    domain_knowledge += "\n【补充表间关系】\n" + extra['table_relations_section']
        else:
            extra = get_extra_knowledge_for_llm(user_id)
            if extra:
                if extra.get('domain_knowledge_section'):
                    domain_knowledge = extra['domain_knowledge_section']
                if extra.get('sample_values_section'):
                    domain_knowledge += "\n【补充字段示例值】\n" + extra['sample_values_section']
                if extra.get('table_relations_section'):
                    domain_knowledge += "\n【补充表间关系】\n" + extra['table_relations_section']
        
        prompt = sql_generator.generate_sql_prompt(
            query=request.query,
            schema_csv=schema_csv,
            sample_values=sample_values,
            table_relations=table_relations,
            history_queries=history_queries,
            domain_knowledge=domain_knowledge
        )
        
        logger.info(f"生成SQL提示: {prompt[:200]}...")

        generated_sql = llm_client.call_real_llm_api(prompt)
        logger.info(f"大模型生成的SQL: {generated_sql}")

        is_valid, error_msg, columns = sql_generator.validate_sql(generated_sql)

        response = SqlValidationResponse(
            is_valid=is_valid,
            sql_query=generated_sql,
            error_message=error_msg if not is_valid else None,
            columns=columns if is_valid else None
        )

        validation_cache[cache_key] = (response, time.time())

        add_history(
            query=request.query,
            sql_query=generated_sql,
            is_valid=is_valid,
            error_message=error_msg if not is_valid else None,
            user_id=user_id
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"文本转SQL验证失败: {e}")
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")


@router.post("/execute", response_model=ChartDataResponse)
async def execute_text_to_sql(
    request: TextToSqlRequest,
    user = Depends(get_current_user)
):
    """执行文本转SQL并返回图表数据"""
    try:
        user_id = user['user_id']
        
        has_schema, schema_info = check_user_schema(user_id)
        if not has_schema:
            raise HTTPException(
                status_code=400,
                detail="您还没有维护Schema，请先在【Schema管理】中上传DDL解析表结构"
            )

        cache_key = hashlib.md5(
            f"{user_id}_{request.query}_{request.max_results}_{request.knowledge_id}".encode()).hexdigest()
        validation_response = None

        if cache_key in validation_cache:
            cached_result, timestamp = validation_cache[cache_key]
            if time.time() - timestamp < 120:
                logger.info(f"使用缓存的验证结果进行执行: {request.query[:50]}...")
                validation_response = cached_result

        if not validation_response:
            validation_response = await validate_text_to_sql(request, user)

        if not validation_response.is_valid:
            raise HTTPException(
                status_code=400, detail=validation_response.error_message)

        generated_sql = validation_response.sql_query

        temp_db_path = get_user_temp_db_path(user_id)
        if not os.path.exists(temp_db_path):
            raise HTTPException(
                status_code=400,
                detail="临时数据库不存在，请重新上传DDL解析表结构"
            )
        
        db_manager = DatabaseManager(temp_db_path)
        max_results = min(request.max_results or 100, 1000)
        query_results = db_manager.execute_query(generated_sql, max_results)

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
        logger.error(f"文本转SQL执行失败: {e}")
        raise HTTPException(status_code=500, detail=f"执行失败: {str(e)}")
