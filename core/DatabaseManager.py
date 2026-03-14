import logging
import sqlite3
import os
from typing import List, Dict, Any


logger = logging.getLogger(__name__)

# 默认SQLite数据库路径
DEFAULT_DB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'db')
DEFAULT_DB_PATH = os.path.join(DEFAULT_DB_DIR, 'app.db')


class DatabaseManager:
    """SQLite数据库管理器"""

    def __init__(self, db_path: str = None):
        """
        初始化数据库管理器
        :param db_path: SQLite数据库文件路径，默认使用db/app.db
        """
        self.db_path = db_path or DEFAULT_DB_PATH
        self._ensure_db_directory()

    def _ensure_db_directory(self):
        """确保数据库目录存在"""
        db_dir = os.path.dirname(self.db_path)
        if not os.path.exists(db_dir):
            os.makedirs(db_dir)
            logger.info(f"创建数据库目录: {db_dir}")

    def _get_connection(self):
        """获取数据库连接"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def execute_query(self, sql: str, max_results: int = 100) -> List[Dict[str, Any]]:
        """执行查询并返回结果"""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # 添加LIMIT限制结果数量
            sql_clean = sql.strip().rstrip(';')
            if 'limit' not in sql_clean.lower():
                sql_with_limit = f"{sql_clean} LIMIT {max_results}"
            else:
                sql_with_limit = sql_clean

            logger.info(f"执行SQL查询: {sql_with_limit}")
            cursor.execute(sql_with_limit)
            results = cursor.fetchall()

            # 将sqlite3.Row转换为字典列表
            return [dict(row) for row in results]

        except Exception as e:
            logger.error(f"SQL查询执行失败: {e}")
            raise
        finally:
            if conn:
                conn.close()

    def execute_ddl(self, sql: str) -> bool:
        """执行DDL语句（CREATE, ALTER, DROP等）"""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            logger.info(f"执行DDL: {sql[:100]}...")
            cursor.execute(sql)
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"DDL执行失败: {e}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()

    def execute_insert(self, sql: str, parameters: tuple = None) -> int:
        """执行INSERT语句并返回最后插入的ID"""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            logger.info(f"执行INSERT: {sql[:100]}...")
            if parameters:
                cursor.execute(sql, parameters)
            else:
                cursor.execute(sql)
            conn.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.error(f"INSERT执行失败: {e}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()

    def get_tables(self) -> List[str]:
        """获取所有表名"""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            results = cursor.fetchall()
            return [row[0] for row in results]
        except Exception as e:
            logger.error(f"获取表列表失败: {e}")
            raise
        finally:
            if conn:
                conn.close()

    def get_table_schema(self, table_name: str) -> List[Dict[str, Any]]:
        """获取表结构信息"""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA table_info({table_name})")
            results = cursor.fetchall()
            return [dict(row) for row in results]
        except Exception as e:
            logger.error(f"获取表结构失败: {e}")
            raise
        finally:
            if conn:
                conn.close()
