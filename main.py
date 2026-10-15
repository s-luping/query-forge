# -*- coding: UTF-8 -*-
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.auth import _get_secret_key
from app.config import DEBUG
from app.limiter import limiter
from app.logger import logger, setup_server_logging
from app.middleware import register_middlewares
from app.response import error_body, get_request_id
from app.routers.auth_router import router as auth_router
from app.routers.conversation_router import router as conversation_router
from app.routers.docs_router import register_docs
from app.routers.driver_router import router as driver_router
from app.routers.knowledge_router import router as knowledge_router
from app.routers.llm_router import config_router as llm_config_router
from app.routers.llm_router import log_router as llm_router
from app.routers.page_router import router as page_router
from app.routers.permission_router import router as permission_router
from app.routers.scheduler_router import router as scheduler_router
from app.routers.schema_router import router as schema_router
from app.routers.security_router import router as security_router
from app.routers.sync_router import router as sync_router
from app.routers.system_router import router as system_router
from app.routers.user_router import router as user_router
from db import init_database
from scheduler.scheduler import scheduler_manager

setup_server_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 建表前准备运行时密钥和系统配置
    init_database()
    # env 与系统设置表均缺失时拒绝启动（绝不回落到硬编码值）
    _get_secret_key()
    scheduler_manager.init_scheduler()
    scheduler_manager.start()
    # 后台预热向量模型（首次生成需加载 bge-m3 embedding 模型，避免用户首问等待 10s+）
    import threading as _threading

    def _warmup_vector():
        try:
            from core.ret_vector_store import EmbeddingModel
            # 编码一条文本强制加载 bge-m3 embedding 模型（模型加载是首问耗时大头）
            EmbeddingModel.encode(['预热'])
            logger.info("向量模型预热完成（后台加载成功）")
        except Exception as e:
            logger.warning(f"向量模型预热失败（首次生成时再加载）: {e}")

    _threading.Thread(target=_warmup_vector, daemon=True).start()
    logger.info("应用启动完成")
    yield
    scheduler_manager.shutdown()
    logger.info("应用关闭")


app = FastAPI(docs_url=None,
              redoc_url=None,
              openapi_url="/openapi.json",
              lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.state.limiter = limiter


# ── 全局异常处理 — 统一错误体 {code, message, detail, request_id}（纲领 §2）──
# detail 键保留：前端 apiRequest 沿用 data.detail 展示错误信息
@app.exception_handler(Exception)
async def _global_exception_handler(request: Request, exc: Exception):
    """捕获所有未处理异常，记录完整堆栈到日志，但只返回通用错误消息给客户端。
    DEBUG 模式下返回更多调试信息。"""
    rid = get_request_id()
    logger.error(
        f"未处理异常 [{rid}] [{request.method} {request.url.path}]: {exc}",
        exc_info=True,
    )
    detail = str(exc) if DEBUG else "服务器内部错误，请联系管理员"
    return JSONResponse(
        status_code=500,
        content=error_body(500, detail=detail, message='服务器内部错误', request_id=rid),
    )


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    """限流触发 — 返回统一错误体（42900），附带 Retry-After"""
    retry_after = getattr(exc, 'retry_after', None) or 60
    return JSONResponse(
        status_code=429,
        headers={'Retry-After': str(retry_after)},
        content=error_body(429, detail=f'请求过于频繁，请 {retry_after} 秒后重试',
                           message='请求过于频繁'),
    )


@app.exception_handler(RequestValidationError)
async def _validation_handler(request: Request, exc: RequestValidationError):
    """参数校验失败 — 422 → 统一错误体（40000），detail 为字段级错误"""
    return JSONResponse(
        status_code=422,
        content=error_body(422, detail=exc.errors() if DEBUG else '请求参数格式不正确',
                           message='请求参数格式不正确'),
    )


@app.exception_handler(StarletteHTTPException)
async def _http_exception_handler(request: Request, exc: StarletteHTTPException):
    """HTTPException → 统一错误体（保留 detail，新增 code/message/request_id）

    注册在 Starlette 父类上：FastAPI 的 HTTPException 是其子类，两者共用本处理器，
    否则路由未命中抛出的 404 / 405 会绕过统一错误体（Starlette 原生 {"detail": ...}）。
    """
    headers = getattr(exc, 'headers', None)
    return JSONResponse(
        status_code=exc.status_code,
        headers=headers,
        content=error_body(exc.status_code, detail=exc.detail,
                           message=str(exc.detail) if exc.detail else '请求失败'),
    )


register_docs(app)
register_middlewares(app)
app.include_router(page_router)


app.include_router(auth_router, tags=["基础认证"])
app.include_router(user_router, prefix="/api/user", tags=["用户管理"])
app.include_router(schema_router, prefix="/api/schema", tags=["schema 管理"])
app.include_router(knowledge_router, prefix="/api/knowledge", tags=["知识库"])
app.include_router(llm_router, prefix="/api/llm", tags=["LLM调用记录"])
app.include_router(llm_config_router,
                   prefix="/api/llm-config", tags=["LLM配置管理"])
app.include_router(conversation_router,
                   prefix="/api/conversation", tags=["连续对话"])
app.include_router(system_router,
                   prefix="/api/system", tags=["系统配置"])
app.include_router(permission_router,
                   prefix="/api/permission", tags=["权限管理"])
app.include_router(security_router,
                   prefix="/api/audit", tags=["安全与审计"])
app.include_router(sync_router,
                   prefix="/api/sync", tags=["元数据同步"])
app.include_router(driver_router,
                   prefix="/api/driver", tags=["数据库驱动管理"])
app.include_router(scheduler_router,
                   prefix="/api/scheduler", tags=["系统定时任务"])


if __name__ == "__main__":
    from app.config import HOST, PORT
    uvicorn.run(
        "main:app",
        host=HOST,
        port=PORT,
        reload=DEBUG,           # DEBUG 模式下自动重载（单进程）
        workers=1,              # 多 worker 需关闭 reload；本机部署保持单进程即可
    )
