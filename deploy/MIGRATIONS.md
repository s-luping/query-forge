# 迁移清单（MIGRATIONS）

本文件登记**表结构的所有变更**，与 `deploy/schema_main.sql` / `deploy/schema_telemetry.sql` /
`deploy/schema_logs.sql`（由 `scripts/gen_schema_sql.py` 从 ORM 元数据自动生成）配合使用。

## 使用方式

| 场景 | 做法 |
|---|---|
| 全新部署 | 执行 `deploy/schema_main.sql` + `deploy/schema_telemetry.sql` + `deploy/schema_logs.sql` 建表，再跑种子数据 |
| 存量 SQLite 库升级 | 启动时 `db/sqlite_hooks.py` 的轻量迁移自动补齐（幂等） |
| 改表结构 | 改 `models/` 下 ORM 定义 → 运行 `python scripts/gen_schema_sql.py` → 在本文件登记 |
| CI 防漂移 | `scripts/ci_guard.py` 检查项 6 比对 SQL 与 ORM，不同步即失败 |

## 一、基线建表（schema_main.sql / schema_telemetry.sql / schema_logs.sql）

由 ORM 元数据自动生成，与 `models/` 定义严格同源（CI 校验）。三库分离——
主库 17 张表、遥测库 2 张表、日志库 3 张表：

- **主库**（业务+元库，`queryforge.db`）：`users` / `roles` / `user_roles` /
  `role_permissions` / `db_schemas` / `db_tables` / `db_columns` /
  `db_table_relations` / `data_sources` / `knowledge_items` / `conversations` /
  `conversation_messages` / `llm_configs` / `llm_usage_stats` / `system_settings` /
  `vector_index_meta` / `sync_job_configs`
- **遥测库**（LLM 调用，`llm_telemetry.db`）：`llm_calls` / `llm_prompts`
- **日志库**（审计+同步历史，`logs.db`）：`query_audit_logs` / `sync_run_logs` /
  `schema_change_logs`

基线 DDL 已通过空库执行验证，且与 SQLAlchemy `create_all` 产出逐对象一致
（58 + 10 个库对象，三库拆分后为 17 + 2 + 3 张表）。

## 二、存量 SQLite 库增量迁移（db/sqlite_hooks.py）

以下迁移仅对**已存在的旧 SQLite 文件**生效（`ALTER TABLE ADD COLUMN` 幂等）；
新库由基线 DDL 直接建全量表，不经过这些路径。启动时由 `db/database.py::init_database`
按序调用：

| # | 函数 | 表 | 变更 | 说明 |
|---|---|---|---|---|
| 1 | `_ensure_column_sqlite` | `conversation_messages` | + `result_data TEXT` | 查询结果集落库 |
| 2 | `_ensure_column_sqlite` | `knowledge_items` | + `knowledge_type VARCHAR(50)` | 知识 typed 结构化 |
| 3 | `_ensure_column_sqlite` | `knowledge_items` | + `aliases TEXT` | 别名召回 |
| 4 | `_ensure_column_sqlite` | `knowledge_items` | + `payload TEXT` | 结构化内容 |
| 5 | `_ensure_column_sqlite` | `knowledge_items` | + `scope_schema_id INTEGER` | 知识库可见范围绑定 |
| 6 | `_migrate_relation_cross_db` | `db_table_relations` | + `left_schema_id` / `right_schema_id INTEGER`；重建唯一索引 `uix_relation_both_sides`（6 列复合）；`schema_id` 置可空（整表重建） | 表关系支持同数据源跨库；存量行用旧 `schema_id` 回填左右两侧 |
| 7 | `_ensure_column_sqlite` | `conversations` | + `schema_tables TEXT` | 首轮召回表集合，供追问轮累积 |
| 8 | `_ensure_column_sqlite` | `conversations` | + `knowledge_ids TEXT` | 多知识库（JSON 数组） |
| 9 | `_ensure_indexes_sqlite` | `db_columns` | 补 `ix_db_columns_sensitive_level` | `create_all` 不为存量表补索引 |
| 10 | `_ensure_telemetry_indexes` | `llm_calls`（遥测库） | 补 `ix_llm_calls_status` / `ix_llm_calls_purpose` | 同上 |
| 11 | `_ensure_logs_indexes` | 日志三表（日志库） | 补 `was_blocked` / `hit_sensitive` / `approval_status` / `change_type` 四个索引 | 日志三表拆库后，索引随库搬迁 |
| 12 | `_migrate_logs_tables` | `query_audit_logs` / `sync_run_logs` / `schema_change_logs` | **整表归档**：主库 → 日志库（ORM 搬迁，显式保留 id，缺列按零值兜底），迁后 DROP 主库旧表 | 日志域拆分；幂等（主库无表即跳过）。跨库外键同步降级：`user_id` / `job_id` / `datasource_id` 改为普通索引列，删除用户/任务/数据源由 crud 层显式级联清理 |

