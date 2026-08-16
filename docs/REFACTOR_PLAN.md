# QueryForge 结构优化设计方案

> 版本: v1 · 2026-08-16 · 状态: 待确认执行范围

---

## 一、现状诊断（按严重度排序）

### 1. 胖路由：schema_router.py 1839 行
一个文件混杂了三种职责：
- 8 种数据库方言的 DDL 解析器（MySQL/PostgreSQL/Oracle/SQLServer/Hive/Doris/ClickHouse/SQLite）≈ 1000 行
- 向量索引管理（构建/状态/列表）
- Schema CRUD + 文件上传 + 导出

新增一种方言 = 在路由文件里继续堆代码，无法单测，无法复用。

### 2. LLM 数据放置不合理（token / 对话 / 日志混装）

`llm_logs` 一行 = 一次调用，但把**大文本和指标混在一行**：
- `system_prompt`（含完整表结构 CSV，单条可达数十 KB）每次调用全量重复存储
  → 1000 次调用 = 1000 份几乎相同的 schema 上下文，日志库膨胀最快的正是这个
- token 明细存在这里没错，但**没有聚合层** → 查"本月各模型 token 消耗"要全表扫描大文本行
- `conversation_messages` 与 `llm_logs` **无外键关联** → 想知道"这条 SQL 回复花了多少 token/钱"只能靠时间戳猜
- `question`（用户问题）在 llm_logs 里和 conversation_messages.content 重复存了一份

### 3. Schema 表：一行一个字段（反范式过度）

```
schema 表 = (user_id, schema_name, table_name, column_name, column_type, column_key, foreign_key) 7 列联合唯一
```
- 库名/表名/表注释在每个字段行上重复 → 一个 50 表 × 20 列的库，表名冗余 1000 遍
- 所有列表/统计页面都在 GROUP BY，索引效率低
- 表级操作（改表注释、删表）要更新 N 行

### 4. 5 个 SQLite 文件分离的代价
- 跨库无法 JOIN、无法建外键（`conversations.schema_name` 是裸字符串、`llm_config_id`/`knowledge_id` 是裸整数）
- 每个业务操作要开多个 session 手工对齐，权限表 `user_schemas` 用字符串关联，无完整性保证
- SQLite 单文件 + WAL 在本项目规模下完全够用，拆 5 个文件只换来复杂度

### 5. 其他
- `llm_configs.api_key` **明文存储**（Text）
- `SystemConfig` KV 表混装：SECRET_KEY（密钥）、EMBEDDING_MODEL_PATH（运行时缓存）、VECTOR_INDEX_THRESHOLD（业务参数）三类东西
- `scheduler/` 是空壳 —— 定时聚合统计、日志清理这些天然适合它的任务没人做
- `main.py` 模块级创建 app，无 app factory；`reload=True` 与 `workers=10` 互斥（uvicorn 会警告并忽略 workers）
- 无 tests/ 目录

---

## 二、目标设计

### 2.1 Token / 对话 / LLM 调用的正确放置（核心答案）

四层结构，各司其职：

```
┌─────────────────────────────────────────────────────┐
│ 明细层  llm_calls        一次 API 调用一行，只存指标  │
│         (tokens, cost, duration, status)             │
│ 去重层  llm_prompts      system_prompt 按 hash 去重  │
│         相同 schema 上下文的 N 次调用共享一行         │
│ 关联层  conversation_messages.llm_call_id            │
│         消息 ↔ 调用直连，token/成本即时可查           │
│ 聚合层  llm_usage_stats  按 天×用户×模型 汇总         │
│         scheduler 定时刷新，看板直接查这张小表        │
└─────────────────────────────────────────────────────┘
```

**llm_calls**（替代 llm_logs，瘦身版）：
```sql
id, user_id, conversation_id, message_id,
config_id, provider, model, purpose,        -- chat_sql | single | test
prompt_id,                                   -- → llm_prompts（大文本去重）
prompt_tokens, completion_tokens, total_tokens,
cost, duration_ms, status, error_message, created_at
```

**llm_prompts**（新增，去重存储）：
```sql
id, content_hash UNIQUE, content TEXT, length, created_at
```

**llm_usage_stats**（新增，聚合表）：
```sql
id, stat_date, user_id, model, provider,
call_count, success_count, prompt_tokens, completion_tokens, total_tokens, cost
UNIQUE(stat_date, user_id, model)
```

**conversations / conversation_messages**（保留，修关联）：
```sql
conversations:  schema_name(字符串) → schema_id(FK)
                新增 context_prompt_id → llm_prompts（首轮确定的 schema 上下文，去重存一次）
conversation_messages:  新增 llm_call_id → llm_calls（该回复的 token/成本直查）
```

**效果举例**：
- 「这个月每个模型花了多少 token」→ 查 llm_usage_stats（毫秒级，几十行）
- 「这条回复为什么贵」→ message.llm_call_id → llm_calls → llm_prompts 看完整上下文
- 日志库体积：system_prompt 从 N 份 → 1 份，预计缩小 80%+

