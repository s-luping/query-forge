"""配置模块 — 数据库路径（双库布局）

主库 queryforge.db：交互域短事务（用户/配置/Schema三层/知识/对话/聚合统计/系统设置）
遥测库 llm_telemetry.db：LLM 调用追加型高频写（llm_calls / llm_prompts）
可通过环境变量 QUERYFORGE_MAIN_DB / QUERYFORGE_TELEMETRY_DB 覆盖路径。
"""
import base64
import os
import secrets
import sqlite3

from app.utils import _load_env_file

_load_env_file()

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DB_DIR = os.path.join(_PROJECT_ROOT, 'db')
RUNTIME_SECRETS_PATH = os.path.join(_PROJECT_ROOT, '.runtime_secrets')


def _resolve(env_key: str, filename: str) -> str:
    path = os.getenv(env_key, '')
    if path:
        return os.path.abspath(path)
    return os.path.join(_DB_DIR, filename)


MAIN_DB_PATH = _resolve('QUERYFORGE_MAIN_DB', 'queryforge.db')
TELEMETRY_DB_PATH = _resolve('QUERYFORGE_TELEMETRY_DB', 'llm_telemetry.db')

# 运行配置
HOST = os.getenv('QUERYFORGE_HOST', '0.0.0.0')
PORT = int(os.getenv('QUERYFORGE_PORT', '8888'))
DEBUG = os.getenv('QUERYFORGE_DEBUG', '').lower() in ('1', 'true', 'yes')
FALLBACK_EXPIRE_MINUTES = int(os.getenv('QUERYFORGE_FALLBACK_EXPIRE_MINUTES', '4320'))

# 系统配置种子：key -> (默认值, 分类, 是否可编辑)
SYSTEM_SETTING_DEFAULTS = {
    'SECRET_KEY': (None, 'security', 0),
    'ACCESS_TOKEN_EXPIRE_MINUTES': (str(FALLBACK_EXPIRE_MINUTES), 'auth', 1),
    'ALLOW_REGISTER': ('true', 'auth', 1),
    'EMBEDDING_MODEL_READY': ('false', 'runtime', 0),
    'EMBEDDING_MODEL_PATH': ('', 'runtime', 0),
    'VECTOR_INDEX_THRESHOLD': ('50', 'vector', 1),
    'FIELD_RECALL_TOP_K': ('20', 'vector', 1),
    'MAX_TABLES': ('10', 'vector', 1),
}

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


def _read_runtime_secrets() -> dict:
    if not os.path.exists(RUNTIME_SECRETS_PATH):
        return {}
    values = {}
    try:
        with open(RUNTIME_SECRETS_PATH, 'r', encoding='utf-8') as file:
            for line in file:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    values[key.strip()] = value.strip()
    except OSError:
        pass
    return values


def _read_database_secret() -> str:
    """兼容已有数据库：在 ORM 建表前读取历史 SECRET_KEY。"""
    if not os.path.exists(MAIN_DB_PATH):
        return ''
    try:
        with sqlite3.connect(MAIN_DB_PATH) as connection:
            row = connection.execute(
                "SELECT value FROM system_settings WHERE key = 'SECRET_KEY' LIMIT 1"
            ).fetchone()
            return str(row[0]) if row and row[0] else ''
    except sqlite3.Error:
        return ''


def _write_runtime_secrets(values: dict):
    os.makedirs(os.path.dirname(RUNTIME_SECRETS_PATH), exist_ok=True)
    temp_path = RUNTIME_SECRETS_PATH + '.tmp'
    with open(temp_path, 'w', encoding='utf-8') as file:
        file.write('# QueryForge generated runtime secrets; keep this file private.\n')
        for key in ('QUERYFORGE_SECRET_KEY', 'QUERYFORGE_FERNET_KEY'):
            if values.get(key):
                file.write(f'{key}={values[key]}\n')
    os.replace(temp_path, RUNTIME_SECRETS_PATH)


def initialize_runtime_secrets():
    """在数据库初始化前准备并持久化启动所需的安全参数。"""
    global SECRET_KEY, FERNET_KEY

    file_values = _read_runtime_secrets()
    SECRET_KEY = SECRET_KEY or file_values.get('QUERYFORGE_SECRET_KEY', '')
    SECRET_KEY = SECRET_KEY or _read_database_secret()
    if not SECRET_KEY:
        SECRET_KEY = secrets.token_urlsafe(36)

    FERNET_KEY = FERNET_KEY or file_values.get('QUERYFORGE_FERNET_KEY', '')
    # 旧数据库没有独立 Fernet 密钥时继续由 SECRET_KEY 派生，避免历史密文失效。
    if not FERNET_KEY and not _read_database_secret():
        FERNET_KEY = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('ascii')

    SYSTEM_SETTING_DEFAULTS['SECRET_KEY'] = (SECRET_KEY, 'security', 0)
    _write_runtime_secrets({
        'QUERYFORGE_SECRET_KEY': SECRET_KEY,
        'QUERYFORGE_FERNET_KEY': FERNET_KEY,
    })


# 配置模块加载完成即准备启动密钥；数据库初始化再次调用时保持幂等。
initialize_runtime_secrets()
