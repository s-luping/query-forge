# QueryForge 目录架构扁平化重构 - 完成报告

## 概述

本次工作对 QueryForge 项目进行了目录架构扁平化重构，解决了"目录太多、层级太深、代码关系混乱"的问题。同时移除了临时性功能（数据库切换迁移），将系统还原为纯 SQLite 存储。

## 完成事项

### 1. 移除数据库切换功能（还原纯 SQLite）

用户明确表示"将处理临时任务的功能都去掉，如 sqlite 数据库迁移外部等等"。

- **`app/config.py`**：移除 `DATABASE_URL`、`DB_IS_SQLITE`、`DB_DIALECT` 环境变量读取，简化为纯 SQLite 路径
- **`db/database.py`**：移除统一引擎创建、密码脱敏、通用迁移逻辑，还原为纯 SQLite + PRAGMA 方式

### 2. `core/` 目录扁平化（3 子目录 → 0）

| 原路径 | 新路径 |
|--------|--------|
| `core/llm/client.py` | `core/llm_client.py` |
| `core/generation/audit.py` | `core/gen_audit.py` |
| `core/generation/chat.py` | `core/gen_chat.py` |
| `core/generation/pipeline.py` | `core/gen_pipeline.py` |
| `core/generation/sql_generator.py` | `core/gen_sql.py` |
| `core/retrieval/index_meta.py` | `core/ret_index_meta.py` |
| `core/retrieval/keywords.py` | `core/ret_keywords.py` |
| `core/retrieval/retriever.py` | `core/ret_retriever.py` |
| `core/retrieval/vector_store.py` | `core/ret_vector_store.py` |

### 3. `services/` 目录扁平化（5 子目录 → 0）

| 原路径 | 新路径 |
|--------|--------|
| `services/llm/telemetry.py` | `services/telemetry.py` |
| `services/sql/gateway.py` | `services/sql_gateway.py` |
| `services/sql/executor.py` | `services/sql_executor.py` |
| `services/vector/service.py` | `services/vector_service.py` |
| `services/schema/service.py` | `services/schema_service.py` |
| `services/schema/parsers/` (3 文件) | `services/schema_parsers.py` (合并) |
| `services/sync/engine.py` | `services/sync_engine.py` |
| `services/sync/diff.py` | `services/sync_diff.py` |
| `services/sync/classify.py` | `services/sync_classify.py` |
| `services/sync/connectors/` (4 文件+__init__) | `services/sync_connectors.py` (合并) |

### 4. `app/` 扁平化 + 拼写修正

- `app/security/crypto.py` → `app/crypto.py`（消除单文件子目录，删除 `app/security/`）
- `curd/` → `crud/`（拼写修正），所有文件 docstring 同步更新

### 5. 全局 import 批量重写

使用 `find + sed` 批量重写全项目 12 种 import 模式，确保所有引用路径与新结构一致。

## 最终目录结构

