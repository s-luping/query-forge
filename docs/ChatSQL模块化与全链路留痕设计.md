# ChatSQL 链路模块化设计与全链路留痕设计

> 版本：v1.0（2026-10-19）
> 定位：ChatSQL 主链路的**模块边界规范**与**留痕规范**，作为后续重构/扩展（多物理库接入、执行反馈自修复等）的实施依据。
> 关联文档：《系统架构设计.md》（总体架构）、《NL2SQL设计与实现.md》（现有链路详解）、《新数据源接入准备清单.md》（异构库接入）。

---

## 1. 设计目标

1. **模块化**：高内聚低耦合。模块之间影响最小化——改一个模块不要求理解/改动另一个模块。
   两个典型隔离要求（本文的硬性红线）：
   - **SQL 生成模块 ↔ 数据源选择/执行模块 隔离**：生成侧只管"把问题变成 SQL"，不感知任何连接、引擎、方言执行细节；
   - **向量召回模块 ↔ 权限模块 隔离**：召回只管"找最相关的"，不感知权限模型；权限以注入数据的方式参与，而不是召回模块反向依赖权限实现。
2. **全链路留痕**：任何一次提问——出错、结果不对、被拦截、空结果——都能**只看记录**定位到"哪一步出了问题、为什么"，不需要复现。
3. **多物理库就绪**：模块边界按"MySQL / Oracle / Doris 等多类型数据源并存"设计，接入新库不改链路骨架。

---

## 2. 模块划分与依赖方向

### 2.1 模块地图

```
┌────────────────────────── 编排层（唯一的全链路知情者）──────────────────────────┐
│  conversation_router（HTTP 入口/追问） + core/gen_chat（流程编排 + 步骤留痕）      │
└──────┬───────────────┬───────────────┬───────────────┬───────────────────────┘
       │               │               │               │
   ┌───▼────┐    ┌─────▼─────┐   ┌────▼─────┐   ┌─────▼──────┐
   │ 召回模块 │    │ 生成模块   │   │ 裁决模块  │   │  执行模块   │
   │ ret_*   │    │ gen_sql   │   │sql_gateway│  │sql_executor│
   └───┬────┘    └─────┬─────┘   └────┬─────┘   └─────┬──────┘
       │               │               │               │
   ┌───▼──────────────────────────────────────────────────▼───────┐
   │                    横切模块（被注入，不反向依赖业务模块）            │
   │  permissions（权限三件套） · gen_audit/telemetry（审计/遥测）      │
   │  llm_client（LLM 统一客户端） · system_settings · logger          │
   └──────────────────────────────────────────────────────────────┘
```

| 模块 | 文件 | 职责（只做这些） | 禁止事项 |
|---|---|---|---|
| **编排层** | `app/routers/conversation_router.py`、`core/gen_chat.py` | 参数校验、按顺序调用下游、构建权限上下文、组装结果、驱动留痕 | 不实现任何单步业务逻辑 |
| **召回模块** | `core/ret_retriever.py`、`ret_keywords.py`、`ret_vector_store.py` | 关键词提取、向量/DB 召回、按表聚合、小库直通 | **不 import `app.permissions`**；不知道"角色/授权表"存在 |
| **生成模块** | `core/gen_sql.py`（+ `gen_chat` 的判断/生成调用） | 拼 prompt、调 LLM、产出 SQL 字符串与判断结论 | **不 import 执行侧任何模块**（sql_executor/datasource/engine）；不解析数据源 |
| **裁决模块** | `services/sql_gateway.py` | AST 解析、只读校验、表/字段白名单、禁 SELECT *、行级过滤注入 | 不执行 SQL；不接触引擎/连接 |
| **执行模块** | `services/sql_executor.py` | 前缀修复与路由、建引擎、执行、行数截断 | 不 import 生成侧模块；不理解 prompt/LLM |
| **横切·权限** | `app/permissions.py` | 权限三件套（可见库/表授权/字段 access map）+ TTL 缓存 | 不被召回模块直接 import（由编排层取值后注入） |
| **横切·留痕** | `core/gen_audit.py`、telemetry、`models/security.py` | 审计落库、遥测落库、pipeline_log 回写 | 不改变业务结果（写失败仅告警） |
| **横切·LLM** | `core/llm_client.py` | 统一请求/SSRF/欠费/usage 内核 | 不理解 NL2SQL 语义 |

