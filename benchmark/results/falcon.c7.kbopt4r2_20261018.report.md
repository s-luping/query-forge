# Baseline 评测汇总

- 题集: questions_falcon_batch4_r2  llm_config_id: 7
- 时间: 2026-10-18 16:28:39
- 题数: 6  EX: 0.5 (3/6)
- 状态分桶: {"wrong_answer": 3, "ok": 3}
- 平均耗时: 44.4s  Token: {"prompt": 10774, "completion": 6944}

| qid | schema | status | EX | note |
|---|---|---|---|---|
| 218 | falcon_dev_5 | wrong_answer | 0 | value_mismatch (pred 33 行 vs 标准答案 34 行) |
| 136 | falcon_dev_18 | wrong_answer | 0 | value_mismatch (pred 23 行 vs 标准答案 23 行) |
| 273 | falcon_dev_18 | ok | 1 | multiset |
| 284 | falcon_dev_17 | ok | 1 | multiset |
| 295 | falcon_dev_5 | ok | 1 | multiset_perm |
| 298 | falcon_dev_5 | wrong_answer | 0 | value_mismatch (pred 15 行 vs 标准答案 2 行) |