```
query-forge/
├── app/                    # 应用层
│   ├── routers/           # 15 个路由文件（保留子目录）
│   ├── config.py           # 配置
│   ├── crypto.py           # 加密（原 app/security/crypto.py）
│   ├── auth.py             # 认证
│   └── ...
├── core/                   # 核心业务逻辑（完全扁平，0 子目录）
│   ├── llm_client.py       # LLM 客户端
│   ├── gen_sql.py          # SQL 生成
│   ├── gen_pipeline.py     # 生成管线
│   ├── gen_chat.py         # 对话
│   ├── gen_audit.py        # 审计日志
│   ├── ret_keywords.py     # 关键词提取
│   ├── ret_retriever.py    # 检索器
│   ├── ret_vector_store.py # 向量存储
│   └── ret_index_meta.py   # 索引元数据
├── crud/                   # 数据访问层（12 文件）
├── db/                     # 数据库引擎（按角色拆分）
│   ├── engine.py           # 引擎与会话工厂（方言自适应 SQLite/MySQL/PG）
│   ├── sqlite_hooks.py     # SQLite 专用 PRAGMA 与轻量迁移
│   ├── seed.py             # 种子数据（系统配置/管理员/角色）
│   └── database.py         # 编排层（get_setting + init_database）
├── models/                 # 数据模型（12 文件）
├── services/               # 业务服务层（完全扁平，0 子目录）
│   ├── telemetry.py        # 遥测
│   ├── sql_gateway.py      # SQL 网关
│   ├── sql_executor.py     # SQL 执行器
│   ├── vector_service.py   # 向量服务
│   ├── schema_service.py   # Schema 服务
│   ├── schema_parsers.py   # Schema 解析器（合并文件）
│   ├── sync_engine.py      # 同步引擎
│   ├── sync_diff.py        # 同步差异
│   ├── sync_classify.py    # 同步分类
│   └── sync_connectors.py  # 同步连接器（合并文件）
├── scheduler/              # 定时任务
│   └── jobs/               # 3 个任务文件（保留子目录）
├── scripts/                # 脚本
└── static/                 # 前端资源
```

## 变更统计

| 指标 | 重构前 | 重构后 |
|------|--------|--------|
| core/ 子目录数 | 3 | 0 |
| services/ 子目录数 | 5 | 0 |
| 最大目录深度 | 3 层 | 2 层 |
| app/security 子目录 | 存在 | 已消除 |
| curd 拼写 | 错误 | 已修正 (crud) |
| 数据库切换功能 | 纯 SQLite | 支持 MySQL/PostgreSQL（环境变量切换） |
| schema_parsers 文件数 | 3 | 1 (合并) |
| sync_connectors 文件数 | 4+1 | 1 (合并) |

## db/ 模块按角色拆分

`db/database.py` 拆分为 4 个角色模块，每个文件职责单一：

| 文件 | 职责 | 适用范围 |
|------|------|---------|
| `db/engine.py` | 引擎与会话工厂（方言自适应） | 所有数据库 |
| `db/sqlite_hooks.py` | PRAGMA 优化 + 轻量迁移 | 仅 SQLite |
| `db/seed.py` | 系统配置/管理员/角色种子数据 | 所有数据库 |
| `db/database.py` | 薄编排层（get_setting + init_database） | 所有数据库 |

### 多数据库切换配置

设置环境变量即可切换，无需改代码：

```bash
# 默认 SQLite（不设置）
python main.py

# 切换 MySQL
DATABASE_URL=mysql+pymysql://user:pass@host:3306/queryforge?charset=utf8mb4 python main.py

# 切换 PostgreSQL
DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/queryforge python main.py
```

- `TELEMETRY_DATABASE_URL` 可单独指定遥测库（留空时外部数据库与主库同址，通过 ORM Base 隔离表）
- `engine.py` 自动检测方言：SQLite 附加 PRAGMA 钩子，外部数据库用 `pool_pre_ping` 防陈旧连接
- `_mask_url()` 脱敏 URL 中的密码，日志安全

## 验证结果

- **13/13 import 检查全部 PASS**（含 _mask_url 脱敏、_resolve_urls MySQL 模式模拟）
- **init_database() 全流程验证**：24 主库表 + 2 遥测表 + admin 用户 + 8 系统配置
- core/ 10 个模块导入正确
- services/ 10 个模块导入正确
- crud.base / crud.user 导入正确
- config.py DATABASE_URL / TELEMETRY_DATABASE_URL 环境变量正常

## 备注

- `app/routers/` 和 `scheduler/jobs/` 保留子目录结构，因文件数量多（15 和 3 个），分层有合理意义
- 早期会话中完成的安全修复（Pickle RCE 消除、SSRF 防护、全局异常处理等）保持不变
- 早期会话中完成性能优化（TTLCache、N+1 消除、时区修复等）保持不变
- Git commit: `948836d` (80 files, +1322 -2332)
