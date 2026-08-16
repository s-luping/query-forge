"""配置模块 — 数据库路径（双库布局）

主库 queryforge.db：交互域短事务（用户/配置/Schema三层/知识/对话/聚合统计/系统设置）
遥测库 llm_telemetry.db：LLM 调用追加型高频写（llm_calls / llm_prompts）
可通过环境变量 QUERYFORGE_MAIN_DB / QUERYFORGE_TELEMETRY_DB 覆盖路径。
"""
import os

from app.utils import _load_env_file

_load_env_file()

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DB_DIR = os.path.join(_PROJECT_ROOT, 'db')


def _resolve(env_key: str, filename: str) -> str:
    path = os.getenv(env_key, '')
    if path:
        return os.path.abspath(path)
    return os.path.join(_DB_DIR, filename)


MAIN_DB_PATH = _resolve('QUERYFORGE_MAIN_DB', 'queryforge.db')
TELEMETRY_DB_PATH = _resolve('QUERYFORGE_TELEMETRY_DB', 'llm_telemetry.db')

# 运行配置
HOST = os.getenv('QUERYFORGE_HOST', '0.0.0.0')
PORT = int(os.getenv('QUERYFORGE_PORT', '8188'))
DEBUG = os.getenv('QUERYFORGE_DEBUG', '').lower() in ('1', 'true', 'yes')

# 安全配置（优先级：环境变量 > 系统设置表；均缺失时应用拒绝签发/校验 token）
# 生成方式: python -c "import secrets; print(secrets.token_urlsafe(32))"
SECRET_KEY = os.getenv('QUERYFORGE_SECRET_KEY', '')
# Fernet 密钥独立于 JWT 密钥（推荐配置；缺省时从 SECRET_KEY 派生以兼容旧数据）
# 生成方式: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
FERNET_KEY = os.getenv('QUERYFORGE_FERNET_KEY', '')
# cookie Secure 标志（启用 HTTPS 后置 1）
COOKIE_SECURE = os.getenv('QUERYFORGE_COOKIE_SECURE', '').lower() in ('1', 'true', 'yes')
# CORS 白名单（逗号分隔；前端与 API 同源部署时留空即可）
CORS_ORIGINS = [o.strip() for o in os.getenv('QUERYFORGE_CORS_ORIGINS', '').split(',') if o.strip()]
# iframe 嵌入白名单（逗号分隔，对应 CSP frame-ancestors；默认仅允许同源嵌入）
# 例：QUERYFORGE_FRAME_ANCESTORS=http://127.0.0.1:3000,http://portal.example.com
# 如需允许任意站点嵌入（不推荐），可设为 *
FRAME_ANCESTORS = [o.strip() for o in os.getenv('QUERYFORGE_FRAME_ANCESTORS', 'self').split(',') if o.strip()]
if not FRAME_ANCESTORS:
    FRAME_ANCESTORS = ['self']
