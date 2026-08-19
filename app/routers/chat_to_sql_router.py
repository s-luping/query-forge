"""
QueryForge SQL生成路由（单次问答模式）

遥测：LLM 调用记录写入遥测库 services/llm/telemetry（purpose='single'）。
"""
import hashlib
import time
from typing import Optional, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.auth import CurrentUser
from app.logger import logger
from app.permissions import is_schema_visible
from app.routers.knowledge_router import get_knowledge_safe
from app.security.crypto import decrypt_secret
from core.llm import LLMClient
from core.generation.sql_generator import SqlGenerator
from core.generation.pipeline import SQLPipeline
from models.llm import LLMConfig
from services.llm import telemetry
from curd.base import session_scope


class TextToSqlRequest(BaseModel):
    """文本转SQL请求模型"""
    query: str
    table_names: Optional[List[str]] = None
    knowledge_id: Optional[int] = None
    db_type: Optional[str] = "sqlite"
    schema_name: Optional[str] = None
    llm_config_id: Optional[int] = None


class SqlValidationResponse(BaseModel):
    """SQL验证响应模型"""
    is_valid: bool
    sql_query: str
    error_message: Optional[str] = None
    columns: Optional[List[str]] = None


router = APIRouter()

sql_generator = SqlGenerator()

validation_cache = {}


def get_user_llm_config(user_id: int, config_id: Optional[int] = None) -> Optional[dict]:
    """获取用户的LLM配置（自己的 + 公共配置，api_key 解密）"""
    with session_scope() as db:
        if config_id:
            config = db.query(LLMConfig).filter(
                LLMConfig.id == config_id,
                LLMConfig.is_active == True,
                (LLMConfig.is_public == True) | (LLMConfig.user_id == user_id)
            ).first()
        else:
            config = db.query(LLMConfig).filter(
                LLMConfig.user_id == user_id,
                LLMConfig.is_default == True,
                LLMConfig.is_active == True
            ).first()
    
        if config:
            return {
                'id': config.id,
                'provider': config.provider,
                'model': config.model,
                'api_key': decrypt_secret(config.api_key),
                'base_url': config.base_url,
                'max_tokens': config.max_tokens or 8000,
                'temperature': config.temperature or 0.7,
                'timeout': config.timeout or 300
            }
        return None
@router.post("/generate_sql")
def generate_sql(
    request: TextToSqlRequest,
    user: CurrentUser,
):
    """生成SQL - 统一使用字段级索引+按表聚合方案
    认证：CurrentUser 类型化依赖（未登录 401），Bearer 头或 HttpOnly cookie 均可。
    """
    user_id = user['user_id']
    start_time = time.time()

    # 库级可见性二次校验（防绕过前端下拉直接请求无权限库）
    if not is_schema_visible(user, request.schema_name):
        raise HTTPException(status_code=403, detail="无权访问该数据库")

    try:
        cache_key = hashlib.md5(
            f"{user_id}_{request.query}_{request.knowledge_id}_{request.schema_name}".encode()).hexdigest()

        if cache_key in validation_cache:
            cached_sql, timestamp = validation_cache[cache_key]
            if time.time() - timestamp < 300:
                logger.info(f"使用缓存的生成结果: {request.query[:50]}...")
                return cached_sql

        llm_config = get_user_llm_config(user_id, request.llm_config_id)

        if llm_config:
            llm_client = LLMClient(
                provider=llm_config['provider'],
                api_key=llm_config['api_key'],
                model=llm_config['model'],
                base_url=llm_config.get('base_url'),
                max_tokens=llm_config['max_tokens'],
                timeout=llm_config['timeout'],
                temperature=llm_config['temperature']
            )
            logger.info(f"使用用户配置的模型: {llm_config['provider']} - {llm_config['model']}")
        else:
            llm_client = LLMClient()
            logger.info("使用默认模型配置")

        pipeline = SQLPipeline(
            user_id=user_id,
            llm_client=llm_client,
            sql_generator=sql_generator,
            user=user
        )

        knowledge = get_knowledge_safe(user_id, request.knowledge_id)
        knowledge_content = knowledge.get("content", "")
        logger.info(f"知识库: {'已加载' if knowledge_content else '无'}")

        pipeline_result = pipeline.run_pipeline(
            query=request.query,
            schema_name=request.schema_name,
            knowledge_content=knowledge_content.strip() if knowledge_content else "",
            history_queries=[],
            db_type=request.db_type
        )

        generated_sql = pipeline_result['sql']
        is_valid = pipeline_result['is_valid']
        error_msg = pipeline_result['error_message']
        columns = pipeline_result['columns']
        used_vector = pipeline_result.get('used_vector_search', False)
        prompt_tokens = pipeline_result.get('prompt_tokens', 0)
        completion_tokens = pipeline_result.get('completion_tokens', 0)
        total_tokens = pipeline_result.get('total_tokens', 0)

        duration_ms = (time.time() - start_time) * 1000

        logger.info(f"生成SQL: {generated_sql}")
        logger.info(f"是否使用向量: {used_vector}, 耗时: {duration_ms:.2f}ms")

        conditions = f"schema_name={request.schema_name}, knowledge_id={request.knowledge_id}, db_type={request.db_type}, vector_search={used_vector}"

        model_name = llm_client.model if hasattr(llm_client, 'model') else 'unknown'

        telemetry.record_call(
            user_id=user_id,
            provider=llm_client.provider,
            question=request.query,
            model=model_name,
            conditions=conditions,
            result=generated_sql,
            duration_ms=duration_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            status='success' if is_valid else 'warning',
            error_message=error_msg if not is_valid else None,
            config_id=llm_config['id'] if llm_config else None,
            purpose='single',
            system_prompt=pipeline_result.get('prompt', ''),
        )

        response = SqlValidationResponse(
            is_valid=is_valid,
            sql_query=generated_sql,
            error_message=error_msg if not is_valid else None,
            columns=columns if is_valid else None
        )

        validation_cache[cache_key] = (response, time.time())

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"文本转SQL验证失败: {e}")
        telemetry.record_call(
            user_id=user_id,
            provider='unknown',
            question=request.query,
            model='unknown',
            conditions=f"schema_name={request.schema_name}, knowledge_id={request.knowledge_id}",
            result='',
            duration_ms=(time.time() - start_time) * 1000,
            status='error',
            error_message=str(e),
            purpose='single',
        )
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")
