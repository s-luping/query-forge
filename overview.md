# 同步调度修复 + 表关系维护 — 完成报告

## 概述

本次工作解决三个问题：同步任务 360 分钟间隔变成 10 分钟执行（重试风暴）、新增「数据管理 → 表关系维护」功能并接入查询链路、全面逻辑审查修复连带 bug。全部验证通过（编译、导入、路由注册、端到端冒烟）。

## 一、同步任务 360 分钟变 10 分钟 — 根因与修复

**根因**（实锤，见 sync_run_logs）：interval=360 的任务失败后：
1. `last_synced_at` 不更新，距上次成功已超 360 分钟 → 每次巡检都判定"到期"；
2. 失败状态在 commit 之后才赋值，未落库 → 巡检线程不知道有任务在跑/刚失败过；
3. 调度器还同步阻塞执行（期间接口卡顿）。

于是形成重试风暴：20:11 起每 10 分钟跑一次、连续 6 次失败、21:11 成功后停止。

**修复**（3 个文件）：

| 文件 | 修复内容 |
|---|---|
| `scheduler/jobs/schema_sync.py` | 到期判定改为「距上次**尝试**时间 ≥ interval」；先标记 running 并提交落库，再派发后台线程（消除派发竞态）；running 超 24h 视为僵死允许重调度 |
| `services/sync_engine.py` | 失败路径改为 merge 后提交，状态正确落库；失败也推进"上次尝试时间" |
| `app/routers/sync_router.py` | interval 必须 ≥10 分钟（对齐巡检周期）；手动触发 30 分钟内 running 状态拒绝重复（并发防护）；编辑时切换数据源的唯一约束校验 |

前端 `sync_manage.html` 间隔输入框增加 `min="10"`。

## 二、表关系维护（新功能）

- **模型**：`models/schema.py` 新增 `DbTableRelation`（schema_id、左/右表+字段、JOIN 类型、关系类型 1:N/1:1/N:1、说明）；`init_database()` 已建表 `db_table_relations`。
- **CRUD**：`crud/schema.py` `RelationCrud` — `exists_same()` 支持**方向颠倒去重**（A.a=B.b 与 B.b=A.a 视为同一条）；查询后 expunge，避免 session 关闭后 DetachedInstanceError。
- **API**：`app/routers/schema_router.py` 新增 `GET/POST/PUT/DELETE /api/schema/relations`（管理员权限，审计日志，表/字段存在性校验，JSON 格式校验）。
- **前端**：`static/template/schema/table_relation.html` + `static/js/table_relation.js`（按库筛选、表/字段下拉联动、编辑回填、删除确认）；`index.html` 数据管理菜单加入口。

**查询链路注入**：`SchemaRetriever.get_relations_text()` 只注入**两侧表都被召回**的关系（防止诱导模型 JOIN 不存在的表），静默降级不阻断主流程。注入点：
- 单轮：`core/gen_pipeline.py` step5 → `gen_sql.generate_sql_prompt()` 新增 `relations_text` 参数；
- 多轮：`core/gen_chat.py` 首轮 system prompt + 追问轮重新召回后追加。

Prompt 中以独立区块【表关系（已人工确认的 JOIN 条件）】呈现，例如：`order.id = order_detail.order_id (INNER JOIN, 1:N) — 订单与订单明细`。

## 三、全面审查发现的连带 bug（已修）

1. **管理员可见性判断错误**：`get_visible_schema_ids()` 对管理员返回 `None`（=全部可见），被当成空列表 → 管理员查不到任何表关系。已区分 `None`（全部）/ `[]`（无权限）两种语义（`ret_retriever.py`、`schema_router.py`）。
2. **DetachedInstanceError 风险**：`SchemaCrud.list_visible()` 返回未 expunge 的 ORM 对象，session 关闭后访问属性会抛异常；且管理员传 `None` 时返回空。已修。
3. **执行记录 Schema 列恒为 '-'**：runs 接口批量补 `schema_name`（避免 N+1），前端对旧记录回退解析 summary JSON。
4. **detached 对象 add 风险**：`sync_engine` 失败路径 `db.add(self._run_log)` 可能重复插入，改用 merge。

## 验证结论

- 全部 9 个改动文件 `py_compile` 通过、模块导入冒烟通过；
- `main.py` 应用可导入，`/api/schema/relations` CRUD 路由、`/api/sync/*` 全部路由注册正常；
- 端到端：admin 注入关系 ✓、无权限用户不注入 ✓、不相关表不注入 ✓、双向去重 ✓、prompt 区块存在 ✓；
- 冒烟测试插入的关系数据已清理，`db_table_relations` 现为空表，可通过新界面录入。

## 注意事项

- fastapi TestClient 依赖（httpx）缺失，本次用路由枚举方式替代接口级测试；
- 项目无测试基建，本次验证均为运行时冒烟，建议后续补充 pytest 回归。

---

## 补充修复：表关系维护支持「同数据源跨库」

**用户反馈**：表关系列表维护是同数据源可跨库的，但选择表后查不到字段。

**根因**：原模型只有单一 `schema_id`，UI 用单个 `relSchema` 下拉同时驱动左右两侧表，无法表达"同数据源跨库"的关联——选右表时只能从同一个库里挑，跨库的表/字段根本选不到。

**改动**

| 层 | 文件 | 内容 |
|---|---|---|
| 模型 | `models/schema.py` | `DbTableRelation` 增 `left_schema_id`/`right_schema_id`（各自所属库）；`schema_id` 保留为兼容字段（=左库）；唯一索引改为 6 列复合 |
| 迁移 | `db/sqlite_hooks.py` + `db/database.py` | `_migrate_relation_cross_db`：补列 + 存量回填；因 SQLite 不支持 `ALTER COLUMN` 改可空，整表重建一次将 `schema_id` 置可空 |
| CRUD | `crud/schema.py` | `list_by_schema`/`list_by_schemas` 匹配左或右 schema；`exists_same` 按左右 schema + 表 + 字段判重（含反向） |
| 后端 | `app/routers/schema_router.py` | 请求改 `left_schema_name`/`right_schema_name`；`_validate_relation_payload` 两侧各自库校验表/字段真实存在；`list_relations` 的 `name_map` 用 `list_visible(visible)`（visible=None 必须传 None，否则库名显示为空） |
| 前端 | `static/template/schema/table_relation.html` + `static/js/table_relation.js` | 弹窗左右两个库下拉，各自独立加载表与字段；列表库列显示「左 ⇄ 右」；保存体改为 left/right schema_name |

**验证**：新建第二库 `pjmall2` 跑真实跨库场景——创建（pjmall.order.id = pjmall2.account.id）、列表（含按库筛选左右均命中）、查询链路注入、编辑、字段不存在校验 全部通过；测试数据已清理。

**踩坑**：SQLite 的 NOT NULL 列不能直接改可空，必须整表重建；裸 `sqlite3` 连接删 schema 不级联，清理需先删 `db_columns`/`db_tables`。
