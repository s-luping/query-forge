# -*- coding: UTF-8 -*-
from contextlib import asynccontextmanager
import uvicorn
from fastapi import Depends, FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
import jwt

from scheduler.scheduler import scheduler_manager
from app.limiter import limiter
from app.routers.base_router import router as base_router
from app.routers.chat_to_sql_router import router as chat_to_sql_router
from app.routers.schema_router import router as schema_router
from app.routers.history_router import router as history_router
from app.routers.extra_router import router as extra_router
from app.routers.table_data_router import router as table_data_router
from app.routers.llm_router import router as llm_router
from app.routers.llm_config_router import router as llm_config_router
from app.config import SECRET_KEY, ALGORITHM
from models import init_database, AppSessionLocal
from models.user import User


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_database()
    scheduler_manager.init_scheduler()
    scheduler_manager.start()
    yield
    scheduler_manager.shutdown()


app = FastAPI(docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return FileResponse("static/template/index.html")


@app.get("/login")
async def login():
    return FileResponse("static/template/login.html")


@app.get("/logout")
async def logout():
    response = FileResponse("static/template/login.html")
    response.set_cookie(key="token", value="", expires=0)
    return response


app.include_router(base_router, tags=["基础认证"])
app.include_router(chat_to_sql_router, prefix="/api/chat-to-sql", tags=["chat_to_sql"])
app.include_router(schema_router, prefix="/api/schema", tags=["schema 管理"])
app.include_router(history_router, prefix="/api/history", tags=["历史记录"])
app.include_router(extra_router, prefix="/api/extra-knowledge", tags=["补充知识"])
app.include_router(table_data_router, prefix="/api/table-data", tags=["表数据管理"])
app.include_router(llm_router, prefix="/api/llm", tags=["LLM调用记录"])
app.include_router(llm_config_router, prefix="/api/llm-config", tags=["LLM配置管理"])


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8188,
                reload=True, workers=10)
