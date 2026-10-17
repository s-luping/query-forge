# Baseline 评测汇总

- 题集: questions_falcon  llm_config_id: 7
- 时间: 2026-10-17 22:28:58
- 题数: 35  EX: 0.4286 (15/35)
- 状态分桶: {"ok": 15, "wrong_answer": 17, "need_more_info": 1, "exec_error": 2}
- 平均耗时: 99.1s  Token: {"prompt": 38655, "completion": 93533}

| qid | schema | status | EX | note |
|---|---|---|---|---|
| 0 | falcon_dev_14 | ok | 1 | multiset |
| 1 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 5 行 vs 标准答案 5 行) |
| 2 | falcon_dev_16 | ok | 1 | multiset |
| 4 | falcon_dev_20 | ok | 1 | multiset_perm |
| 5 | falcon_dev_28 | need_more_info | 0 | 系统判定信息不足: ["客户所属州字段：customers 表无 state 列，address 为自由文本且无格式说明，无法按州分组计算成功率", "若州信息包含在 address 中，缺少地址格式及州提取规则（如是否为'街道, 城市,  |
| 7 | falcon_dev_8 | wrong_answer | 0 | value_mismatch (pred 43 行 vs 标准答案 43 行) |
| 3 | falcon_dev_16 | ok | 1 | multiset |
| 8 | falcon_dev_8 | wrong_answer | 0 | value_mismatch (pred 6 行 vs 标准答案 6 行) |
| 9 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 2 行 vs 标准答案 2 行) |
| 6 | falcon_dev_4 | ok | 1 | multiset |
| 11 | falcon_dev_8 | ok | 1 | multiset |
| 10 | falcon_dev_8 | ok | 1 | multiset |
| 12 | falcon_dev_24 | wrong_answer | 0 | value_mismatch (pred 1104 行 vs 标准答案 939 行) |
| 15 | falcon_dev_14 | ok | 1 | multiset |
| 16 | falcon_dev_28 | wrong_answer | 0 | value_mismatch (pred 3 行 vs 标准答案 3 行) |
| 14 | falcon_dev_21 | exec_error | 0 | SQL 执行失败: (pymysql.err.OperationalError) (1055, "Expression #2 of PARTITION BY or ORDER BY clause of window '<unnamed wi |
| 17 | falcon_dev_4 | ok | 1 | multiset_perm |
| 18 | falcon_dev_19 | wrong_answer | 0 | value_mismatch (pred 63 行 vs 标准答案 24 行) |
| 13 | falcon_dev_17 | ok | 1 | multiset_perm |
| 19 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 1 行) |
| 20 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 2 行 vs 标准答案 1 行) |
| 21 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 400 行 vs 标准答案 20 行) |
| 23 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 1 行) |
| 25 | falcon_dev_26 | wrong_answer | 0 | value_mismatch (pred 10 行 vs 标准答案 10 行) |
| 24 | falcon_dev_15 | ok | 1 | multiset |
| 26 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 54 行 vs 标准答案 1 行) |
| 27 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 22 行 vs 标准答案 22 行) |
| 28 | falcon_dev_4 | wrong_answer | 0 | value_mismatch (pred 75 行 vs 标准答案 75 行) |
| 29 | falcon_dev_8 | exec_error | 0 | SQL 执行失败: (pymysql.err.OperationalError) (1054, "Unknown column 'installs_num' in 'window order by'")
[SQL: WITH cleaned |
| 30 | falcon_dev_16 | ok | 1 | multiset |
| 32 | falcon_dev_18 | ok | 1 | multiset |
| 33 | falcon_dev_18 | ok | 1 | multiset |
| 31 | falcon_dev_17 | ok | 1 | multiset_perm |
| 34 | falcon_dev_21 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 1 行) |
| 22 | falcon_dev_28 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 298 行) |
