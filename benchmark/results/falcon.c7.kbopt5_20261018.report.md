# Baseline 评测汇总

- 题集: questions_falcon_batch5  llm_config_id: 7
- 时间: 2026-10-18 17:21:00
- 题数: 10  EX: 0.4 (4/10)
- 状态分桶: {"wrong_answer": 6, "ok": 4}
- 平均耗时: 84.8s  Token: {"prompt": 15013, "completion": 24273}

| qid | schema | status | EX | note |
|---|---|---|---|---|
| 20 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 1 行) |
| 9 | falcon_dev_14 | ok | 1 | multiset_r2 |
| 82 | falcon_dev_14 | ok | 1 | multiset |
| 113 | falcon_dev_21 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 3 行) |
| 134 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 8 行 vs 标准答案 9 行) |
| 154 | falcon_dev_14 | ok | 1 | multiset |
| 191 | falcon_dev_21 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 40 行) |
| 209 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 2 行 vs 标准答案 1 行) |
| 299 | falcon_dev_14 | ok | 1 | multiset |
| 42 | falcon_dev_21 | wrong_answer | 0 | value_mismatch (pred 17 行 vs 标准答案 33 行) |
