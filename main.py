# -*- coding: UTF-8 -*-
from contextlib import asynccontextmanager
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

from scheduler.scheduler import scheduler_manager
from app.limiter import limiter
from app.logger import logger, setup_server_logging
from app.config import DEBUG
from app.auth import _get_secret_key
from app.middleware import register_middlewares
from app.routers.auth_router import router as auth_router
from app.routers.chat_to_sql_router import router as chat_to_sql_router
from app.routers.schema_router import router as schema_router
from app.routers.knowledge_router import router as knowledge_router
from app.routers.llm_router import log_router as llm_router, config_router as llm_config_router
from app.routers.user_router import router as user_router
from app.routers.conversation_router import router as conversation_router
from app.routers.system_router import router as system_router
from app.routers.permission_router import router as permission_router
from app.routers.security_router import router as security_router
from app.routers.sync_router import router as sync_router
from app.routers.driver_router import router as driver_router
from app.routers.docs_router import register_docs
from app.routers.page_router import router as page_router
from app.routers.scheduler_router import router as scheduler_router
from models import init_database


setup_server_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 建表前准备运行时密钥和系统配置
    init_database()
    # env 与系统设置表均缺失时拒绝启动（绝不回落到硬编码值）
    _get_secret_key()
    scheduler_manager.init_scheduler()
    scheduler_manager.start()
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
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
register_docs(app)
register_middlewares(app)
app.include_router(page_router)


app.include_router(auth_router, tags=["基础认证"])
app.include_router(user_router, prefix="/api/user", tags=["用户管理"])
app.include_router(chat_to_sql_router,
                   prefix="/api/chat-to-sql", tags=["chat_to_sql"])
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
