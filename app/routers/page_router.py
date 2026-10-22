"""页面路由：用户首页、管理后台、登录和退出。"""
from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.settings import COOKIE_SECURE

router = APIRouter()


@router.get('/')
async def root():
    return FileResponse('static/template/home.html')


@router.get('/admin')
async def admin_console():
    return FileResponse('static/template/index.html')


@router.get('/login')
async def login():
    return FileResponse('static/template/login.html')


@router.get('/logout')
async def logout():
    response = FileResponse('static/template/login.html')
    response.set_cookie(key='token', value='', expires=0, path='/',
                        httponly=True, samesite='lax', secure=COOKIE_SECURE)
    return response
