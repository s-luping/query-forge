# -*- coding: UTF-8 -*-
import logging
import os
from contextlib import asynccontextmanager
import time
import uvicorn
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, HTMLResponse
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
from logging.handlers import TimedRotatingFileHandler

from scheduler.scheduler import scheduler_manager
from app.limiter import limiter
from app.logger import logger
from app.config import CORS_ORIGINS, COOKIE_SECURE, DEBUG, FRAME_ANCESTORS
from app.auth import _get_secret_key, resolve_token_user
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
from models import init_database


def _setup_server_logging():
    """uvicorn 控制台日志写入 logs/server.log（按天轮转，保留 30 天），终端仍实时显示"""
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
    os.makedirs(log_dir, exist_ok=True)
    handler = TimedRotatingFileHandler(
        os.path.join(log_dir, 'server.log'), when='midnight',
        backupCount=30, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s'))
    for name in ('uvicorn', 'uvicorn.error', 'uvicorn.access'):
        lg = logging.getLogger(name)
        if not any(isinstance(h, TimedRotatingFileHandler) for h in lg.handlers):
            lg.addHandler(handler)


_setup_server_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动即校验签名密钥：env 与系统设置表均缺失时拒绝启动（绝不回落到硬编码值）
    _get_secret_key()
    init_database()
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
# CORS 白名单：同源部署时无需跨域；仅显式配置的来源允许携带凭据
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


# OpenAPI 安全方案：让 /docs 的 Authorize 按钮支持 Bearer Token（可选，cookie 仍可用）
from fastapi.openapi.utils import get_openapi  # noqa: E402


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title="QueryForge API",
        version="1.4.0",
        description=(
            "QueryForge 智能数据查询平台 API。\n\n"
            "鉴权方式：登录后以 HttpOnly Cookie 自动携带，或在 Authorize 中填写 "
            "`Bearer <token>`（token 可从登录响应 Cookie 或自行签发获得）。\n"
            "普通用户访问管理员接口返回 403。"
        ),
        routes=app.routes,
    )
    schema["components"] = schema.get("components", {})
    schema["components"]["securitySchemes"] = {
        "HTTPBearer": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
    }
    schema["security"] = [{"HTTPBearer": []}]
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi


# ═══════════════════════════════════════════════════════════════════
# API 文档页 — 资源本地化（static/vendor/swagger-ui），不依赖 CDN，
# 适配内网/离线部署；访问权限由 template_auth_guard 统一控制（仅管理员）。
# ═══════════════════════════════════════════════════════════════════
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html  # noqa: E402

_SWAGGER_ASSET_PREFIX = '/static/vendor/swagger-ui'


@app.get("/docs", include_in_schema=False)
async def docs_page():
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title="QueryForge API 文档",
        swagger_js_url=f"{_SWAGGER_ASSET_PREFIX}/swagger-ui-bundle.js",
        swagger_css_url=f"{_SWAGGER_ASSET_PREFIX}/swagger-ui.css",
        swagger_favicon_url=f"{_SWAGGER_ASSET_PREFIX}/favicon.png",
    )


@app.get("/redoc", include_in_schema=False)
async def redoc_page():
    return get_redoc_html(
        openapi_url="/openapi.json",
        title="QueryForge API 文档",
        redoc_js_url=f"{_SWAGGER_ASSET_PREFIX}/redoc.standalone.js",
        redoc_favicon_url=f"{_SWAGGER_ASSET_PREFIX}/favicon.png",
    )


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """统一安全响应头"""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    # iframe 嵌入策略：
    # - 默认仅允许同源嵌入（主界面用 iframe 加载各模块页面），并配 X-Frame-Options: SAMEORIGIN 双保险；
    # - 配置 QUERYFORGE_FRAME_ANCESTORS 放行外部来源时，由 CSP frame-ancestors 精确控制，
    #   此时不再下发 X-Frame-Options（该头无法表达白名单，SAMEORIGIN 会挡住外部来源）。
    # 注意：CSP 的 self 关键字必须加引号，否则会被解析为名为 self 的主机。
    frame_ancestors = " ".join("'self'" if a == "self" else a for a in FRAME_ANCESTORS)
    if FRAME_ANCESTORS == ['self']:
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    # 文档页资源已本地化（static/vendor/swagger-ui），全程保持严格 CSP
    csp = (
        "default-src 'self'; img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
        "connect-src 'self'; "
        f"frame-ancestors {frame_ancestors}; base-uri 'self'; form-action 'self'"
    )
    response.headers.setdefault("Content-Security-Policy", csp)
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    # 页面文档禁止缓存：避免浏览器沿用旧响应（含旧 CSP frame-ancestors）导致嵌入被误拦
    content_type = response.headers.get("content-type", "")
    if "text/html" in content_type:
        response.headers.setdefault("Cache-Control", "no-store, max-age=0")
    else:
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