### 2.2 依赖方向规则（红线）

1. **单向依赖**：只允许 `编排层 → 业务模块 → 横切模块`；禁止业务模块之间互相 import（生成↔执行、召回↔裁决、生成↔召回之间均不得直接依赖）。
2. **数据源知识单向收敛**：host/port/db_type/引擎差异只允许出现在 `sql_executor`（执行侧）与 `sync_engine`（同步侧）；`gen_sql`/`ret_retriever` 看到的"方言"只能是从编排层传入的字符串（如 `dialect='oracle'`），不得自行查 DataSource 表。
3. **权限知识单向收敛**：角色/授权表的读取只允许在 `app/permissions.py`；召回模块消费的是编排层构建好的**权限快照**（见 §3.2），不是 user dict 直接查库。
4. **模块间只通过数据契约通信**（§4 的 result 结构），禁止传 ORM 对象、Session、request 等带副作用的东西跨模块。

---

## 3. 隔离设计（现状差距与改造）

### 3.1 生成 ↔ 执行隔离（现状已满足，固化为契约）

现状核实：`gen_sql.py` 零项目 import；`sql_executor.py` 不 import 任何生成侧模块；执行由编排层（conversation_router 后置步骤）驱动。

**固化规则**：
- 生成模块产出 `GenerationResult`（含 `sql`、`need_more_info`、`error_message` 等），编排层把它交给裁决/执行，生成模块到此为止，**不知道 SQL 之后发生什么**；
- 执行失败**不回灌生成模块自动重试**（若未来实施"执行反馈自修复"，必须由**编排层**发起第二轮生成——新调用、新留痕、步号递增——而不是让执行模块回调生成模块，保持依赖方向不破坏）；
- 方言提示由编排层推断（`gen_chat._resolve_involved_db_type`）后作为参数传入生成 prompt，生成模块不查库确认方言。

### 3.2 召回 ↔ 权限隔离（现状有耦合，本次改造）

**现状**：`core/ret_retriever.py` 顶层 `from app.permissions import ...`，召回内部直接查权限三件套。

**目标**：依赖倒置——权限快照由编排层构建，召回模块只消费快照。

```python
# core/recall_scope.py（新文件，仅数据结构，无业务依赖）
@dataclass
class RecallScope:
    """权限快照：编排层用 permissions 模块构建后传入召回。"""
    visible_schema_ids: Optional[list]              # None=全部可见（admin）
    table_grants: Dict[int, List[int]]              # schema_id -> 可见表 id
    column_access: Dict[int, str]                   # column_id -> SELECT/FILTER/NONE
```

```python
# ret_retriever 改造后签名（语义不变，仅数据来源变化）
def recall_fields(self, keyword: str, schema_name: Optional[str],
                  scope: RecallScope) -> RecallResult: ...
```

改造要点：
1. `ret_retriever` 删除 `app.permissions` import；原权限裁剪逻辑（可见库过滤、字段权限掩码）改为对 `scope` 的纯数据过滤——**裁剪行为逐字段保持不变**；
2. 编排层（gen_chat）在进入召回前调用 `permissions` 三件套构建 `RecallScope`（TTL 缓存照常生效，一次请求内多次构建只命中缓存，无额外查询放大）；
3. 兼容路径：`scope=None` 时表示"admin 全量"，仅允许出现在显式管理场景，chat 链路禁止传 None；
4. 隔离收益：召回模块可单独测试（构造 scope 即可，不需要造角色/授权数据）；权限模型变更（如新增资源类型）不触碰召回代码。

**验证方式**：
- 新增单测 `tests/test_recall_scope.py`：构造同一批字段 + 不同 scope，断言裁剪结果与改造前一致（用改造前的行为做黄金对照）；
- 静态红线检查（§6.3）：`ret_retriever` import 列表断言不含 `app.permissions`。

---

## 4. 模块间数据契约

跨模块只传以下纯数据结构（dict 或 dataclass，可 JSON 序列化）：

