# Baseline 评测汇总

- 题集: questions_falcon_retry_all  llm_config_id: 7
- 时间: 2026-10-18 20:42:22
- 题数: 184  EX: 0.2337 (43/184)
- 状态分桶: {"wrong_answer": 110, "ok": 43, "need_more_info": 12, "exec_error": 11, "error": 1, "row_limit": 1, "invalid_sql": 1, "model_quota_paused": 5}
- ⚠ 模型过期/配额不足 5 题（待续费后用 --retry-status model_quota_paused 重跑）
- 平均耗时: 107.3s  Token: {"prompt": 318446, "completion": 597609}

| qid | schema | status | EX | note |
|---|---|---|---|---|
| 7 | falcon_dev_8 | wrong_answer | 0 | value_mismatch (pred 30 行 vs 标准答案 43 行) |
| 1 | falcon_dev_20 | ok | 1 | multiset_r2 |
| 5 | falcon_dev_28 | need_more_info | 0 | 系统判定信息不足: ["州字段：所有已召回表中均无 state/province 字段，无法按州分组计算成功率", "address 字段的存储格式样例：无法确认自由文本 address 中是否含州信息（如'街道, 城市, 州缩写 邮编'） |
| 8 | falcon_dev_8 | wrong_answer | 0 | value_mismatch (pred 6 行 vs 标准答案 6 行) |
| 9 | falcon_dev_14 | ok | 1 | multiset_r2 |
| 15 | falcon_dev_14 | ok | 1 | multiset |
| 16 | falcon_dev_28 | wrong_answer | 0 | value_mismatch (pred 3 行 vs 标准答案 3 行) |
| 20 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 1 行) |
| 10 | falcon_dev_8 | wrong_answer | 0 | value_mismatch (pred 3 行 vs 标准答案 3 行) |
| 21 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 10 行 vs 标准答案 20 行) |
| 19 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 1 行) |
| 25 | falcon_dev_26 | wrong_answer | 0 | value_mismatch (pred 10 行 vs 标准答案 10 行) |
| 26 | falcon_dev_20 | ok | 1 | multiset_perm |
| 27 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 22 行 vs 标准答案 22 行) |
| 22 | falcon_dev_28 | wrong_answer | 0 | value_mismatch (pred 2000 行 vs 标准答案 298 行) |
| 29 | falcon_dev_8 | exec_error | 0 | SQL 执行失败: (pymysql.err.OperationalError) (1054, "Unknown column 'installs_num' in 'window order by'")
[SQL: WITH cleaned |
| 28 | falcon_dev_4 | wrong_answer | 0 | value_mismatch (pred 75 行 vs 标准答案 75 行) |
| 34 | falcon_dev_21 | ok | 1 | multiset_r2 |
| 37 | falcon_dev_24 | wrong_answer | 0 | value_mismatch (pred 2000 行 vs 标准答案 1704 行) |
| 30 | falcon_dev_16 | wrong_answer | 0 | value_mismatch (pred 10 行 vs 标准答案 10 行) |
| 23 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 1 行) |
| 38 | falcon_dev_15 | ok | 1 | multiset |
| 39 | falcon_dev_26 | wrong_answer | 0 | value_mismatch (pred 380 行 vs 标准答案 380 行) |
| 42 | falcon_dev_21 | ok | 1 | multiset_perm |
| 45 | falcon_dev_28 | wrong_answer | 0 | value_mismatch (pred 5 行 vs 标准答案 5 行) |
| 41 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 100 行 vs 标准答案 46 行) |
| 48 | falcon_dev_7 | wrong_answer | 0 | value_mismatch (pred 10 行 vs 标准答案 10 行) |
| 49 | falcon_dev_28 | ok | 1 | multiset |
| 51 | falcon_dev_9 | wrong_answer | 0 | value_mismatch (pred 214 行 vs 标准答案 151 行) |
| 40 | falcon_dev_4 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 1 行) |
| 47 | falcon_dev_26 | error | 0 | HTTPError: 500 Server Error: Internal Server Error for url: http://localhost:8888/api/conversation |
| 52 | falcon_dev_7 | wrong_answer | 0 | value_mismatch (pred 15 行 vs 标准答案 724 行) |
| 55 | falcon_dev_20 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 3 行) |
| 58 | falcon_dev_16 | ok | 1 | multiset_perm |
| 59 | falcon_dev_5 | ok | 1 | ordered |
| 64 | falcon_dev_15 | ok | 1 | multiset_r2 |
| 54 | falcon_dev_4 | wrong_answer | 0 | value_mismatch (pred 9 行 vs 标准答案 64 行) |
| 69 | falcon_dev_15 | wrong_answer | 0 | value_mismatch (pred 2 行 vs 标准答案 2 行) |
| 71 | falcon_dev_15 | wrong_answer | 0 | value_mismatch (pred 13 行 vs 标准答案 13 行) |
| 68 | falcon_dev_26 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 52 行) |
| 73 | falcon_dev_24 | row_limit | 0 | 标准答案 11723 行超服务端 max_rows=2000 截断 |
| 72 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 2 行 vs 标准答案 3 行) |
| 56 | falcon_dev_5 | wrong_answer | 0 | value_mismatch (pred 9 行 vs 标准答案 9 行) |
| 75 | falcon_dev_26 | ok | 1 | multiset |
| 82 | falcon_dev_14 | ok | 1 | multiset |
| 81 | falcon_dev_26 | wrong_answer | 0 | value_mismatch (pred 98 行 vs 标准答案 98 行) |
| 80 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 21 行 vs 标准答案 22 行) |
| 85 | falcon_dev_5 | wrong_answer | 0 | value_mismatch (pred 79 行 vs 标准答案 79 行) |
| 86 | falcon_dev_26 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 1 行) |
| 89 | falcon_dev_5 | wrong_answer | 0 | value_mismatch (pred 112 行 vs 标准答案 115 行) |
| 91 | falcon_dev_26 | wrong_answer | 0 | value_mismatch (pred 20 行 vs 标准答案 20 行) |
| 95 | falcon_dev_16 | wrong_answer | 0 | value_mismatch (pred 4 行 vs 标准答案 4 行) |
| 83 | falcon_dev_21 | wrong_answer | 0 | value_mismatch (pred 3 行 vs 标准答案 2 行) |
| 98 | falcon_dev_26 | wrong_answer | 0 | value_mismatch (pred 95 行 vs 标准答案 95 行) |
| 88 | falcon_dev_14 | exec_error | 0 | SQL 执行失败: (pymysql.err.OperationalError) (3593, "You cannot use the window function 'avg' in this context.'")
[SQL: WITH |
| 99 | falcon_dev_28 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 1 行) |
| 103 | falcon_dev_18 | need_more_info | 0 | 系统判定信息不足: ["包含订单信息的表（订单表，需含州字段）", "支付方式字段（用于筛选信用卡支付）", "运费字段（用于与平均值比较）", "订单金额字段（用于求和统计）"] |
| 100 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 12 行 vs 标准答案 12 行) |
| 104 | falcon_dev_9 | ok | 1 | multiset |
| 106 | falcon_dev_15 | ok | 1 | multiset |
| 105 | falcon_dev_28 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 69 行) |
| 110 | falcon_dev_15 | ok | 1 | multiset |
| 112 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 4 行 vs 标准答案 5 行) |
| 113 | falcon_dev_21 | ok | 1 | multiset |
| 97 | falcon_dev_5 | exec_error | 0 | SQL 执行失败: (pymysql.err.OperationalError) (1054, "Unknown column 'val' in 'window order by'")
[SQL: WITH company_val AS ( |
| 114 | falcon_dev_20 | ok | 1 | ordered |
| 118 | falcon_dev_4 | wrong_answer | 0 | value_mismatch (pred 5 行 vs 标准答案 5 行) |
| 123 | falcon_dev_28 | wrong_answer | 0 | value_mismatch (pred 2000 行 vs 标准答案 14 行) |
| 120 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 4 行 vs 标准答案 7 行) |
| 117 | falcon_dev_26 | wrong_answer | 0 | value_mismatch (pred 2000 行 vs 标准答案 550 行) |
| 125 | falcon_dev_16 | need_more_info | 0 | 系统判定信息不足: ["'排名第一'的排名口径：是每位学生自己各科成绩中的第一名科目，还是学生在某一科目中于全班排名第一", "'高分科目'的判定标准：分数阈值（如≥80分）、排名前N，还是等同于'排名第一的科目'（后者与'超过两门'矛盾） |
| 126 | falcon_dev_8 | wrong_answer | 0 | value_mismatch (pred 133 行 vs 标准答案 107 行) |
| 124 | falcon_dev_19 | exec_error | 0 | SQL 执行失败: (pymysql.err.ProgrammingError) (1064, "You have an error in your SQL syntax; check the manual that corresponds |
| 130 | falcon_dev_7 | ok | 1 | ordered |
| 128 | falcon_dev_5 | ok | 1 | multiset |
| 133 | falcon_dev_21 | wrong_answer | 0 | value_mismatch (pred 2 行 vs 标准答案 2 行) |
| 132 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 5 行 vs 标准答案 5 行) |
| 134 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 9 行 vs 标准答案 9 行) |
| 136 | falcon_dev_18 | ok | 1 | multiset_perm |
| 144 | falcon_dev_17 | need_more_info | 0 | 系统判定信息不足: ["利润的计算口径或所需字段（如成本价/利润额）在已召回表中不存在"] |
| 141 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 1 行) |
| 147 | falcon_dev_8 | wrong_answer | 0 | value_mismatch (pred 46 行 vs 标准答案 44 行) |
| 127 | falcon_dev_15 | ok | 1 | multiset_perm |
| 145 | falcon_dev_20 | ok | 1 | multiset |
| 150 | falcon_dev_20 | invalid_sql | 0 | 仅允许 SELECT 查询语句 |
| 148 | falcon_dev_24 | wrong_answer | 0 | value_mismatch (pred 267 行 vs 标准答案 267 行) |
| 153 | falcon_dev_21 | wrong_answer | 0 | value_mismatch (pred 200 行 vs 标准答案 135 行) |
| 151 | falcon_dev_4 | ok | 1 | multiset_perm |
| 156 | falcon_dev_5 | need_more_info | 0 | 系统判定信息不足: ["缺少公司成立日期或成立年份字段（如 year_founded / date_founded），无法计算平均成立年限"] |
| 157 | falcon_dev_28 | need_more_info | 0 | 系统判定信息不足: ["库存量字段：已召回表中无 stock/inventory/库存数量 类字段，无法实现'库存量大于100件'的过滤", "'供应商平均售价'口径未明确：指该供应商全部商品的平均售价，还是商品自身售价（次要，可在生成阶段 |
| 154 | falcon_dev_14 | ok | 1 | multiset |
| 162 | falcon_dev_28 | ok | 1 | ordered |
| 158 | falcon_dev_15 | wrong_answer | 0 | value_mismatch (pred 3 行 vs 标准答案 13 行) |
| 165 | falcon_dev_16 | wrong_answer | 0 | value_mismatch (pred 10 行 vs 标准答案 10 行) |
| 167 | falcon_dev_8 | wrong_answer | 0 | value_mismatch (pred 33 行 vs 标准答案 33 行) |
| 170 | falcon_dev_5 | wrong_answer | 0 | value_mismatch (pred 174 行 vs 标准答案 174 行) |
| 155 | falcon_dev_4 | ok | 1 | multiset |
| 172 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 11 行 vs 标准答案 11 行) |
| 171 | falcon_dev_14 | need_more_info | 0 | 系统判定信息不足: ["缺少存储门店所属国家的字段（如Store_Country），无法定位墨西哥区域的玩具店"] |
| 168 | falcon_dev_26 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 5 行) |
| 176 | falcon_dev_7 | wrong_answer | 0 | value_mismatch (pred 579 行 vs 标准答案 578 行) |
| 177 | falcon_dev_20 | ok | 1 | ordered |
| 179 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 39 行 vs 标准答案 39 行) |
| 174 | falcon_dev_28 | wrong_answer | 0 | value_mismatch (pred 2000 行 vs 标准答案 3 行) |
| 184 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 34 行 vs 标准答案 5 行) |
| 182 | falcon_dev_24 | wrong_answer | 0 | value_mismatch (pred 265 行 vs 标准答案 265 行) |
| 185 | falcon_dev_28 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 365 行) |
| 189 | falcon_dev_21 | exec_error | 0 | SQL 执行失败: (pymysql.err.OperationalError) (1055, "Expression #2 of SELECT list is not in GROUP BY clause and contains non |
| 191 | falcon_dev_21 | wrong_answer | 0 | value_mismatch (pred 40 行 vs 标准答案 40 行) |
| 192 | falcon_dev_7 | wrong_answer | 0 | value_mismatch (pred 401 行 vs 标准答案 368 行) |
| 193 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 19 行 vs 标准答案 19 行) |
| 183 | falcon_dev_15 | wrong_answer | 0 | value_mismatch (pred 2 行 vs 标准答案 8 行) |
| 194 | falcon_dev_21 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 2 行) |
| 197 | falcon_dev_9 | wrong_answer | 0 | value_mismatch (pred 223 行 vs 标准答案 223 行) |
| 187 | falcon_dev_21 | wrong_answer | 0 | value_mismatch (pred 3 行 vs 标准答案 3 行) |
| 195 | falcon_dev_4 | ok | 1 | multiset_perm_r2 |
| 202 | falcon_dev_19 | ok | 1 | ordered |
| 198 | falcon_dev_19 | ok | 1 | multiset |
| 203 | falcon_dev_21 | wrong_answer | 0 | value_mismatch (pred 200 行 vs 标准答案 36 行) |
| 209 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 2 行 vs 标准答案 1 行) |
| 210 | falcon_dev_8 | wrong_answer | 0 | value_mismatch (pred 10 行 vs 标准答案 10 行) |
| 213 | falcon_dev_19 | wrong_answer | 0 | value_mismatch (pred 27 行 vs 标准答案 22 行) |
| 214 | falcon_dev_24 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 30 行) |
| 201 | falcon_dev_26 | exec_error | 0 | SQL 执行失败: QueuePool limit of size 1 overflow 2 reached, connection timed out, timeout 30.00 (Background on this error at |
| 205 | falcon_dev_26 | need_more_info | 0 | 系统判定信息不足: ["缺失球员与所属球队的关联关系（需存在同时包含playerID和teamID的表，或在球员出场记录表中增加球员对应场次的所属球队/主客队标识）"] |
| 216 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 5 行 vs 标准答案 18 行) |
| 217 | falcon_dev_15 | wrong_answer | 0 | value_mismatch (pred 3 行 vs 标准答案 4 行) |
| 218 | falcon_dev_5 | wrong_answer | 0 | value_mismatch (pred 34 行 vs 标准答案 34 行) |
| 219 | falcon_dev_26 | need_more_info | 0 | 系统判定信息不足: ["球员级别的犯规次数字段：football_appearances 表中无 fouls 列，fouls 仅存在于 football_teamstats（球队粒度），无法计算单个球员的犯规次数"] |
| 220 | falcon_dev_21 | ok | 1 | multiset_perm |
| 215 | falcon_dev_20 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 9 行) |
| 228 | falcon_dev_16 | ok | 1 | multiset_perm |
| 226 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 12 行 vs 标准答案 12 行) |
| 231 | falcon_dev_9 | ok | 1 | multiset |
| 232 | falcon_dev_21 | wrong_answer | 0 | value_mismatch (pred 200 行 vs 标准答案 127 行) |
| 234 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 3 行 vs 标准答案 3 行) |
| 222 | falcon_dev_26 | exec_error | 0 | SQL 执行失败: QueuePool limit of size 1 overflow 2 reached, connection timed out, timeout 30.00 (Background on this error at |
| 230 | falcon_dev_24 | wrong_answer | 0 | value_mismatch (pred 139 行 vs 标准答案 61 行) |
| 239 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 4 行 vs 标准答案 4 行) |
| 238 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 16 行 vs 标准答案 16 行) |
| 243 | falcon_dev_15 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 1 行) |
| 248 | falcon_dev_4 | wrong_answer | 0 | value_mismatch (pred 100 行 vs 标准答案 5 行) |
| 247 | falcon_dev_5 | ok | 1 | multiset |
| 257 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 13 行 vs 标准答案 13 行) |
| 237 | falcon_dev_26 | need_more_info | 0 | 系统判定信息不足: ["缺少球员与所属球队的关联信息，如出场表（football_appearances）中缺少球员所属球队ID或主客场标识字段，或缺少球员赛季所属球队的关联表"] |
| 258 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 1 行) |
| 259 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 5 行 vs 标准答案 5 行) |
| 250 | falcon_dev_26 | exec_error | 0 | SQL 执行失败: QueuePool limit of size 1 overflow 2 reached, connection timed out, timeout 30.00 (Background on this error at |
| 261 | falcon_dev_21 | wrong_answer | 0 | value_mismatch (pred 5 行 vs 标准答案 5 行) |
| 263 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 38 行 vs 标准答案 9 行) |
| 264 | falcon_dev_26 | exec_error | 0 | SQL 执行失败: QueuePool limit of size 1 overflow 2 reached, connection timed out, timeout 30.00 (Background on this error at |
| 265 | falcon_dev_8 | wrong_answer | 0 | value_mismatch (pred 10 行 vs 标准答案 10 行) |
| 262 | falcon_dev_24 | ok | 1 | multiset |
| 270 | falcon_dev_28 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 36 行) |
| 271 | falcon_dev_16 | wrong_answer | 0 | value_mismatch (pred 10 行 vs 标准答案 10 行) |
| 267 | falcon_dev_26 | exec_error | 0 | SQL 执行失败: QueuePool limit of size 1 overflow 2 reached, connection timed out, timeout 30.00 (Background on this error at |
| 273 | falcon_dev_18 | ok | 1 | multiset |
| 274 | falcon_dev_18 | ok | 1 | multiset_perm |
| 277 | falcon_dev_19 | wrong_answer | 0 | value_mismatch (pred 168 行 vs 标准答案 167 行) |
| 266 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 3 行 vs 标准答案 2 行) |
| 280 | falcon_dev_7 | wrong_answer | 0 | value_mismatch (pred 848 行 vs 标准答案 848 行) |
| 272 | falcon_dev_21 | model_quota_paused | 0 | 模型过期/配额不足: {"code":50000,"message":"模型欠费/余额不足，已标记该 LLM 配置为欠费状态，续费后请在模型管理页恢复","detail":"模型欠费/余额不足，已标记该 LLM 配置为欠费状态，续费后请在模 |
| 283 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 1 行) |
| 278 | falcon_dev_17 | model_quota_paused | 0 | 模型过期/配额不足: {"code":50000,"message":"模型欠费/余额不足，已标记该 LLM 配置为欠费状态，续费后请在模型管理页恢复","detail":"模型欠费/余额不足，已标记该 LLM 配置为欠费状态，续费后请在模 |
| 286 | falcon_dev_8 | wrong_answer | 0 | value_mismatch (pred 304 行 vs 标准答案 303 行) |
| 282 | falcon_dev_26 | model_quota_paused | 0 | 模型过期/配额不足: {"code":50000,"message":"模型欠费/余额不足，已标记该 LLM 配置为欠费状态，续费后请在模型管理页恢复","detail":"模型欠费/余额不足，已标记该 LLM 配置为欠费状态，续费后请在模 |
| 284 | falcon_dev_17 | ok | 1 | multiset |
| 288 | falcon_dev_9 | ok | 1 | multiset |
| 291 | falcon_dev_7 | wrong_answer | 0 | value_mismatch (pred 12 行 vs 标准答案 60 行) |
| 294 | falcon_dev_14 | need_more_info | 0 | 系统判定信息不足: ["“同类商店”的分组依据：表中无商店类型字段，是按 Store_City（同城市）还是 Store_Location（同位置类型）划分", "“开业三年后”的具体时间窗口：是开业日期+3 年起的一整年，还是其他区间", |
| 293 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 1 行) |
| 292 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 15 行 vs 标准答案 15 行) |
| 295 | falcon_dev_5 | ok | 1 | multiset_perm |
| 296 | falcon_dev_16 | need_more_info | 0 | 系统判定信息不足: ["学生所在城市的确定方式：表中无 City 字段，仅有 Address 文本字段，需说明城市如何从 Address 中提取（或提供 Address 样本格式），否则无法按城市分组", "比较对象不明确：未指明是某位具体 |
| 298 | falcon_dev_5 | exec_error | 0 | SQL 执行失败: (pymysql.err.OperationalError) (1055, "Expression #1 of SELECT list is not in GROUP BY clause and contains non |
| 299 | falcon_dev_14 | ok | 1 | multiset |
| 302 | falcon_dev_18 | wrong_answer | 0 | value_mismatch (pred 5 行 vs 标准答案 3 行) |
| 304 | falcon_dev_15 | wrong_answer | 0 | value_mismatch (pred 19 行 vs 标准答案 19 行) |
| 305 | falcon_dev_28 | wrong_answer | 0 | value_mismatch (pred 62 行 vs 标准答案 62 行) |
| 306 | falcon_dev_4 | ok | 1 | multiset_perm |
| 297 | falcon_dev_5 | model_quota_paused | 0 | 模型过期/配额不足: {"code":50000,"message":"模型欠费/余额不足，已标记该 LLM 配置为欠费状态，续费后请在模型管理页恢复","detail":"模型欠费/余额不足，已标记该 LLM 配置为欠费状态，续费后请在模 |
| 308 | falcon_dev_18 | wrong_answer | 0 | value_mismatch (pred 3 行 vs 标准答案 24 行) |
| 307 | falcon_dev_17 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 1 行) |
| 300 | falcon_dev_26 | model_quota_paused | 0 | 模型过期/配额不足: {"code":50000,"message":"模型欠费/余额不足，已标记该 LLM 配置为欠费状态，续费后请在模型管理页恢复","detail":"模型欠费/余额不足，已标记该 LLM 配置为欠费状态，续费后请在模 |
