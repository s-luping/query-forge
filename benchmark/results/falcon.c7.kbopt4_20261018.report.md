# Baseline 评测汇总

- 题集: questions_falcon_batch4  llm_config_id: 7
- 时间: 2026-10-18 16:21:11
- 题数: 11  EX: 0.2727 (3/11)
- 状态分桶: {"ok": 3, "wrong_answer": 7, "exec_error": 1}
- 平均耗时: 62.1s  Token: {"prompt": 15211, "completion": 12326}

| qid | schema | status | EX | note |
|---|---|---|---|---|
| 104 | falcon_dev_9 | ok | 1 | multiset |
| 136 | falcon_dev_18 | wrong_answer | 0 | value_mismatch (pred 23 行 vs 标准答案 23 行) |
| 242 | falcon_dev_18 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 1 行) |
| 218 | falcon_dev_5 | wrong_answer | 0 | value_mismatch (pred 33 行 vs 标准答案 34 行) |
| 247 | falcon_dev_5 | ok | 1 | multiset |
| 273 | falcon_dev_18 | exec_error | 0 | SQL 执行失败: (pymysql.err.NotSupportedError) (1235, "This version of MySQL doesn't yet support 'LIMIT & IN/ALL/ANY/SOME sub |
| 288 | falcon_dev_9 | ok | 1 | multiset |
| 284 | falcon_dev_17 | wrong_answer | 0 | value_mismatch (pred 10 行 vs 标准答案 3 行) |
| 297 | falcon_dev_5 | wrong_answer | 0 | value_mismatch (pred 3 行 vs 标准答案 3 行) |
| 295 | falcon_dev_5 | wrong_answer | 0 | value_mismatch (pred 636 行 vs 标准答案 636 行) |
| 298 | falcon_dev_5 | wrong_answer | 0 | value_mismatch (pred 15 行 vs 标准答案 2 行) |
