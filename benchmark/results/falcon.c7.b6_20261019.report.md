# Baseline 评测汇总

- 题集: questions_falcon_b6  llm_config_id: 7
- 时间: 2026-10-19 02:15:06
- 题数: 10  EX: 0.4 (4/10)
- 状态分桶: {"ok": 4, "wrong_answer": 5, "timeout": 1}
- 平均耗时: 172.2s  Token: {"prompt": 27211, "completion": 20696}

| qid | schema | status | EX | note |
|---|---|---|---|---|
| 20 | falcon_dev_14 | ok | 1 | ordered |
| 19 | falcon_dev_14 | ok | 1 | multiset_perm |
| 30 | falcon_dev_16 | wrong_answer | 0 | value_mismatch (pred 6 行 vs 标准答案 10 行) |
| 52 | falcon_dev_7 | wrong_answer | 0 | value_mismatch (pred 23 行 vs 标准答案 724 行) |
| 98 | falcon_dev_26 | wrong_answer | 0 | value_mismatch (pred 95 行 vs 标准答案 95 行) |
| 23 | falcon_dev_14 | ok | 1 | multiset_r2 |
| 141 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 1 行) |
| 264 | falcon_dev_26 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 1 行) |
| 305 | falcon_dev_28 | ok | 1 | multiset |
| 117 | falcon_dev_26 | timeout | 0 | 客户端超时(600s) |
