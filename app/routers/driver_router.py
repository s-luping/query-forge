# -*- coding: UTF-8 -*-
"""数据库驱动管理 — 查看各数据库连接驱动安装状态，缺失时一键安装

- 驱动通过 pip 安装到当前服务进程的解释器（sys.executable），装完立即生效
- 仅管理员可访问（AdminUser 依赖）
- 只允许安装驱动目录内预定义的包，杜绝任意 pip 注入
"""
import importlib
import subprocess
import sys
from typing import List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.auth import AdminUser
from app.logger import logger, log_audit

router = APIRouter()

# 驱动目录：应用支持的数据库连接驱动（同步/连接/预留）
# builtin=True 表示 Python 内置模块（无需安装）
DRIVER_CATALOG = [
    {"module": "pymysql", "package": "pymysql", "db_type": "mysql",
     "display": "MySQL", "builtin": False},
    {"module": "pymysql", "package": "pymysql", "db_type": "mariadb",
     "display": "MariaDB", "builtin": False},
    {"module": "pymysql", "package": "pymysql", "db_type": "doris",
     "display": "Doris（MySQL 协议）", "builtin": False},
    {"module": "psycopg2", "package": "psycopg2-binary", "db_type": "postgresql",
     "display": "PostgreSQL", "builtin": False},
    {"module": "sqlite3", "package": "", "db_type": "sqlite",
     "display": "SQLite（内置）", "builtin": True},
    {"module": "pyodbc", "package": "pyodbc", "db_type": "sqlserver",
     "display": "SQL Server", "builtin": False},
    {"module": "oracledb", "package": "oracledb", "db_type": "oracle",
     "display": "Oracle", "builtin": False},
    {"module": "clickhouse_connect", "package": "clickhouse-connect", "db_type": "clickhouse",
     "display": "ClickHouse", "builtin": False},
    {"module": "pyhive", "package": "pyhive", "db_type": "hive",
     "display": "Hive", "builtin": False},
    {"module": "pymongo", "package": "pymongo", "db_type": "mongodb",
     "display": "MongoDB（预留）", "builtin": False},
    {"module": "redis", "package": "redis", "db_type": "redis",
     "display": "Redis（预留）", "builtin": False},
]


def _probe(module_name: str):
    """探测模块是否可导入，返回 (installed, version)"""
    try:
        mod = importlib.import_module(module_name)
    except Exception:
        return False, ''
    version = (getattr(mod, '__version__', '')
               or getattr(mod, 'version', '')
               or getattr(mod, 'VERSION', '')
               or '')
    return True, str(version)


class DriverItem(BaseModel):
    module: str
    package: str
    db_type: str
    display: str
    builtin: bool
    installed: bool
    version: str


class DriverListResponse(BaseModel):
    python: str          # 当前服务解释器（驱动将安装到此解释器）
    items: List[DriverItem]


class InstallRequest(BaseModel):
    package: str


@router.get("/list", response_model=DriverListResponse)
def list_drivers(user: AdminUser):
    """列出支持的数据库驱动及安装状态"""
    items = []
    for d in DRIVER_CATALOG:
        installed, version = _probe(d["module"])
        items.append(DriverItem(
            module=d["module"], package=d["package"], db_type=d["db_type"],
            display=d["display"], builtin=d["builtin"],
            installed=installed, version=version,
        ))
    return DriverListResponse(python=sys.executable, items=items)


@router.post("/install")
def install_driver(req: InstallRequest, user: AdminUser):
    """一键安装数据库驱动（pip 安装到当前服务解释器）"""
    package = req.package.strip()
    if not package:
        raise HTTPException(status_code=400, detail="缺少要安装的包名")

    allowed = {d["package"] for d in DRIVER_CATALOG if d["package"]}
    if package not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"仅支持安装以下驱动包: {', '.join(sorted(allowed))}")

    logger.info(f"管理员 {user['username']} 安装数据库驱动: {package} "
                f"(python={sys.executable})")
    try:
        proc = subprocess.run(
            [sys.executable, '-m', 'pip', 'install', package],
            capture_output=True, text=True, timeout=300,
        )
        output = ((proc.stdout or '') + (proc.stderr or '')).strip()
        tail = output.splitlines()[-8:]
        log_audit(user, "install_driver",
                  f"package={package} python={sys.executable} code={proc.returncode}")
        if proc.returncode == 0:
            logger.info(f"驱动安装成功: {package}")
            return {"success": True, "message": f"驱动 {package} 安装成功",
                    "output": tail}
        logger.error(f"驱动安装失败: {package}\n{output[-800:]}")
        return {"success": False, "message": f"驱动 {package} 安装失败（详见输出）",
                "output": tail}
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500,
                            detail=f"安装超时（300秒），请稍后重试: {package}")
    except Exception as e:
        logger.error(f"安装驱动异常: {e}")
        raise HTTPException(status_code=500, detail=f"安装失败: {str(e)}")
