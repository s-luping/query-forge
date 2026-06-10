"""
models 包 - SQLAlchemy 模型和数据库初始化
"""
import os
from datetime import datetime

from sqlalchemy import create_engine, text, event
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import APP_DB_PATH, SCHEMA_DB_PATH, EXTRA_DB_PATH, LLM_DB_PATH, CONVERSATION_DB_PATH
from app.logger import logger

Base = declarative_base()


def _set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA cache_size=-64000")
    cursor.close()


def _create_engine_with_wal(db_path: str):
    engine = create_engine(
        f'sqlite:///{db_path}',
        echo=False,
        connect_args={'check_same_thread': False, 'timeout': 30}
    )
    event.listen(engine, 'connect', _set_sqlite_pragma)
    return engine


app_engine = _create_engine_with_wal(APP_DB_PATH)
llm_engine = _create_engine_with_wal(LLM_DB_PATH)
schema_engine = _create_engine_with_wal(SCHEMA_DB_PATH)
extra_engine = _create_engine_with_wal(EXTRA_DB_PATH)
conversation_engine = _create_engine_with_wal(CONVERSATION_DB_PATH)

AppSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=app_engine)
SchemaSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=schema_engine)
ExtraSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=extra_engine)
LLMSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=llm_engine)
ConversationSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=conversation_engine)


def init_database():
    """初始化所有数据库表结构"""
    _ensure_db_dirs()

    from models.user import User, UserSchema, UserExtra
    from models.llm import LLMConfig
    from models.system import SystemConfig
    from models.vector_index import VectorIndexMeta

    User.__table__.create(bind=app_engine, checkfirst=True)
    LLMConfig.__table__.create(bind=app_engine, checkfirst=True)
    SystemConfig.__table__.create(bind=app_engine, checkfirst=True)
    VectorIndexMeta.__table__.create(bind=app_engine, checkfirst=True)
    UserSchema.__table__.create(bind=app_engine, checkfirst=True)
    UserExtra.__table__.create(bind=app_engine, checkfirst=True)
    _seed_system_config()

    logger.info(f"应用数据库表创建/检查完成: {APP_DB_PATH}")
    print(f"应用数据库表创建/检查完成: {APP_DB_PATH}")

    init_schema_database()
    init_extra_database()
    init_llm_database()
    init_conversation_database()
    create_default_admin()


def _ensure_db_dirs():
    for db_path in [APP_DB_PATH, SCHEMA_DB_PATH, EXTRA_DB_PATH, LLM_DB_PATH, CONVERSATION_DB_PATH]:
        db_dir = os.path.dirname(db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir)
            logger.info(f"创建数据库目录: {db_dir}")


def _sync_embedding_model_path(db):
    """如果 EMBEDDING_MODEL_READY=true 但路径为空，自动扫描补齐"""
    import os
    from models.system import SystemConfig

    ready_row = db.query(SystemConfig).filter(
        SystemConfig.key == 'EMBEDDING_MODEL_READY'
    ).first()
    path_row = db.query(SystemConfig).filter(
        SystemConfig.key == 'EMBEDDING_MODEL_PATH'
    ).first()

    if not ready_row or str(ready_row.value) != 'true':
        return
    if path_row and str(path_row.value).strip():
        return  # 已有路径，无需修复

    # 扫描模型目录
    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    MODEL_CACHE_DIR = os.path.join(PROJECT_ROOT, 'models', 'embeddings')
    possible_paths = [
        os.path.join(MODEL_CACHE_DIR, 'bge-m3', 'BAAI', 'bge-m3'),
        os.path.join(MODEL_CACHE_DIR, 'bge-m3'),
    ]
    for local_path in possible_paths:
        if os.path.exists(os.path.join(local_path, 'config.json')):
            if path_row:
                path_row.value = local_path  # type: ignore[assignment]
            else:
                db.add(SystemConfig(key='EMBEDDING_MODEL_PATH', value=local_path))
            db.commit()
            logger.info(f"已自动补齐 EMBEDDING_MODEL_PATH = {local_path}")
            return


def _seed_system_config():
    import secrets
    import string
    from models.system import SystemConfig

    db = AppSessionLocal()
    try:
        if not db.query(SystemConfig).filter(SystemConfig.key == 'SECRET_KEY').first():
            chars = string.ascii_letters + string.digits
            random_key = ''.join(secrets.choice(chars) for _ in range(36))
            db.add(SystemConfig(key='SECRET_KEY', value=random_key))
            logger.info("已生成随机 SECRET_KEY")
        if not db.query(SystemConfig).filter(SystemConfig.key == 'ACCESS_TOKEN_EXPIRE_MINUTES').first():
            db.add(SystemConfig(key='ACCESS_TOKEN_EXPIRE_MINUTES', value='4320'))
            logger.info("已初始化 ACCESS_TOKEN_EXPIRE_MINUTES = 4320 (3天)")
        if not db.query(SystemConfig).filter(SystemConfig.key == 'EMBEDDING_MODEL_READY').first():
            db.add(SystemConfig(key='EMBEDDING_MODEL_READY', value='false'))
            logger.info("已初始化 EMBEDDING_MODEL_READY = false（嵌入模型未下载）")
        if not db.query(SystemConfig).filter(SystemConfig.key == 'EMBEDDING_MODEL_PATH').first():
            db.add(SystemConfig(key='EMBEDDING_MODEL_PATH', value=''))
            logger.info("已初始化 EMBEDDING_MODEL_PATH（模型路径缓存）")
        db.commit()

        # 一致性修复：ready=true 但 path 为空时，自动扫描补齐路径
        _sync_embedding_model_path(db)
    except Exception as e:
        logger.warning(f"初始化系统配置失败: {e}")
        db.rollback()
    finally:
        db.close()


