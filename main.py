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
from app.config import SECRET_KEY, ALGORITHM
from models import init_database, SessionLocal
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


@app.get("/check-token")
async def check_token(request: Request):
    """验证token是否有效"""
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        token = auth_header[7:]
    else:
        token = request.cookies.get('token')
    
    if not token:
        return JSONResponse(status_code=401, content={"detail": "未登录"})
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get('username')
        if not username:
            return JSONResponse(status_code=401, content={"detail": "无效的token"})
        
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.username == username, User.is_active == 1).first()
            if not user:
                return JSONResponse(status_code=401, content={"detail": "用户不存在"})
            return {"valid": True, "username": username}
        finally:
            db.close()
    except jwt.ExpiredSignatureError:
        return JSONResponse(status_code=401, content={"detail": "token已过期"})
    except jwt.InvalidTokenError:
        return JSONResponse(status_code=401, content={"detail": "无效的token"})


app.include_router(base_router, tags=["基础认证"])
app.include_router(chat_to_sql_router, prefix="/api/chat-to-sql", tags=["chat_to_sql"])
app.include_router(schema_router, prefix="/api", tags=["schema管理"])
app.include_router(history_router, prefix="/api/chat-to-sql", tags=["历史记录"])
app.include_router(extra_router, prefix="/api", tags=["补充知识"])


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8188,
                reload=True, workers=10)
