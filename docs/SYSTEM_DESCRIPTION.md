# QueryForge 系统描述文档

> 当前系统（2026-08 重构后）的权威功能与架构说明。部署见 DEPLOYMENT.md，AI 维护速查见 AI_MEMORY.md。

## 1. 系统定位

QueryForge 是公司内部的**自然语言数据查询平台**：用户用中文提问，系统基于已导入的数据库结构（Schema）检索字段，调用大模型生成 SQL，经权限网关校验后返回结果。核心价值：业务人员无需懂 SQL 即可查数，且数据不出内网。

## 2. 功能模块

### 用户侧（`/`，登录后）
- **SQL 对话**（chatSQL/chat.html）：新建对话时选库（自动带出数据库类型）→ 提问 → 多轮连续对话迭代 SQL
- **知识库**：补充业务口径/表关系/计算规则，生成 SQL 时注入提示词
- **使用记录**：个人 LLM 调用日志

### 管理侧（`/admin`，仅管理员）
- **数据浏览**：数据源→库→表→字段级联查看/搜索/分页；CSV 模板下载与上传导入；库/表/字段删除（均带确认与数据源同步提示）
- **向量索引**：BGE-M3 向量索引构建与管理（字段召回）
- **模型管理**：模型配置（OpenAI 兼容 API，密钥 Fernet 加密）、调用日志
- **元数据同步**：数据源（MySQL/PostgreSQL/SQLite）→ 同步任务（调度/手动）→ 执行历史 → 变更记录（新增自动应用、删除待审批）；支持一键清空历史
- **用户管理**：管理员创建/编辑/启停/重置密码/删除用户（级联清理授权/对话/模型配置）
- **权限管理**：数据源→库→表→字段→知识库 五层授权；字段级 SELECT/FILTER/NONE + 行级过滤规则
- **安全审计**：审计概览/日志、敏感字段分级（公开/内部/敏感/机密）、行级规则
- **驱动管理**：数据库驱动状态与一键安装
- **系统设置**：JWT/向量参数/站点品牌（Logo、站点名）等

## 3. 核心架构

```
用户提问 → 关键词提取 + 向量召回（BGE-M3）→ 按表聚合 Schema 上下文
        → LLM 生成 SQL（OpenAI 兼容 API）→ SQL 权限网关（AST 字段级校验 + 行级注入）
        → 返回结果 + 审计记录（query_audit_logs）+ LLM 遥测（llm_telemetry.db）
```

- **认证**：JWT（HttpOnly cookie），`pwd_ts` 令牌撤销；管理员/普通用户双层依赖
- **权限网关**（services/sql/gateway.py）：SELECT/FILTER/NONE 三级字段权限 + 行级 WHERE 注入，拦截敏感字段越权
- **元数据同步**（services/sync/engine.py）：连接外部库 → 读 information_schema → diff 变更 → 写入四层表 → 变更审批流
- **调度器**：每小时用量聚合、每日遥测清理、每 10 分钟自动同步

## 4. 数据模型（四层）

| 层 | 表 | 说明 |
|---|---|---|
| 数据源 | data_sources | 外部库连接配置（密码加密存储） |
| 库 | db_schemas | 数据库/Schema，`datasource_id` 关联数据源，`db_type` 必填 |
| 表 | db_tables | 表名/注释 |
| 字段 | db_columns | 类型/注释/键/外键/敏感等级/示例值 |

关联：db_schemas → db_tables → db_columns；授权表（user_schema/table/column/knowledge_grants）；安全表（row_scope_rules、query_audit_logs）。

## 5. 安全设计

- 密码 bcrypt 哈希；API Key/数据源密码 Fernet 加密
- JWT 密钥无硬编码兜底（环境变量或系统设置表，缺失拒绝启动）
- 页面守卫：未登录 302 /login，非管理员访问管理模板 403
- CSP `frame-ancestors` 可配置（默认同源）；HTML 禁止缓存；审计日志留痕（audit.log）
- 敏感字段默认权限推导：公开/内部→SELECT、敏感→FILTER、机密→NONE

## 6. 部署与运行

- 本地 venv（Python 3.10）+ `start_server.bat`，端口 8188，日志统一 `logs/`
- 配置见 DEPLOYMENT.md；iframe 嵌入白名单 `QUERYFORGE_FRAME_ANCESTORS`

## 7. 技术栈

FastAPI · SQLAlchemy 2.0 · SQLite(WAL) · sentence-transformers(BGE-M3) · HTML/JS/Bootstrap5 · APScheduler · sqlglot（SQL 解析）
