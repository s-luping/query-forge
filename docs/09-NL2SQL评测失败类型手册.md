# NL2SQL 评测失败类型手册

> 版本：v1.0（2026-10-20） · 读者：评测执行、归因分析、优化决策
> 用途：QueryForge NL2SQL 基准跑批（Falcon / BIRD / Spider）失败归因的**标准手册**。
> 跑批后按本手册分桶，先定性再决定是否耗优化预算——避免对"不可修"的桶浪费迭代。
>
> 配套工具：`benchmark/analyze_spider.py`（统一重算+分桶）、`benchmark/spider_bench.py::wide_compare`（宽口径分层比对）、`benchmark/run_eval.py` / `analyze_falcon.py`（Falcon 同族）。

---

## 1. 归因总流程

```
跑批结果 → 按 qid 取最新记录 → gen SQL 重放目标库
  → ① 严格多重集比对（行序无关，浮点 4 位）
  → ② 宽口径分层比对（wide_compare）→ 通过 = 形态类，不耗预算
  → ③ gen ⊇ gold 判定 → 并列保序桶，不耗预算
  → ④ 剩余为真错 → 逐题人工定性（gold quirk / 枚举 / 方言 / 召回 / 拦截 / 基础设施）
```

宽口径 `wide_compare` 五层（全部通过才记 wide_pass，记录命中层名）：

| 层 | 处理 | 典型场景 |
|---|---|---|
| r2ci | 字符串小写去空格、数值 3 位舍入后精确多重集 | 大小写/空格/浮点尾数差异 |
| tol | 字符串锚点分组配对，数值格 \|a-b\|≤0.0015 | AVG 半进位 0.0001 级漂移 |
| perm | 同列数全排列（≤3 列放宽到 2000 行） | 输出列顺序与 gold 不同 |
| perm_tol | 排列 + 容差叠加 | 列序 + 精度同时出现 |
| extra_col | gen 列数 = gold+1 时逐列剔除重比 | 多输出一个未要求列 |

> 坑：**不能用固定舍入位数消精度漂移**——gold 落标 4 位舍入 × 比对再舍入 = 双重舍入，r2/r3/r4 各会反弹 4~59 行；必须容差匹配，且 tol=1.5e-3（名义 0.001 的差在二进制浮点下会 >1e-3 被误拒）。

---

## 2. 错误类型总表

### A. 不耗优化预算（评测口径/基准自身问题）

#### A1. 并列保序（tie_superset）★最高频
- **定义**：最值/TopN 存在并列，模型用 `DENSE_RANK`/`RANK`/不加 LIMIT 保留全部并列行，gold 用 `LIMIT 1` 在并列中任意取一行。判别：**gen 行集 ⊇ gold 行集且行数更多**。
- **案例**：q421「参观最多的博物馆」两家并列，模型返 2 行 ⊇ gold 1 行；Falcon q218 同日加入的两家 'Internet' 公司。
- **解决**：评测侧"并列分桶"单独统计（gen⊇gold 即另计，不算错也不算对）；**不修模型**——按题意保并列反而是更正确的语义。若业务强制单行，应加次级排序（但 gold 未必有，慎改）。

#### A2. gold quirk（口径差，gold 自身与题面语义不符）
- **定义**：gold SQL 的写法依赖 SQLite 弱语义/标注口径，与题面字面语义不可两全。
- **已见子类**：
  - TEXT 列 ORDER BY 取字典序（q95/96 horsepower '100'<'70' 按字符串排），模型 CAST 数值排才是题面语义；
  - `count(*)` 代 SUM（q500 题面"total injuries"gold 数行数）；
  - `GROUP BY first_name` 合并同名不同人（q469/471，1580 vs 2000 组）；
  - 行数代实体数（q687 count(*)=19 行 vs DISTINCT state）；
  - 边界 `<2` vs `<=2`（q526 题面 less than 2，gold 含 2）；
  - 单位错（Falcon q298「5 亿美元」gold 写 >5 而字段单位 $B 应为 0.5）。
- **解决**：逐题标注 gold_quirk，报告中单独分桶；**不耗预算**。若同类 quirk 反复出现，可考虑向上游反馈修订 gold。

### B. 低成本可修（KB / prompt / 配置）

#### B1. 枚举值照抄
- **定义**：过滤条件里的枚举字符串与实际存储值不一致。两个方向：① 丢字符（q610 题面 "The Rise of the Blue Beetle!"，生成 SQL 丢「!」→ 0 行）；② 先验反噬（q1033 实际值 'House'/'Apartment'，模型写 Spider 训练集惯例 'Hse'/'Apt'）。
- **解决**：知识库 L2「字段口径」条目写**实际 DISTINCT 值并要求逐字符照抄**（含大小写/空格/标点），给 TRIM 前后双形式；元数据同步低基数 VARCHAR 自动采样 DISTINCT 注入召回（既有方案）。
- **预防**：分析空结果（gen=0 行）失败时**第一个查枚举值**。