| 契约 | 生产者 → 消费者 | 关键字段 |
|---|---|---|
| `RecallScope` | 编排层 → 召回 | 见 §3.2 |
| `RecallResult`（现 aggregation dict） | 召回 → 编排层 → 生成 | `tables[]`（含 table/column/relations/敏感等级/full_scope 标记）、`recalled_count`、`permission_stats` |
| `JudgeResult` | 生成 → 编排层 | `feasible`、`error_message`（拦截原因，含权限归因） |
| `GenerationResult` | 生成 → 编排层 | `sql`、`dialect`、`prompt`、`llm_call_id` |
| `GatewayResult` | 裁决 → 编排层 | `ok`、`rewritten_sql`、`reason`（拦截原因：无表权限/字段 NONE/写语句/SELECT *）、`row_filter_applied` |
| `ExecutionResult` | 执行 → 编排层 | `columns`、`rows`、`row_count`、`truncated`、`schema`（实际路由库）、`datasource_type`、`error` |

约定：
1. 每个契约里**凡是会被留痕的字段必须是可 JSON 序列化的标量/数组**，禁止塞 ORM 对象；
2. 失败也走同一契约（如 `GatewayResult(ok=False, reason=...)`），**不允许用异常做正常业务分支**（异常仅用于真正意外错误，由编排层兜底留痕后转 5xx）；
3. 契约字段只增不改语义；前端消费的字段（`schema`、`datasource_type` 等）保持向后兼容。

---

## 5. 全链路留痕设计

### 5.1 留痕的四个 sink（现状已有，统一规范）

| sink | 存储 | 记什么 | 谁看 |
|---|---|---|---|
| **pipeline_log（步骤链）** | `query_audit_logs.pipeline_log`（logs 库） | 每一步的 StepTrace JSON | 管理员：安全审计 → 链路追踪弹窗 |
| **遥测** | `llm_prompts` / `llm_calls`（遥测库） | 每次调用的全文 prompt、token、耗时、conditions（实际路由库+类型） | 使用记录页（llm_logs） |
| **对话消息** | `conversation_messages`（主库） | 召回表集合、SQL、结果数据（含 schema/datasource_type）、permission_note、llm_call_id 回填 | 用户自己：对话气泡 |
| **执行审计** | `query_audit_logs`（logs 库） | 最终 SQL、审计步（SQL_EXECUTE 带 schema/datasource_type）、审计操作 | 安全审计页 |

原则：**一条用户提问 = 一条 query_audit_logs = 完整 pipeline_log**；追问轮追加到同一会话，但每轮生成新的审计记录与独立 pipeline_log。

### 5.2 StepTrace 统一结构（本次规范新增）

pipeline_log 现有 `{step, timestamp, data}` 升级为统一结构（**向后兼容：无新字段的历史记录按 status=ok 展示**）：

```json
{
  "step": "STEP2_RECALL",
  "status": "ok",              // ok | error | intercept | skip
  "started_at": "2026-10-19T22:30:01+08:00",
  "duration_ms": 812,
  "summary": "召回 128 字段 / 16 表",       // 一句话，列表页直接可读
  "detail": { ... },                        // 该步的关键数据（见下表）
  "error": null                              // status=error/intercept 时必填，人话原因
}
```

**每步必记内容**（detail 的最低要求，允许超集）：

| step | status 取值 | detail 必含 | error 必含 |
|---|---|---|---|
| AUTH_SCHEMA_CHECK | ok/intercept | schema_name、is_visible | 库不可见的归因 |
| LLM_CONFIG_LOAD | ok/error | llm_config_id、model、thinking_mode | 无可用模型/欠费 |
| KNOWLEDGE_LOAD | ok | global_count、user_pinned、selected_ids | — |
| STEP1_KEYWORDS | ok | keywords[] | — |
| STEP2_RECALL | ok/error | recall_mode（vector/db_fallback/full_scope_direct）、field_count、table_count、top_k | 向量加载失败原因 |
| STEP3_AGGREGATE | ok | tables[]、full_scope | — |
| STEP_PERMISSION | ok/intercept | filtered_table_count、none_column_count、filter_column_count | 因权限导致召回为空的归因 |
| STEP_RECALL_KNOWLEDGE | ok | kb_hits[]（id+title） | — |
| STEP_DIALECT_INFER | ok | involved_db_types、resolved_dialect | — |
| STEP4_CONTEXT | ok | prompt_sections[]（注入了哪些段）、csv_chars | — |
| STEP_JUDGE_PROMPT / STEP_JUDGE_RESULT | ok/error | prompt_chars、tokens | 判断步 LLM 异常 |
| STEP5_RESULT | ok/intercept/error | feasible、sql_length、llm_call_id | need_more_info 原因 / 生成失败分类 |
| STEP6_VALIDATE | ok/intercept | sqlglot_dialect、parse_ok | 语法错误 |
| STEP7_GATEWAY | ok/intercept | denied_tables、denied_columns、row_filter_applied | 拦截原因（表/字段/写语句/SELECT *） |
| PREFIX_REPAIR | ok/skip | repaired_tables[]、ambiguity_tables[] | — |
| SQL_EXECUTE | ok/error | datasource_id、schema（实际库）、datasource_type、row_count、truncated、duration_ms | DB 原始错误码+消息 |
| MESSAGE_PERSIST | ok/error | message_id | — |

