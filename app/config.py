"""配置模块 — Django 风格：全部配置为模块级 键=值 赋值，不使用函数

主库 queryforge.db：交互域短事务（用户/配置/Schema三层/知识/对话/聚合统计/系统设置）
遥测库 llm_telemetry.db：LLM 调用追加型高频写（llm_calls / llm_prompts）

本文件为全部配置的唯一初始值来源（包括首次写入 system_settings 表的系统设置）。
运行期读取顺序：数据库 system_settings（前台用户改过的值）优先，
其次回落本文件中的初始值 —— 统一经 db.get_setting() 读取。

安全密钥：SECRET_KEY 留空时，首次初始化数据库会自动生成随机字符串并持久化到
系统设置表；FERNET_KEY 留空时 crypto 模块从 SECRET_KEY 派生。
"""
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_DIR = os.path.join(PROJECT_ROOT, 'db')

# ── 数据库路径 ─────────────────────────────────────────────
MAIN_DB_PATH = os.path.join(DB_DIR, 'queryforge.db')
TELEMETRY_DB_PATH = os.path.join(DB_DIR, 'llm_telemetry.db')

# ── 数据库连接池（SQLAlchemy QueuePool 复用，减少建连/断连开销） ──
DB_POOL_SIZE = 10                # 池内常驻连接数
DB_MAX_OVERFLOW = 20             # 峰值时最多额外创建的连接数
DB_POOL_TIMEOUT = 30             # 等待空闲连接超时（秒）
DB_POOL_RECYCLE = 3600           # 连接回收周期（秒），防止陈旧连接
DB_ECHO = False                  # SQL 回显（调试用）

# ── 运行配置 ───────────────────────────────────────────────
HOST = '0.0.0.0'
PORT = 8888
DEBUG = False

# ── 系统设置初始值（首次启动写入 system_settings 表；运行期数据库优先） ──
ACCESS_TOKEN_EXPIRE_MINUTES = 4320          # 登录令牌有效期（分钟），auth 分类可改
ALLOW_REGISTER = 'true'                     # 是否开放注册，auth 分类可改
EMBEDDING_MODEL_READY = 'false'             # embedding 模型是否就绪，runtime 自动维护
EMBEDDING_MODEL_PATH = ''                   # embedding 模型路径，runtime 自动维护
VECTOR_INDEX_THRESHOLD = '50'               # 向量索引构建阈值，vector 分类可改
FIELD_RECALL_TOP_K = '20'                   # 字段召回数量，vector 分类可改
MAX_TABLES = '10'                           # 单次查询最大表数，vector 分类可改

# ── 安全配置 ───────────────────────────────────────────────
# JWT 签名密钥：留空则首次初始化数据库时自动生成随机字符串并持久化到系统设置表
SECRET_KEY = ''
# Fernet 加密密钥：留空时 crypto 模块从 SECRET_KEY 派生
FERNET_KEY = ''
# cookie Secure 标志（启用 HTTPS 后置 True）
COOKIE_SECURE = False
# CORS 白名单（空列表 = 前端与 API 同源部署）
CORS_ORIGINS = []
# iframe 嵌入白名单（对应 CSP frame-ancestors；默认仅允许同源嵌入；
# 需被外部页面嵌入时改为 ['http://127.0.0.1:3000', 'http://portal.example.com']，或 '*' 允许任意）
FRAME_ANCESTORS = ['self']