### 2.2 Schema 三层模型（替代一行一字段）

```sql
db_schemas:  id, owner_user_id FK, name, db_type, description, source, created_at, updated_at
db_tables:   id, schema_id FK, name, description, created_at     -- 表级信息只存一次
db_columns:  id, table_id FK, ordinal, name, data_type,
             description, is_nullable, default_value, column_key, foreign_key, sample_values
```
- 列表页直接查三层，不再 GROUP BY
- 表注释/删除表 = 一行操作
- vector_index_meta 挂 schema_id（替代 schema_name 字符串）
- 权限 grants 挂 schema_id

### 2.3 双库按写强度拆分（用户已确认）

经与用户确认（曾遇到"查看记录被其他写进程卡住"），采用**按写强度拆两个文件**，而不是单库：

| 库 | 文件 | 内容 | 写特征 |
|----|------|------|--------|
| 主库 | `db/queryforge.db` | users / grants / llm_configs(加密) / db_schemas三层 / knowledge_items / conversations+messages / vector_index_meta / llm_usage_stats / system_settings | 交互域，短事务 |
| 遥测库 | `db/llm_telemetry.db` | llm_calls / llm_prompts | 每次 LLM 调用追加一条，高频写，物理隔离 |

两库均 WAL + busy_timeout=5000 + synchronous=NORMAL；主库开启 FOREIGN KEY 约束。
跨库引用（conversation_messages.llm_call_id → llm_calls.id、conversations.context_prompt_id → llm_prompts.id）为**逻辑引用**（裸整数，不建跨库 FK），由 services/llm/telemetry.py 统一维护。

历史"卡住"问题的真正根因（长事务持锁 / 未全路径覆盖 WAL / 独立进程并发写）已在本次重构中一并处理：
所有 session 使用统一工厂、事务极短、busy_timeout 全引擎生效。

> 存量数据：按用户决定**全新空库开始**，旧 5 库文件保留在 db/ 下不导入。

### 2.4 目标目录结构

```
query-forge/
├── main.py                        # 仅启动入口（≤30 行）
├── app/
│   ├── factory.py                 # create_app() 装配、lifespan
│   ├── config.py                  # pydantic-settings 分层配置
│   ├── deps.py                    # get_db / get_current_user 共享依赖
│   ├── security/                  # auth.py / permissions.py / crypto.py(api_key 加解密)
│   ├── logging.py / limiter.py / middleware.py
├── api/v1/                        # 薄路由层，每文件 ≤300 行，只做参数校验+调服务
│   ├── auth.py  users.py  conversations.py
│   ├── schemas.py                 # Schema CRUD
│   ├── schema_import.py           # DDL/JSON 解析入口
│   ├── vector_index.py            # 向量索引管理（独立）
│   ├── knowledge.py  llm_configs.py  llm_logs.py  system.py
├── services/                      # 业务逻辑层（router 不再写业务）
│   ├── llm/                       # client.py(重试/异步) usage.py prompts.py
│   ├── nl2sql/                    # pipeline.py chat_session.py sql_generator.py keywords.py
│   ├── schema/                    # service.py
│   │   └── parsers/               # ★ 方言注册表模式：新增方言=加一个文件
│   │       ├── __init__.py        #   registry: {"mysql": MysqlParser, ...}
│   │       ├── mysql.py postgresql.py oracle.py sqlserver.py
│   │       ├── datawarehouse.py   #   hive/doris/clickhouse 共用骨架
│   │       └── json_formats.py    #   spider/自定义 JSON
│   ├── vector/                    # embedder.py store.py index_service.py
│   └── conversation_service.py
├── models/                        # ORM：base.py + user.py llm.py conversation.py schema.py knowledge.py system.py
├── db/                            # 运行数据（单库 + vectors/）
├── migrations/                    # 迁移脚本（旧5库 → 新库）
├── scheduler/jobs/                # usage_stats.py(token聚合) retention.py(日志清理)
├── static/  templates/            # templates 从 static/template 提出（路径统一）
├── scripts/ tests/
```

### 2.5 其他修复
- `api_key` 用 Fernet 对称加密落库（密钥来自 SECRET_KEY 派生）
- `SystemConfig` 拆分语义：密钥类进安全配置，模型路径缓存进运行时状态，业务参数带 category/editable 标记
- `main.py`: 修 reload/workers 冲突；app factory 支持测试时创建独立实例
- scheduler 落地两个真实任务：token 用量聚合、llm_calls 过期归档

---

## 三、分阶段执行计划（每阶段可独立回退）

| 阶段 | 内容 | 风险 |
|------|------|------|
| P1 模块拆分 | schema_router 拆出 parsers 包 + vector_index 独立路由；行为零变化 | 低 |
| P2 数据库重构 | 新表模型 + 单库 engine + 迁移脚本 + LLMClient 埋点改造 | 中 |
| P3 配置安全 | pydantic-settings、api_key 加密、SystemConfig 分类 | 低 |
| P4 收尾 | 目录规整、scheduler 任务、冒烟测试 | 低 |