规范：
1. **status=intercept 与 error 分开**：intercept 是"链路正常但业务上不放行"（信息不足/权限拦截/网关拦截），error 是"这一步本身失败"——前端和归因矩阵据此区分展示；
2. 每步记录 **duration_ms**：慢在哪一步一眼可见（当前只有 LLM 步有耗时，召回/网关/执行是盲区）；
3. `error` 必须是人话+机器可查（如 `"MySQL 1054 Unknown column 'x'"`），禁止只写 `str(e)` 的原始堆栈；
4. pipeline_log 写入失败不得影响主流程（沿用 gen_audit 的 try/except 约定），但要在 app.log 告警。

### 5.3 失败归因矩阵（出错/结果不对时看哪里）

| 现象 | 第一入口 | 定位方法 |
|---|---|---|
| 报错（前端红色错误） | 链路追踪 → 找第一个 `status=error` 的 step | step.error 即根因；LLM 类错误再看 llm_calls 的 conditions/耗时 |
| 结果不对（有数据但值错） | 链路追踪 → STEP2_RECALL 的 detail.tables | ① 该进的表/字段没召回 → 召回问题（调 TopK/补知识库）；② 表对但 SQL 口径不对 → 看 llm_prompts 里实际注入的表结构+知识段（口径类失败沉淀知识库 L2/L4）；③ 表对 SQL 对 → 看 SQL_EXECUTE 实际路由库是否是预期库（前缀修复 PREFIX_REPAIR 是否误判） |
| 空结果 | 对话气泡 permission_note（用户侧）+ 链路追踪 STEP_PERMISSION | 有无行级过滤 → 区分"数据真没有"与"被权限过滤" |
| 被拦截（信息不足） | STEP5_RESULT.error + STEP_PERMISSION | 权限归因（无授权/召回不到/NONE 字段计数）已自动附在 error_message |
| 慢 | 链路追踪各步 duration_ms | LLM 慢看 llm_calls；执行慢看 SQL_EXECUTE.duration_ms |
| 怀疑权限裁剪过度 | STEP_PERMISSION detail | none_column_count/filter_column_count 与授权预期比对 |

### 5.4 前端展示增强

1. **链路追踪弹窗**（security_manage 页，已有入口）：按 §5.2 解析 status/duration_ms/summary——每步一行：`✓ STEP2_RECALL · 812ms · 召回 128 字段/16 表`；intercept 黄色、error 红色并展开 error 全文；detail 可折叠查看；无 status 字段的存量记录按 ok 渲染（兼容）；
2. **对话气泡**（用户侧）：保持现状——SQL、结果表、0 行归因、模型元信息、数据源徽标；**不给普通用户看链路细节**（避免暴露权限拓扑），只给结论性归因；
3. **使用记录页**：不变（遥测视角）。

---

## 6. 实施计划

### 6.1 分期（每期独立可回归）

