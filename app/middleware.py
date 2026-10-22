"""应用中间件：安全响应头、访问日志（含 traceId/慢接口）、页面访问守卫和 CORS。"""
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse

from app.security import resolve_request_user
from app.settings import CORS_ORIGINS, FRAME_ANCESTORS, SLOW_REQUEST_MS
from app.logger import logger
from app.response import get_request_id, new_request_id, set_request_id

_TEMPLATE_ADMIN_PREFIXES = (
    '/static/template/system/',
    '/static/template/llm/llm_config.html',
    '/static/template/schema/vector_index.html',
)
_DOCS_PATHS = ('/docs', '/redoc', '/openapi.json', '/admin')
_FORBIDDEN_HTML = (
    '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
    '<title>403 无权访问</title></head>'
    '<body style="font-family:sans-serif;text-align:center;padding-top:80px;">'
    '<h2 style="color:#dc3545;">403 无权访问</h2>'
    '<p>该页面仅管理员可见，请联系管理员开通权限。</p>'
    '<a href="/" style="color:#0d6efd;">返回首页</a></body></html>'
)


def _is_admin_page(path: str) -> bool:
    return path.startswith(_TEMPLATE_ADMIN_PREFIXES) or path in _DOCS_PATHS


async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    frame_ancestors = ' '.join("'self'" if item == 'self' else item
                               for item in FRAME_ANCESTORS)
    if FRAME_ANCESTORS == ['self']:
        response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    response.headers.setdefault(
        'Content-Security-Policy',
        "default-src 'self'; img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
        "connect-src 'self'; "
        f"frame-ancestors {frame_ancestors}; base-uri 'self'; form-action 'self'"
    )
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    content_type = response.headers.get('content-type', '')
    response.headers.setdefault(
        'Cache-Control', 'no-store, max-age=0' if 'text/html' in content_type else 'no-cache')
    return response


async def access_log(request: Request, call_next):
    if any(request.url.path.startswith(path)
           for path in ('/static', '/favicon.ico', '/__reload__')):
        return await call_next(request)
    # traceId：贯穿访问日志 / 慢SQL日志 / 错误响应体 / X-Request-ID 响应头
    set_request_id(new_request_id())
    started = time.time()
    # 请求级缓存解析（结果供 page_auth_guard / 限流 key / 路由依赖复用）
    user = resolve_request_user(request)
    response = await call_next(request)
    duration = (time.time() - started) * 1000
    identity = (f"user_id={user['user_id']} username={user['username']}"
                if user else 'anonymous')
    rid = get_request_id()
    log_line = (f'[{rid}] [{request.method}] {request.url.path} - '
                f'{response.status_code} - {duration:.2f}ms - {identity}')
    if duration >= SLOW_REQUEST_MS:
        # 慢接口观测（纲领 §4.1）：独立 WARNING 便于检索
        logger.warning(f'[SLOW] {log_line}')
    else:
        logger.info(log_line)
    try:
        response.headers['X-Request-ID'] = rid
    except Exception:
        pass
    return response


async def page_auth_guard(request: Request, call_next):
    path = request.url.path
    is_page = (path in ('/', '/admin') or
               (path.startswith('/static/template/') and path.endswith('.html')) or
               path in _DOCS_PATHS)
    if not is_page:
        return await call_next(request)
    user = resolve_request_user(request)
    if path == '/':
        return await call_next(request) if user else RedirectResponse('/login', status_code=302)
    if not user:
        return RedirectResponse('/login', status_code=302)
    if _is_admin_page(path) and user.get('role') != 'admin':
        from app.permissions import has_permission
        allowed = has_permission(user, path, 'page', path) or has_permission(
            user, 'page.view', 'page', path)
        if not allowed:
            logger.warning(f"越权访问管理页面: user={user.get('username')} path={path}")
            return HTMLResponse(_FORBIDDEN_HTML, status_code=403)
    return await call_next(request)


def register_middlewares(app: FastAPI):
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
        allow_headers=['Authorization', 'Content-Type'],
    )
    app.middleware('http')(security_headers)
    app.middleware('http')(access_log)
    app.middleware('http')(page_auth_guard)