#### B2. 方言错误
- **定义**：SQLite/通用语法在 MySQL 不成立。已见：HAVING 引用非聚合列（q923，MySQL 1054，SQLite 允许）；`CAST(x AS DOUBLE)`（MySQL 8.0.17+ 语法，本机 8.0.12 报 1064，全局已禁用改 DECIMAL(18,4)）；`IN (SELECT ... LIMIT)` 报 1235（需包一层再 JOIN，已沉淀全局 KB）。
- **解决**：生成 prompt 方言段强化（聚合条件放 WHERE，HAVING 只放聚合结果）；KB 沉淀方言陷阱条目；执行报错 1054/1064/1235 自动归入此类。

#### B3. 结果形态（wide_pass，宽口径可过）
- **定义**：值全对但形态不符——列序（perm）、多一列（extra_col）、精度（tol）。
- **解决**：【结果形态】prompt 约束（不加题目未要求列）已上线；宽口径统计兜底。若某类形态错误在**严格口径**下高频，检查元数据/知识条目是否把模型带偏（如 Falcon 排名列规则曾把 q136 修错——**KB 规则写反比不写更糟，每轮必须小批复测**）。

#### B4. 清洗陷阱
- **定义**：'$' 前缀、千分位、'+' 号、字符串数字需 CAST、utf8mb4 排序规则合并大小写变体（GROUP BY 分区数变化）。
- **解决**：KB L3 清洗片段（`CAST(REPLACE(TRIM(col),'$','') AS DECIMAL(18,4))` 模板）；分库条目加 `COLLATE utf8mb4_bin` 提示。

### C. 链路问题（需要排查系统）

#### C1. 召回遗漏
- **定义**：gold 涉及的表/字段没进 prompt（中间关联表被 TopK 裁掉）。判别：看 pipeline【表结构】注入内容 vs gold 涉及表。
- **解决**：SMALL_SCHEMA_TABLE_LIMIT 小库直通、FIELD_RECALL_TOP_K/MAX_TABLES 放宽、全库直通阈值（VECTOR_INDEX_THRESHOLD 语义）。

#### C2. 拦截（judge 判"信息不足"）
- **定义**：可行性判断步拦截。分两种：**合理拦截**（schema 确实答不出）与**误伤**（题目可答被拦）。
- **排查**：先查拦截时 prompt 是否缺表/缺列——若是，先修召回（Spider q922 实为元数据同步 bug 的连带）；真误伤再看 judge prompt 是否过严。
- **特殊**：元数据同步静默失败（0 表）会表现为"全部拦截"——先查 `db_tables` 计数再怪 judge。

#### C3. 执行错误（exec_error）
- **定义**：生成 SQL 执行报错。多为方言（B2），也可能是幻觉列（Falcon q291 编造 install_num）。
- **解决**：执行反馈自修复（报错回灌重生成一次）是既定高性价比方案，尚未实施。

#### C4. 基础设施（infra）
- **定义**：模型侧超时（NVIDIA 思考到 300s 读超时 504）、限流 429、配额耗尽（SetLimitExceeded）、网关 5xx、DNS 瞬断。
- **解决**：重试 + `fallback_ids` 配置链自动换模型；跑批用 `workers` 多线程提速（`spider_bench test <题目> <结果> <llm_id> <workers> <fallback链>`）。异常题在结果文件里删掉记录即自动重跑。

#### C5. row_limit
- **定义**：gold 结果集超服务端 SQL_MAX_ROWS 截断，无法完整比对。已扩到 2000 行（覆盖 Falcon 44 题中的 43 题）。

---

## 3. 优化预算分配原则

| 桶 | 动作 |
|---|---|
| A1 并列保序 / A2 gold quirk | 不修，分桶统计 |
| B1 枚举 / B2 方言 / B4 清洗 | KB 条目 + 小批（≤10 题）复测，逐题 SQL 强归因 |
| B3 形态 | prompt 约束 + 宽口径统计兜底 |
| C1 召回 / C2 拦截 | 查链路（prompt 注入实证，勿只看页面） |
| C4 基础设施 | 重试/配置链，不计入模型指标 |

**每轮改动必须小批复测**：KB 双刃剑实证——一条写反的规则能把对题修错（Falcon q136 案例）。

---

## 4. 分桶名 ↔ 工具对应

| analyze_spider 桶名 | 本手册类型 |
|---|---|
| ok | 通过（严格口径） |
| wide_pass | B3 形态类 |
| tie_superset | A1 并列保序 |
| true_wrong | A2 / B1 / B2 / B4 / C3（需人工定性，见 ATTR 归因） |
| exec_error | C3（多为 B2 方言） |
| intercepted / infra / row_limit | C2 / C4 / C5（Falcon 工具链使用） |

报告脚本：`make_spider_cumulative_report.py`（ATTR 字典即逐题人工定性）。