| 期 | 内容 | 改动面 | 风险 |
|---|---|---|---|
| **P1 留痕统一** ✅ 已实施（2026-10-19） | StepTrace 结构落地：gen_chat/conversation_router 各步补 status/duration_ms/summary/error；PREFIX_REPAIR 步纳入 pipeline_log；前端弹窗解析新结构 | gen_chat.py、conversation_router.py、gen_audit.py（新增 StepTracker）、sql_executor.py（_repair_missing_schema_prefix info 参）、security_manage.js；无表结构变更 | 低（纯增量，向后兼容） |
| **P2 召回/权限解耦** ✅ 已实施（2026-10-19） | 新增 core/recall_scope.py（RecallScope 数据契约 + build_recall_scope 编排层构建器）；ret_retriever 删 app.permissions import，全部权限消费方法加 scope 形参（未传时惰性构建兼容遗留调用方）；gen_chat/两个路由层显式构建传入 | ret_retriever.py、gen_chat.py、新 recall_scope.py、conversation_router.py、knowledge_router.py；+ tests/test_recall_scope.py 9 用例 | 中（已通过：黄金对照 + 隔离性证明 + 全量回归 153 用例） |
| **P3 红线固化** ✅ 已实施（2026-10-19） | tests/test_module_boundaries.py：AST 收集 import 断言 FORBIDDEN_EDGES + 业务模块禁 import app.routers 全局规则 | tests/test_module_boundaries.py（无生产代码改动） | 低（现存代码零违规） |

### 6.2 测试要求

- P1：现有全量套件不回归；补一条"E2E 成功链路 pipeline_log 每个 step 都有 status/duration_ms"断言（可用 TestClient + 假 LLM）；
- P2：`test_recall_scope.py` 以改造前行为为黄金对照（同字段集 × admin/受限/无权三档 scope）；`test_recall_knowledge_bridge.py` 7 用例、`test_dialect_infer.py`、`test_prefix_repair.py` 全部保持通过；
- P3：故意在 gen_sql 里 import sql_executor、在 ret_retriever 里 import permissions 的反向用例被检查拦截。

### 6.3 模块依赖红线（静态检查规则）

```
禁止 import 方向：
  core/gen_sql.py        → services/*, app/permissions            # 生成不碰执行/权限
  services/sql_executor.py → core/gen_sql.py, core/gen_chat.py    # 执行不碰生成
  core/ret_retriever.py  → app/permissions                        # 召回不碰权限（P2 后生效）
  services/sql_gateway.py → services/sql_executor.py             # 裁决不碰执行
  所有业务模块            → app/routers/*                          # 业务模块不反向依赖路由层
```

检查实现建议：`tests/test_module_boundaries.py` 逐文件读 AST（`ast.parse` + 遍历 Import/ImportFrom），断言上述边不存在——不引入新依赖，pytest 直跑。

---

## 7. 多物理库下的模块职责对照（扩展就绪性）

| 关注点 | 归属模块 | 多库时的变化 |
|---|---|---|
| 方言提示（prompt 里怎么写引用符/语法） | 编排层推断 → 生成模块消费 | 新增 db_type 只需扩展 `_resolve_involved_db_type` 的映射与 gen_sql 引用符表 |
| 引擎差异（连接串、驱动、超时参数） | 执行模块 `_build_engine_for_db_type` | 新增 db_type 加一个分支即可 |
| 元数据同步差异 | sync_engine（同步侧，与 chat 链路隔离） | 同上 |
| 权限 | 横切 permissions，与库类型无关 | 授权挂在 DbSchema/DbTable/DbColumn 逻辑层，不感知物理库类型 |
| 前缀路由与跨库边界 | 执行模块 | 已定：一条 SQL 一个引擎，跨异构 JOIN 不支持 |

**验收标准**：接入一个新类型数据源，改动只允许落在——数据源表配置、执行模块引擎分支、方言映射表、同步适配——四处之一；出现任何需要改 gen_sql/ret_retriever/sql_gateway 的情况，视为破坏模块边界，先补契约再接库。

---

## 8. 红线清单（汇总）

1. 业务模块间禁止互相 import；模块间只传 §4 契约；
2. 生成模块不感知数据源/连接/引擎；执行模块不感知 LLM/prompt；
3. 召回模块不 import 权限模块，权限以 `RecallScope` 注入；
4. 数据源物理知识（host/db_type/驱动）只存在于执行模块与同步模块；
5. 每一步必有 StepTrace，error 必须人话可读；留痕写失败不阻塞主流程但必须告警；
6. 执行反馈自修复（未来功能）必须由编排层发起第二轮生成，禁止执行模块回调生成模块；
7. intercept 与 error 语义分离，前端按状态区分展示；
8. 普通用户只见结论性归因，链路细节仅管理员可见。