def init_schema_database():
    from models.schema import Schema
    Schema.__table__.create(bind=schema_engine, checkfirst=True)
    logger.info(f"模式数据库表创建/检查完成: {SCHEMA_DB_PATH}")
    print(f"模式数据库表创建/检查完成: {SCHEMA_DB_PATH}")


def init_extra_database():
    from models.extra_knowledge import ExtraKnowledge
    ExtraKnowledge.__table__.create(bind=extra_engine, checkfirst=True)
    logger.info(f"补充知识数据库表创建/检查完成: {EXTRA_DB_PATH}")
    print(f"补充知识数据库表创建/检查完成: {EXTRA_DB_PATH}")


def init_llm_database():
    from models.llm import LLMLog
    LLMLog.__table__.create(bind=llm_engine, checkfirst=True)
    _migrate_llm_log_columns()
    logger.info(f"LLM调用记录数据库表创建/检查完成: {LLM_DB_PATH}")
    print(f"LLM调用记录数据库表创建/检查完成: {LLM_DB_PATH}")


def _migrate_llm_log_columns():
    import sqlalchemy
    try:
        with llm_engine.connect() as conn:
            result = conn.execute(sqlalchemy.text("PRAGMA table_info('llm_logs')"))
            columns = [row[1] for row in result.fetchall()]
            if 'provider' not in columns:
                conn.execute(sqlalchemy.text("ALTER TABLE llm_logs ADD COLUMN provider VARCHAR(50) DEFAULT ''"))
            if 'cost' not in columns:
                conn.execute(sqlalchemy.text("ALTER TABLE llm_logs ADD COLUMN cost FLOAT DEFAULT 0.0"))
            if 'system_prompt' not in columns:
                conn.execute(sqlalchemy.text("ALTER TABLE llm_logs ADD COLUMN system_prompt TEXT"))
            conn.commit()
        with app_engine.connect() as conn:
            result = conn.execute(sqlalchemy.text("PRAGMA table_info('llm_configs')"))
            columns = [row[1] for row in result.fetchall()]
            if 'is_public' not in columns:
                conn.execute(sqlalchemy.text("ALTER TABLE llm_configs ADD COLUMN is_public BOOLEAN DEFAULT 0"))
            conn.commit()
    except Exception as e:
        logger.warning(f"迁移失败（可忽略）: {e}")


def init_conversation_database():
    from models.conversation import Conversation, ConversationMessage
    Conversation.__table__.create(bind=conversation_engine, checkfirst=True)
    ConversationMessage.__table__.create(bind=conversation_engine, checkfirst=True)
    _migrate_conversation_columns()
    logger.info(f"对话记录数据库表创建/检查完成: {CONVERSATION_DB_PATH}")
    print(f"对话记录数据库表创建/检查完成: {CONVERSATION_DB_PATH}")


def _migrate_conversation_columns():
    import sqlalchemy
    try:
        with conversation_engine.connect() as conn:
            result = conn.execute(sqlalchemy.text("PRAGMA table_info('conversations')"))
            columns = [row[1] for row in result.fetchall()]
            if 'knowledge_id' not in columns:
                conn.execute(sqlalchemy.text("ALTER TABLE conversations ADD COLUMN knowledge_id INTEGER"))
            # 清理早期版本遗留的 extra_knowledge 列（已被 knowledge_id 替代）
            if 'extra_knowledge' in columns and 'knowledge_id' in columns:
                conn.execute(sqlalchemy.text("""
                    CREATE TABLE conversations_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        title VARCHAR(200),
                        schema_name VARCHAR(100),
                        db_type VARCHAR(20) DEFAULT 'sqlite',
                        llm_config_id INTEGER,
                        knowledge_id INTEGER,
                        created_at DATETIME,
                        updated_at DATETIME
                    )
                """))
                conn.execute(sqlalchemy.text(
                    "INSERT INTO conversations_new SELECT id, user_id, title, schema_name, db_type, llm_config_id, knowledge_id, created_at, updated_at FROM conversations"
                ))
                conn.execute(sqlalchemy.text("DROP TABLE conversations"))
                conn.execute(sqlalchemy.text("ALTER TABLE conversations_new RENAME TO conversations"))
                logger.info("对话表迁移: 已清理多余列 extra_knowledge")
            conn.commit()
    except Exception as e:
        logger.warning(f"对话表迁移失败（可忽略）: {e}")


def create_default_admin():
    import secrets
    import string
    from models.user import User

    db = AppSessionLocal()
    try:
        admin = db.query(User).filter(User.username == 'admin').first()
        if not admin:
            chars = string.ascii_letters + string.digits + '!@#$%^&*'
            pwd = ''.join(secrets.choice(chars) for _ in range(16))
            admin_user = User(
                username='admin', password=pwd, role='admin',
                description='系统管理员', is_active=1, register_date=datetime.now()
            )
            db.add(admin_user)
            db.commit()
            logger.info("默认管理员用户创建成功: admin")
            print(f"\n{'='*60}")
            print(f"  默认管理员账号已创建")
            print(f"  用户名: admin")
            print(f"  密码:   {pwd}")
            print(f"  请登录后立即修改密码！")
            print(f"{'='*60}\n")
        else:
            logger.debug("管理员用户已存在")
            print("管理员用户已存在")
    except Exception as e:
        logger.error(f"创建默认用户失败: {e}")
        db.rollback()
    finally:
        db.close()
