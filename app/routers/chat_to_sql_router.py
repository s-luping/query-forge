"""
QueryForge SQL生成路由
"""
import hashlib
import time
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer
from pydantic import BaseModel

from app.auth import get_current_user
from app.logger import logger
from app.routers.extra_router import get_extra_knowledge_safe
from core.LLMClient import LLMClient
from core.SQLGenerator import SqlGenerator
from core.SQLPipeline import SQLPipeline
from models import AppSessionLocal, LLMSessionLocal
from models.llm import LLMConfig, LLMLog


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

security = HTTPBearer(auto_error=False)


def get_user_llm_config(user_id: int, config_id: Optional[int] = None) -> Optional[dict]:
    """获取用户的LLM配置（自己的 + 公共配置）"""
    db = AppSessionLocal()
    try:
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


def save_llm_log(user_id: int, provider: str, question: str, model: str, conditions: str,
                 result: str, duration_ms: float, prompt_tokens: int,
                 completion_tokens: int, total_tokens: int, status: str = 'success',
                 error_message: str = None):
    """保存LLM调用记录"""
    db = LLMSessionLocal()
    try:
        log = LLMLog(
            user_id=user_id,
            provider=provider,
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


@router.post("/generate_sql")
def generate_sql(
    request: TextToSqlRequest,
    user=Depends(get_current_user)
):
    """生成SQL - 统一使用字段级索引+按表聚合方案
    
    必要依赖：
        - user_id: 用户ID
        - llm_client: LLM客户端（需要有可用配置或默认配置）
        - query: 用户问题
        
    可选依赖（缺失不影响流程）：
        - schema_name: 模式名（不指定则查询所有）
        - knowledge_id: 补充知识ID
        - llm_config_id: LLM配置ID
        - history_queries: 历史成功查询
    """
    user_id = user['user_id']
    start_time = time.time()

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
            sql_generator=sql_generator
        )

        knowledge = get_extra_knowledge_safe(user_id, request.knowledge_id)
        extra_knowledge = knowledge.get("extra_knowledge", "")
        logger.info(f"补充知识: {'已加载' if extra_knowledge else '无'}")

        pipeline_result = pipeline.run_pipeline(
            query=request.query,
            schema_name=request.schema_name,
            extra_knowledge=extra_knowledge.strip() if extra_knowledge else "",
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

        save_llm_log(
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
            error_message=error_msg if not is_valid else None
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
        save_llm_log(
            user_id=user_id,
            provider='unknown',
            question=request.query,
            model='unknown',
            conditions=f"schema_name={request.schema_name}, knowledge_id={request.knowledge_id}",
            result='',
            duration_ms=(time.time() - start_time) * 1000,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            status='error',
            error_message=str(e)
        )
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")