@app.middleware("http")
async def access_log_middleware(request: Request, call_next):
    start_time = time.time()
    
    excluded_paths = ["/static", "/favicon.ico", "/__reload__"]
    if any(request.url.path.startswith(path) for path in excluded_paths):
        return await call_next(request)
    
    user_id = None
    username = None
    token = request.cookies.get("token") or request.headers.get("Authorization", "").replace("Bearer ", "")
    if token:
        resolved = resolve_token_user(token)
        if resolved:
            user_id = resolved['user_id']
            username = resolved['username']
    
    response = await call_next(request)
    
    duration = (time.time() - start_time) * 1000
    
    log_message = f"[{request.method}] {request.url.path} - {response.status_code} - {duration:.2f}ms"
    if user_id:
        log_message += f" - user_id={user_id} username={username}"
    else:
        log_message += " - anonymous"
    
    logger.info(log_message)
    
    return response


# ═══════════════════════════════════════════════════════════════════
# 页面/模板/文档访问守卫（UI 层）
#   - 未登录访问 / 、任意模板或 API 文档 → 302 跳登录页
#   - 非管理员访问管理员模板或 API 文档 → 403（仅 admin 角色可打开）
# API 数据安全由各端点的 CurrentUser/AdminUser 依赖保证，本中间件管页面访问。
# ═══════════════════════════════════════════════════════════════════

_TEMPLATE_ADMIN_PREFIXES = (
    '/static/template/system/',                                   # 系统管理（含用户/权限/审计/同步/设置）
    '/static/template/llm/llm_config.html',                       # 模型配置（调用记录对普通用户开放，仅看自己）
    '/static/template/schema/vector_index.html',                  # 向量索引
)

# 仅管理员可见的页面路径（API 文档 + 管理后台）
_DOCS_PATHS = ('/docs', '/redoc', '/openapi.json', '/admin')


def _is_admin_template(path: str) -> bool:
    return path.startswith(_TEMPLATE_ADMIN_PREFIXES) or path in _DOCS_PATHS


_FORBIDDEN_HTML = (
    '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><title>403 无权访问</title></head>'
    '<body style="font-family:sans-serif;text-align:center;padding-top:80px;">'
    '<h2 style="color:#dc3545;">403 无权访问</h2>'
    '<p>该页面仅管理员可见，请联系管理员开通权限。</p>'
    '<a href="/" style="color:#0d6efd;">返回首页</a></body></html>'
)


@app.middleware("http")
async def template_auth_guard(request: Request, call_next):
    path = request.url.path
    is_page = (path == '/'
               or path == '/admin'
               or (path.startswith('/static/template/') and path.endswith('.html'))
               or path in _DOCS_PATHS)
    if not is_page:
        return await call_next(request)

    token = request.cookies.get("token") or request.headers.get("Authorization", "").replace("Bearer ", "")
    user = resolve_token_user(token)

    if path == '/':
        if user is None:
            return RedirectResponse('/login', status_code=302)
        return await call_next(request)

    # 静态模板 / API 文档 / 管理后台
    if user is None:
        return RedirectResponse('/login', status_code=302)
    if _is_admin_template(path) and user.get('role') != 'admin':
        logger.warning(f"越权访问管理页面: user={user.get('username')} path={path}")
        return HTMLResponse(_FORBIDDEN_HTML, status_code=403)
    return await call_next(request)


@app.get("/")
async def root():
    """用户首页：SQL 对话工作台（面向使用用户）"""
    return FileResponse("static/template/home.html")


@app.get("/admin")
async def admin_console():
    """管理后台（仅管理员，由 template_auth_guard 拦截）"""
    return FileResponse("static/template/index.html")


@app.get("/login")
async def login():
    logger.info("访问登录页面")
    return FileResponse("static/template/login.html")


@app.get("/logout")
async def logout():
    response = FileResponse("static/template/login.html")
    # 清除 cookie 需与下发时属性一致，否则 HttpOnly cookie 清不掉
    response.set_cookie(key="token", value="", expires=0, path="/",
                        httponly=True, samesite="lax", secure=COOKIE_SECURE)
    logger.info("用户登出")
    return response


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


if __name__ == "__main__":
    from app.config import HOST, PORT, DEBUG
    uvicorn.run(
        "main:app",
        host=HOST,
        port=PORT,
        reload=DEBUG,           # DEBUG 模式下自动重载（单进程）
        workers=1,              # 多 worker 需关闭 reload；本机部署保持单进程即可
    )
