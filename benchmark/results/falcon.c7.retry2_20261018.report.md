# Baseline 评测汇总

- 题集: questions_falcon_retry2  llm_config_id: 7
- 时间: 2026-10-19 00:58:37
- 题数: 141  EX: 0.2411 (34/141)
- 状态分桶: {"wrong_answer": 76, "need_more_info": 16, "ok": 34, "exec_error": 10, "row_limit": 1, "error": 3, "invalid_sql": 1}
- 平均耗时: 144.5s  Token: {"prompt": 344825, "completion": 337088}

| qid | schema | status | EX | note |
|---|---|---|---|---|
| 8 | falcon_dev_8 | wrong_answer | 0 | value_mismatch (pred 6 行 vs 标准答案 6 行) |
| 7 | falcon_dev_8 | wrong_answer | 0 | value_mismatch (pred 43 行 vs 标准答案 43 行) |
| 5 | falcon_dev_28 | need_more_info | 0 | 系统判定信息不足: ["州字段：所有表中不存在独立的 state 列，无法直接按州分组统计成功率", "customers.address 的样例格式：若州信息嵌在地址文本中，需提供几行样例确认解析规则（如 'street, city, S |
| 16 | falcon_dev_28 | wrong_answer | 0 | value_mismatch (pred 3 行 vs 标准答案 3 行) |
| 20 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 1 行) |
| 19 | falcon_dev_14 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 1 行) |
| 21 | falcon_dev_14 | ok | 1 | multiset |
| 22 | falcon_dev_28 | wrong_answer | 0 | value_mismatch (pred 298 行 vs 标准答案 298 行) |
| 10 | falcon_dev_8 | wrong_answer | 0 | value_mismatch (pred 5 行 vs 标准答案 3 行) |
| 25 | falcon_dev_26 | wrong_answer | 0 | value_mismatch (pred 10 行 vs 标准答案 10 行) |
| 27 | falcon_dev_20 | ok | 1 | multiset |
| 28 | falcon_dev_4 | wrong_answer | 0 | value_mismatch (pred 75 行 vs 标准答案 75 行) |
| 30 | falcon_dev_16 | exec_error | 0 | SQL 执行失败: (pymysql.err.ProgrammingError) (1064, "You have an error in your SQL syntax; check the manual that corresponds |
| 23 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 1 行) |
| 37 | falcon_dev_24 | ok | 1 | multiset_perm |
| 39 | falcon_dev_26 | wrong_answer | 0 | value_mismatch (pred 380 行 vs 标准答案 380 行) |
| 29 | falcon_dev_8 | wrong_answer | 0 | value_mismatch (pred 138 行 vs 标准答案 139 行) |
| 41 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 46 行 vs 标准答案 46 行) |
| 40 | falcon_dev_4 | exec_error | 0 | SQL 执行失败: (pymysql.err.ProgrammingError) (1064, "You have an error in your SQL syntax; check the manual that corresponds |
| 48 | falcon_dev_7 | ok | 1 | ordered |
| 45 | falcon_dev_28 | wrong_answer | 0 | value_mismatch (pred 15 行 vs 标准答案 5 行) |
| 51 | falcon_dev_9 | need_more_info | 0 | 系统判定信息不足: ["互联网用户渗透率的定义或计算所需字段（如总人口或渗透率字段）", "连续三年的具体时间范围或起止年份"] |
| 52 | falcon_dev_7 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 724 行) |
| 55 | falcon_dev_20 | ok | 1 | multiset_perm |
| 47 | falcon_dev_26 | need_more_info | 0 | 系统判定信息不足: ["射门记录与球队的关联字段（如 football_shots.teamID 或 football_appearances.teamID）", "football_shots.shotType 中表示头球射门的枚举值"] |
| 68 | falcon_dev_26 | wrong_answer | 0 | value_mismatch (pred 52 行 vs 标准答案 52 行) |
| 69 | falcon_dev_15 | ok | 1 | multiset_r2 |
| 71 | falcon_dev_15 | exec_error | 0 | SQL 执行失败: (pymysql.err.ProgrammingError) (1064, "You have an error in your SQL syntax; check the manual that corresponds |
| 56 | falcon_dev_5 | wrong_answer | 0 | value_mismatch (pred 9 行 vs 标准答案 9 行) |
| 73 | falcon_dev_24 | row_limit | 0 | 标准答案 11723 行超服务端 max_rows=2000 截断 |
| 80 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 22 行 vs 标准答案 22 行) |
| 81 | falcon_dev_26 | wrong_answer | 0 | value_mismatch (pred 98 行 vs 标准答案 98 行) |
| 72 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 2 行 vs 标准答案 3 行) |
| 85 | falcon_dev_5 | ok | 1 | multiset |
| 86 | falcon_dev_26 | ok | 1 | multiset |
| 83 | falcon_dev_21 | exec_error | 0 | SQL 执行失败: (pymysql.err.ProgrammingError) (1064, "You have an error in your SQL syntax; check the manual that corresponds |
| 54 | falcon_dev_4 | error | 0 | HTTPError: 500 Server Error: Internal Server Error for url: http://localhost:8888/api/conversation |
| 91 | falcon_dev_26 | wrong_answer | 0 | value_mismatch (pred 20 行 vs 标准答案 20 行) |
| 89 | falcon_dev_5 | ok | 1 | multiset_perm |
| 97 | falcon_dev_5 | exec_error | 0 | SQL 执行失败: (pymysql.err.OperationalError) (1054, "Unknown column 'val' in 'window order by'")
[SQL: WITH cleaned AS (
    |
| 98 | falcon_dev_26 | wrong_answer | 0 | value_mismatch (pred 95 行 vs 标准答案 95 行) |
| 95 | falcon_dev_16 | exec_error | 0 | SQL 执行失败: (pymysql.err.ProgrammingError) (1064, "You have an error in your SQL syntax; check the manual that corresponds |
| 88 | falcon_dev_14 | need_more_info | 0 | 系统判定信息不足: ["“区域”具体对应哪个字段（Store_City 还是 Store_Location 或其他）", "Store_Open_Date 的日期格式（如 yyyy-MM-dd 或 MM/dd/yyyy）", "库存量的计算 |
| 103 | falcon_dev_18 | need_more_info | 0 | 系统判定信息不足: ["包含订单信息的表（订单表）", "州（state）字段", "支付方式字段（用于筛选信用卡支付）", "运费字段（用于与平均值比较）", "订单金额字段（用于求和）"] |
| 99 | falcon_dev_28 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 1 行) |
| 105 | falcon_dev_28 | ok | 1 | multiset_perm_r2 |
| 112 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 4 行 vs 标准答案 5 行) |
| 100 | falcon_dev_14 | ok | 1 | multiset_r2 |
| 117 | falcon_dev_26 | ok | 1 | multiset_perm |
| 118 | falcon_dev_4 | wrong_answer | 0 | value_mismatch (pred 5 行 vs 标准答案 5 行) |
| 123 | falcon_dev_28 | wrong_answer | 0 | value_mismatch (pred 14 行 vs 标准答案 14 行) |
| 120 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 4 行 vs 标准答案 7 行) |
| 124 | falcon_dev_19 | ok | 1 | multiset_r2 |
| 125 | falcon_dev_16 | wrong_answer | 0 | value_mismatch (pred 2 行 vs 标准答案 2 行) |
| 133 | falcon_dev_21 | wrong_answer | 0 | value_mismatch (pred 2 行 vs 标准答案 2 行) |
| 126 | falcon_dev_8 | wrong_answer | 0 | value_mismatch (pred 248 行 vs 标准答案 107 行) |
| 141 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 1 行) |
| 144 | falcon_dev_17 | need_more_info | 0 | 系统判定信息不足: ["利润的计算口径与数据来源：已召回表中无成本价/利润字段（如 cost_price、profit 列或包含成本的表）"] |
| 134 | falcon_dev_14 | ok | 1 | multiset_perm_r2 |
| 147 | falcon_dev_8 | wrong_answer | 0 | value_mismatch (pred 49 行 vs 标准答案 44 行) |
| 132 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 5 行 vs 标准答案 5 行) |
| 153 | falcon_dev_21 | wrong_answer | 0 | value_mismatch (pred 135 行 vs 标准答案 135 行) |
| 156 | falcon_dev_5 | need_more_info | 0 | 系统判定信息不足: ["缺少公司成立日期/成立年份字段（如 founded_year 或 founding_date），无法计算平均成立年限", "若存在包含成立年份的其他表（如公司维表），该表未被召回"] |
| 157 | falcon_dev_28 | need_more_info | 0 | 系统判定信息不足: ["库存量字段：已召回表结构中无 stock/inventory/quantity_in_stock 等库存数量列，'库存量大于100件'条件无法实现"] |
| 148 | falcon_dev_24 | exec_error | 0 | SQL 执行失败: (pymysql.err.ProgrammingError) (1064, "You have an error in your SQL syntax; check the manual that corresponds |
| 150 | falcon_dev_20 | invalid_sql | 0 | 仅允许 SELECT 查询语句 |
| 165 | falcon_dev_16 | wrong_answer | 0 | value_mismatch (pred 10 行 vs 标准答案 10 行) |
| 167 | falcon_dev_8 | ok | 1 | multiset |
| 168 | falcon_dev_26 | wrong_answer | 0 | value_mismatch (pred 153 行 vs 标准答案 5 行) |
| 170 | falcon_dev_5 | wrong_answer | 0 | value_mismatch (pred 174 行 vs 标准答案 174 行) |
| 158 | falcon_dev_15 | wrong_answer | 0 | value_mismatch (pred 3 行 vs 标准答案 13 行) |
| 172 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 7 行 vs 标准答案 11 行) |
| 174 | falcon_dev_28 | wrong_answer | 0 | value_mismatch (pred 3 行 vs 标准答案 3 行) |
| 179 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 39 行 vs 标准答案 39 行) |
| 182 | falcon_dev_24 | wrong_answer | 0 | value_mismatch (pred 265 行 vs 标准答案 265 行) |
| 183 | falcon_dev_15 | exec_error | 0 | SQL 执行失败: (pymysql.err.ProgrammingError) (1064, "You have an error in your SQL syntax; check the manual that corresponds |
| 171 | falcon_dev_14 | need_more_info | 0 | 系统判定信息不足: ["toy_stores 表缺少国家/地区字段，无法确定如何筛选墨西哥", "“玩具店”的定义不明确（表无店铺类型字段）", "“在售商品”的口径不明确（是否仅统计有销售记录的商品）"] |
| 176 | falcon_dev_7 | wrong_answer | 0 | value_mismatch (pred 885 行 vs 标准答案 578 行) |
| 185 | falcon_dev_28 | wrong_answer | 0 | value_mismatch (pred 365 行 vs 标准答案 365 行) |
| 189 | falcon_dev_21 | wrong_answer | 0 | value_mismatch (pred 4 行 vs 标准答案 4 行) |
| 191 | falcon_dev_21 | ok | 1 | multiset_perm |
| 192 | falcon_dev_7 | wrong_answer | 0 | value_mismatch (pred 381 行 vs 标准答案 368 行) |
| 187 | falcon_dev_21 | wrong_answer | 0 | value_mismatch (pred 3 行 vs 标准答案 3 行) |
| 194 | falcon_dev_21 | ok | 1 | multiset_perm |
| 184 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 5 行 vs 标准答案 5 行) |
| 193 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 19 行 vs 标准答案 19 行) |
| 197 | falcon_dev_9 | wrong_answer | 0 | value_mismatch (pred 223 行 vs 标准答案 223 行) |
| 203 | falcon_dev_21 | ok | 1 | multiset |
| 209 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 2 行 vs 标准答案 1 行) |
| 210 | falcon_dev_8 | wrong_answer | 0 | value_mismatch (pred 15 行 vs 标准答案 10 行) |
| 213 | falcon_dev_19 | ok | 1 | multiset |
| 214 | falcon_dev_24 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 30 行) |
| 205 | falcon_dev_26 | need_more_info | 0 | 系统判定信息不足: ["球员与球队的关联关系（如 football_appearances 缺少 teamID，无法确定球员所属球队）", "场均进球和联赛平均的具体计算口径（主场场均还是总场均，联赛平均如何定义）", "助攻效率的定义（如 |
| 201 | falcon_dev_26 | error | 0 | HTTPError: 502 Server Error: Bad Gateway for url: http://localhost:8888/api/conversation |
| 216 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 5 行 vs 标准答案 18 行) |
| 218 | falcon_dev_5 | wrong_answer | 0 | value_mismatch (pred 34 行 vs 标准答案 34 行) |
| 219 | falcon_dev_26 | need_more_info | 0 | 系统判定信息不足: ["球员级别的犯规次数字段：football_appearances 无 fouls 列，football_teamstats.fouls 为球队每场数据，无法按球员统计", "球员与球队的关联字段：football_p |
| 217 | falcon_dev_15 | wrong_answer | 0 | value_mismatch (pred 3 行 vs 标准答案 4 行) |
| 226 | falcon_dev_20 | ok | 1 | ordered |
| 215 | falcon_dev_20 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 9 行) |
| 232 | falcon_dev_21 | wrong_answer | 0 | value_mismatch (pred 127 行 vs 标准答案 127 行) |
| 222 | falcon_dev_26 | wrong_answer | 0 | value_mismatch (pred 9 行 vs 标准答案 8 行) |
| 230 | falcon_dev_24 | error | 0 | HTTPError: 500 Server Error: Internal Server Error for url: http://localhost:8888/api/conversation |
| 238 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 16 行 vs 标准答案 16 行) |
| 239 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 4 行 vs 标准答案 4 行) |
| 234 | falcon_dev_14 | ok | 1 | multiset |
| 248 | falcon_dev_4 | ok | 1 | ordered |
| 243 | falcon_dev_15 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 1 行) |
| 257 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 20 行 vs 标准答案 13 行) |
| 237 | falcon_dev_26 | need_more_info | 0 | 系统判定信息不足: ["球员所属球队的关联字段（如 football_appearances.teamID 或球员-球队关联表）"] |
| 259 | falcon_dev_20 | ok | 1 | multiset_r2 |
| 261 | falcon_dev_21 | ok | 1 | multiset |
| 250 | falcon_dev_26 | need_more_info | 0 | 系统判定信息不足: ["球员与球队的关联字段（如 football_appearances 缺少 teamID，无法将球员归属到具体球队）"] |
| 258 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 1 行) |
| 264 | falcon_dev_26 | exec_error | 0 | SQL 执行失败: (pymysql.err.ProgrammingError) (1064, "You have an error in your SQL syntax; check the manual that corresponds |
| 263 | falcon_dev_20 | ok | 1 | multiset_r2 |
| 265 | falcon_dev_8 | wrong_answer | 0 | value_mismatch (pred 23 行 vs 标准答案 10 行) |
| 266 | falcon_dev_20 | ok | 1 | multiset |
| 270 | falcon_dev_28 | wrong_answer | 0 | value_mismatch (pred 36 行 vs 标准答案 36 行) |
| 271 | falcon_dev_16 | exec_error | 0 | SQL 执行失败: (pymysql.err.ProgrammingError) (1064, "You have an error in your SQL syntax; check the manual that corresponds |
| 272 | falcon_dev_21 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 5 行) |
| 278 | falcon_dev_17 | ok | 1 | multiset |
| 277 | falcon_dev_19 | ok | 1 | multiset |
| 267 | falcon_dev_26 | need_more_info | 0 | 系统判定信息不足: ["是否需要两个独立的结果集（每场比赛明细和球队平均）", "球队平均进球数是针对英超2015赛季所有球队，还是仅前五场比赛中的球队", "输出形态：是每场比赛一行附带主客队平均，还是两个分开的结果集"] |
| 280 | falcon_dev_7 | ok | 1 | ordered |
| 286 | falcon_dev_8 | wrong_answer | 0 | value_mismatch (pred 301 行 vs 标准答案 303 行) |
| 283 | falcon_dev_14 | ok | 1 | multiset |
| 282 | falcon_dev_26 | wrong_answer | 0 | value_mismatch (pred 4 行 vs 标准答案 41 行) |
| 292 | falcon_dev_20 | ok | 1 | multiset_perm |
| 291 | falcon_dev_7 | ok | 1 | multiset |
| 296 | falcon_dev_16 | need_more_info | 0 | 系统判定信息不足: ["学生所在城市字段：表中仅有 school_students.Address 自由文本，无城市列，无法确定如何提取'所在城市'", "（次要）比较对象口径：是针对某位特定学生（需提供学生ID或姓名），还是对全体学生逐一 |
| 297 | falcon_dev_5 | ok | 1 | multiset_perm_r2 |
| 294 | falcon_dev_14 | need_more_info | 0 | 系统判定信息不足: ["库存周转率的计算公式（如销售成本/平均库存，还是销售数量/平均库存）", "“开业三年后”的具体时间范围（是开业满三年后的那一年，还是从开业三年后至今）", "“同类商店”的分类标准（按城市、位置还是其他维度）",  |
| 298 | falcon_dev_5 | wrong_answer | 0 | value_mismatch (pred 16 行 vs 标准答案 2 行) |
| 302 | falcon_dev_18 | wrong_answer | 0 | value_mismatch (pred 5 行 vs 标准答案 3 行) |
| 293 | falcon_dev_14 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 1 行) |
| 305 | falcon_dev_28 | wrong_answer | 0 | value_mismatch (pred 1465 行 vs 标准答案 62 行) |
| 304 | falcon_dev_15 | wrong_answer | 0 | value_mismatch (pred 19 行 vs 标准答案 19 行) |
| 307 | falcon_dev_17 | ok | 1 | multiset |
| 308 | falcon_dev_18 | wrong_answer | 0 | value_mismatch (pred 3 行 vs 标准答案 24 行) |
| 300 | falcon_dev_26 | wrong_answer | 0 | value_mismatch (pred 715 行 vs 标准答案 715 行) |
