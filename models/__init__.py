# -*- coding: UTF-8 -*-
"""
models 包 - 包含所有 SQLAlchemy 模型和初始化逻辑
"""
import os
import logging
from datetime import datetime
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker
from app.config import APP_DB_PATH, HISTORY_DB_PATH, SQL_DB_PATH, EXTRA_DB_PATH

logger = logging.getLogger("app_logger")
db_logger = logging.getLogger("sqlalchemy_logger")

Base = declarative_base()

app_engine = create_engine(
    f'sqlite:///{APP_DB_PATH}',
    echo=False,
    connect_args={'check_same_thread': False}
)

history_engine = create_engine(
    f'sqlite:///{HISTORY_DB_PATH}',
    echo=False,
    connect_args={'check_same_thread': False}
)

sql_engine = create_engine(
    f'sqlite:///{SQL_DB_PATH}',
    echo=False,
    connect_args={'check_same_thread': False}
)

extra_engine = create_engine(
    f'sqlite:///{EXTRA_DB_PATH}',
    echo=False,
    connect_args={'check_same_thread': False}
)

@event.listens_for(app_engine, "connect")
def app_engine_connect(dbapi_connection, connection_record):
    db_logger.debug(f"应用数据库连接创建: {APP_DB_PATH}")

@event.listens_for(history_engine, "connect")
def history_engine_connect(dbapi_connection, connection_record):
    db_logger.debug(f"历史数据库连接创建: {HISTORY_DB_PATH}")

@event.listens_for(sql_engine, "connect")
def sql_engine_connect(dbapi_connection, connection_record):
    db_logger.debug(f"SQL数据库连接创建: {SQL_DB_PATH}")

@event.listens_for(extra_engine, "connect")
def extra_engine_connect(dbapi_connection, connection_record):
    db_logger.debug(f"补充知识数据库连接创建: {EXTRA_DB_PATH}")

AppSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=app_engine)
HistorySessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=history_engine)
SqlSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sql_engine)
ExtraSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=extra_engine)

SessionLocal = AppSessionLocal


def init_database():
    """初始化所有数据库表结构"""
    _ensure_db_dirs()
    
    from models.user import User
    
    User.__table__.create(bind=app_engine, checkfirst=True)
    logger.info(f"应用数据库表创建/检查完成: {APP_DB_PATH}")
    print(f"应用数据库表创建/检查完成: {APP_DB_PATH}")
    
    init_history_database()
    init_sql_database()
    init_extra_database()
    create_default_admin()


def _ensure_db_dirs():
    """确保数据库目录存在"""
    for db_path in [APP_DB_PATH, HISTORY_DB_PATH, SQL_DB_PATH, EXTRA_DB_PATH]:
        db_dir = os.path.dirname(db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir)
            logger.info(f"创建数据库目录: {db_dir}")


def init_history_database():
    """初始化历史记录数据库"""
    from models.sql_history import SqlHistory
    
    SqlHistory.__table__.create(bind=history_engine, checkfirst=True)
    logger.info(f"历史记录数据库表创建/检查完成: {HISTORY_DB_PATH}")
    print(f"历史记录数据库表创建/检查完成: {HISTORY_DB_PATH}")


def init_sql_database():
    """初始化SQL Schema数据库"""
    from models.schema_parse import SchemaParse
    
    SchemaParse.__table__.create(bind=sql_engine, checkfirst=True)
    logger.info(f"SQL Schema数据库表创建/检查完成: {SQL_DB_PATH}")
    print(f"SQL Schema数据库表创建/检查完成: {SQL_DB_PATH}")


def init_extra_database():
    """初始化补充知识数据库"""
    from models.extra import ExtraKnowledge
    
    ExtraKnowledge.__table__.create(bind=extra_engine, checkfirst=True)
    logger.info(f"补充知识数据库表创建/检查完成: {EXTRA_DB_PATH}")
    print(f"补充知识数据库表创建/检查完成: {EXTRA_DB_PATH}")


def create_default_admin():
    """创建默认管理员用户"""
    from models.user import User
    
    db = AppSessionLocal()
    try:
        admin = db.query(User).filter(User.username == 'admin').first()
        if not admin:
            admin_user = User(
                username='admin',
                password='MyAdmin123',
                role='admin',
                description='系统管理员',
                is_active=1,
                register_date=datetime.now()
            )
            db.add(admin_user)
            db.commit()
            logger.info("默认管理员用户创建成功: admin / MyAdmin123")
            print("默认管理员用户创建成功: admin / MyAdmin123")
        else:
            logger.debug("管理员用户已存在")
            print("管理员用户已存在")
    except Exception as e:
        logger.error(f"创建默认用户失败: {e}")
        print(f"创建默认用户失败: {e}")
        db.rollback()
    finally:
        db.close()


def get_db():
    """获取应用数据库会话"""
    db = AppSessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_history_db():
    """获取历史记录数据库会话"""
    db = HistorySessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_sql_db():
    """获取SQL Schema数据库会话"""
    db = SqlSessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_extra_db():
    """获取补充知识数据库会话"""
    db = ExtraSessionLocal()
    try:
        yield db
    finally:
        db.close()