> 注：以上列变更**均已纳入基线 DDL**（ORM 模型中已定义这些列），
> 因此全新库建表即包含全部字段；本清单仅说明存量库的补齐路径，防止误以为"改列只改了一半"。

## 二之二、日志域拆分（三库分离）

`query_audit_logs` / `sync_run_logs` / `schema_change_logs` 三张追加型高频写表
从主库拆至独立日志库 `logs.db`（`LogsBase`），与主库（配置/元数据/业务）
物理隔离。要点：

1. **跨库外键降级**：原 `user_id → users.id`、`job_id → sync_job_configs.id`、
   `datasource_id → data_sources.id` 三个跨库外键改为普通索引列
   （SQLite 跨文件无外键），删除用户/同步任务/数据源时由 crud 层显式级联清理
   （`user_router` / `crud.sync.delete_cascade` / `crud.datasource.delete_cascade`）；
   `schema_change_logs.run_log_id → sync_run_logs.id` 为库内引用，保留外键。
2. **会话路由**：`crud.base.session_scope(logs=True)` / `tx_scope(logs=True)` 绑日志库；
   `BaseCrud` 子类声明 `default_db = 'logs'` 后通用方法自动走日志库。
3. **同步引擎事务**：`sync_engine.run()` 拆为「日志库先行落 run_log 拿主键 →
   主库事务应用元数据 → 日志库记录变更 → 日志库完成 run_log → 主库更新任务状态」，
   两库无分布式事务，主库失败时日志库 run_log 标记 failed。
4. **定时清理**：新增 `cleanup_logs_db` 作业（每天 03:10，审计/同步历史 90 天）；
   `cleanup_main_db` 只保留 `result_data` 30 天清理；`wal_checkpoint` 增加日志库。
5. **外部数据库模式**：日志库与主库同址（同 `DATABASE_URL`），仅靠 Base 隔离，
   不产生额外库文件；SQLite 模式为独立 `db/logs.db`。

## 三、外部数据库（MySQL / PostgreSQL）

不经过 SQLite 轻量迁移：`init_database` 对非 SQLite 仅执行 `create_all`
（建全量表，含全部索引）。切换到外部库只需修改 `app/config.py` 的 `DATABASE_URL`，
基线 DDL 可作为审查参考（SQLite 方言，类型映射需按目标库调整）。

## 四、变更登记规范

1. 每次改 `models/` 必须同步：
   - 重新生成 `deploy/*.sql`（`python scripts/gen_schema_sql.py`）；
   - 若涉及存量库兼容，在 `db/sqlite_hooks.py` 增加幂等迁移，并在本文件第二节登记；
   - 在 `docs/资产总表.md` 表清单登记新表（CI 检查项 4 强制）。
2. 禁止只改一边：ORM 与 `deploy/*.sql` 漂移会被 CI 检查项 6 拦截。
