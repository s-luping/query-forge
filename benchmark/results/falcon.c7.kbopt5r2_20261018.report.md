# Baseline 评测汇总

- 题集: questions_falcon_batch5_r2  llm_config_id: 7
- 时间: 2026-10-18 17:29:51
- 题数: 5  EX: 0.6 (3/5)
- 状态分桶: {"ok": 3, "wrong_answer": 2}
- 平均耗时: 106.9s  Token: {"prompt": 8706, "completion": 8875}

| qid | schema | status | EX | note |
|---|---|---|---|---|
| 42 | falcon_dev_21 | ok | 1 | multiset_perm |
| 20 | falcon_dev_14 | ok | 1 | ordered |
| 113 | falcon_dev_21 | ok | 1 | multiset |
| 134 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 20 行 vs 标准答案 9 行) |
| 191 | falcon_dev_21 | wrong_answer | 0 | value_mismatch (pred 40 行 vs 标准答案 40 行) |
