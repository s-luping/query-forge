"""API 文档路由 — 本地 Swagger UI、ReDoc 与 OpenAPI 安全方案。"""
from fastapi import APIRouter, Request
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.openapi.utils import get_openapi

from app.limiter import LIMIT_READ, limiter

router = APIRouter()
_SWAGGER_ASSET_PREFIX = '/static/vendor/swagger-ui'


@router.get("/docs", include_in_schema=False)
@limiter.limit(LIMIT_READ)
async def docs_page(request: Request):
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title="QueryForge API 文档",
        swagger_js_url=f"{_SWAGGER_ASSET_PREFIX}/swagger-ui-bundle.js",
        swagger_css_url=f"{_SWAGGER_ASSET_PREFIX}/swagger-ui.css",
        swagger_favicon_url=f"{_SWAGGER_ASSET_PREFIX}/favicon.png",
    )


@router.get("/redoc", include_in_schema=False)
@limiter.limit(LIMIT_READ)
async def redoc_page(request: Request):
    return get_redoc_html(
        openapi_url="/openapi.json",
        title="QueryForge API 文档",
        redoc_js_url=f"{_SWAGGER_ASSET_PREFIX}/redoc.standalone.js",
        redoc_favicon_url=f"{_SWAGGER_ASSET_PREFIX}/favicon.png",
    )


def configure_openapi(app):
    """为应用安装带 Bearer JWT 安全方案的 OpenAPI 生成器。"""
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


def register_docs(app):
    """注册文档路由并配置 OpenAPI。"""
    app.include_router(router)
    configure_openapi(app)