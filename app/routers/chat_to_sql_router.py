# -*- coding: UTF-8 -*-
"""
QueryForge SQL生成路由
"""
import time
import os
import hashlib
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.security import HTTPBearer
from typing import List, Dict, Optional

from core.models import TextToSqlRequest, SqlValidationResponse, ChartDataResponse
from core.SQLGenerator import SqlGenerator
from core.DatabaseManager import DatabaseManager
from core.LLMClient import LLMClient
from app.logger import logger
from app.auth import get_current_user
from app.config import TEMP_DB_PATH
from app.routers.history_router import add_history, get_successful_queries
from app.routers.extra_router import get_extra_knowledge_by_id
from models import SchemaSessionLocal, LLMSessionLocal, AppSessionLocal
from models.schema import Schema
from models.llm_log import LLMLog
from models.llm_config import LLMConfig


router = APIRouter()

sql_generator = SqlGenerator()

validation_cache = {}



security = HTTPBearer(auto_error=False)


def get_user_llm_config(user_id: int, config_id: Optional[int] = None) -> Optional[dict]:
    """获取用户的LLM配置"""
    db = AppSessionLocal()
    try:
        if config_id:
            config = db.query(LLMConfig).filter(
                LLMConfig.id == config_id,
                LLMConfig.user_id == user_id,
                LLMConfig.is_active == True
            ).first()
        else:
            config = db.query(LLMConfig).filter(
                LLMConfig.user_id == user_id,
                LLMConfig.is_default == True,
                LLMConfig.is_active == True
            ).first()
        
        if config:
            return {
                'provider': config.provider,
                'model': config.model,
                'api_key': config.api_key,
                'base_url': config.base_url,
                'max_tokens': config.max_tokens or 8000,
                'temperature': config.temperature or 0.7,
                'timeout': config.timeout or 300
            }
        return None
    finally:
        db.close()


def save_llm_log(user_id: int, question: str, model: str, conditions: str, 
                 result: str, duration_ms: float, prompt_tokens: int, 
                 completion_tokens: int, total_tokens: int, status: str = 'success',
                 error_message: str = None):
    """保存LLM调用记录"""
    db = LLMSessionLocal()
    try:
        log = LLMLog(
            user_id=user_id,
            question=question,
            model=model,
            conditions=conditions,
            result=result,
            duration_ms=duration_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            status=status,
            error_message=error_message
        )
        db.add(log)
        db.commit()
        logger.info(f"LLM调用记录已保存: user_id={user_id}, model={model}")
    except Exception as e:
        logger.error(f"保存LLM调用记录失败: {e}")
        db.rollback()
    finally:
        db.close()



def get_user_schema_csv(user_id: int, schema_name: str = None) -> str:
    """获取用户的模式并生成CSV格式的内容"""
    db = SchemaSessionLocal()
    try:
        query = db.query(Schema)\
        .filter(Schema.user_id == user_id, Schema.schema_name == schema_name)
        
        items = query.order_by(Schema.table_name, Schema.column_name).all()
        
        if not items:
            return ""
        
        lines = ['schema_name,table_name,column_name,column_type,column_description,table_comment,primary_key,foreign_key,is_nullable,default_value']
        for item in items:
            lines.append(','.join([
                item.schema_name,
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



@router.post("/generate_sql")
async def generate_sql(
    request: TextToSqlRequest,
    user = Depends(get_current_user)
):
    """生成SQL"""
    user_id = user['user_id']
    try:
        cache_key = hashlib.md5(
            f"{user_id}_{request.query}_{request.knowledge_id}_{request.schema_name}".encode()).hexdigest()

        if cache_key in validation_cache:
            cached_sql, timestamp = validation_cache[cache_key]
            if time.time() - timestamp < 300:
                logger.info(f"使用缓存的生成结果: {request.query[:50]}...")
                return cached_sql

        schema_csv = get_user_schema_csv(user_id, request.schema_name)
        if not schema_csv:
            raise HTTPException(
                status_code=400,
                detail="获取Schema失败，请检查您的Schema配置"
            )
        
        sample_values = ""
        table_relations = ""
        domain_knowledge = ""
        
        if request.knowledge_id:
            knowledge = get_extra_knowledge_by_id(user_id, request.knowledge_id)
            if knowledge:
                sample_values = knowledge.get("sample_values_section", "")
                table_relations = knowledge.get("table_relations_section", "")
                domain_knowledge = knowledge.get("domain_knowledge_section", "")
        
        history_queries = get_successful_queries(user_id)
        
        prompt = sql_generator.generate_sql_prompt(
            query=request.query,
            schema_csv=schema_csv,
            sample_values=sample_values,
            table_relations=table_relations,
            history_queries=history_queries,
            domain_knowledge=domain_knowledge,
            db_type=request.db_type
        )
        
        logger.info(f"生成SQL提示: {prompt[:200]}...")

        llm_config = get_user_llm_config(user_id, request.llm_config_id)
        
        if llm_config:
            llm_client = LLMClient(
                provider=llm_config['provider'],
                api_key=llm_config['api_key'],
                model=llm_config['model'],
                max_tokens=llm_config['max_tokens'],
                timeout=llm_config['timeout'],
                temperature=llm_config['temperature']
            )
            if llm_config['base_url']:
                llm_client.base_url = llm_config['base_url']
            logger.info(f"使用用户配置的模型: {llm_config['provider']} - {llm_config['model']}")
        else:
            llm_client = LLMClient()
            logger.info("使用默认模型配置")

        llm_result = llm_client.call_llm_with_details(prompt)
        generated_sql = llm_result['sql']
        logger.info(f"大模型生成的SQL: {generated_sql}")

        is_valid, error_msg, columns = sql_generator.validate_sql(generated_sql)

        conditions = f"schema_name={request.schema_name}, knowledge_id={request.knowledge_id}, db_type={request.db_type}"
        save_llm_log(
            user_id=user_id,
            question=request.query,
            model=llm_result['model'],
            conditions=conditions,
            result=generated_sql,
            duration_ms=llm_result['duration_ms'],
            prompt_tokens=llm_result['prompt_tokens'],
            completion_tokens=llm_result['completion_tokens'],
            total_tokens=llm_result['total_tokens'],
            status='success' if is_valid else 'warning',
            error_message=error_msg if not is_valid else None
        )

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
            user_id=user_id,
            schema_name=request.schema_name,
            knowledge_id=request.knowledge_id
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"文本转SQL验证失败: {e}")
        save_llm_log(
            user_id=user_id,
            question=request.query,
            model='unknown',
            conditions=f"schema_name={request.schema_name}, knowledge_id={request.knowledge_id}",
            result='',
            duration_ms=0,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            status='error',
            error_message=str(e)
        )
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")



