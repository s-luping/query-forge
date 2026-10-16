# Baseline 评测汇总

- 题集: questions_falcon  llm_config_id: 5
- 时间: 2026-10-16 01:58:52
- 题数: 309  EX: 0.0065 (2/309)
- 状态分桶: {"wrong_answer": 17, "need_more_info": 3, "ok": 2, "exec_error": 1, "error": 282, "row_limit": 2, "rate_limited": 2}
- 平均耗时: 35.7s  Token: {"prompt": 14689, "completion": 195562}


| qid | schema        | status         | EX | note                                                                                                                     |
| --- | ------------- | -------------- | -- | ------------------------------------------------------------------------------------------------------------------------ |
| 0   | falcon_dev_14 | wrong_answer   | 0  | value_mismatch (pred 4 行 vs 标准答案 4 行)                                                                                    |
| 2   | falcon_dev_16 | need_more_info | 0  | 系统判定信息不足: ["学生单科目成绩的计算规则（如指定某次考试、某时间范围的考试，或取该科目所有考试的平均分/最高分等作为排名依据）"]                                                    |
| 4   | falcon_dev_20 | wrong_answer   | 0  | empty_mismatch (pred 0 行 vs 标准答案 18 行)                                                                                   |
| 1   | falcon_dev_20 | wrong_answer   | 0  | empty_mismatch (pred 0 行 vs 标准答案 5 行)                                                                                    |
| 5   | falcon_dev_28 | need_more_info | 0  | 系统判定信息不足: ["结构化的州（state）字段（现有客户表仅含未拆分的text类型address字段，无法直接用于分组统计）", "客户address字段中州信息的提取规则"]                              |
| 6   | falcon_dev_4  | need_more_info | 0  | 系统判定信息不足: ["客户所属行业的相关字段/数据", "客户逾期天数超过行业平均值的判定口径（如平均逾期天数、最大逾期天数、至少一笔逾期超标等）"]                                             |
| 8   | falcon_dev_8  | wrong_answer   | 0  | value_mismatch (pred 6 行 vs 标准答案 6 行)                                                                                    |
| 7   | falcon_dev_8  | wrong_answer   | 0  | value_mismatch (pred 43 行 vs 标准答案 43 行)                                                                                  |
| 3   | falcon_dev_16 | ok             | 1  | multiset                                                                                                                 |
| 9   | falcon_dev_14 | wrong_answer   | 0  | empty_mismatch (pred 0 行 vs 标准答案 2 行)                                                                                    |
| 10  | falcon_dev_8  | exec_error     | 0  | SQL 执行失败: (pymysql.err.ProgrammingError) (1064, "You have an error in your SQL syntax; check the manual that corresponds |
| 11  | falcon_dev_8  | ok             | 1  | multiset                                                                                                                 |
| 13  | falcon_dev_17 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 12  | falcon_dev_24 | row_limit      | 0  | 标准答案 939 行超服务端 max_rows=100 截断                                                                                           |
| 15  | falcon_dev_14 | wrong_answer   | 0  | empty_mismatch (pred 0 行 vs 标准答案 4 行)                                                                                    |
| 16  | falcon_dev_28 | wrong_answer   | 0  | empty_mismatch (pred 0 行 vs 标准答案 3 行)                                                                                    |
| 14  | falcon_dev_21 | wrong_answer   | 0  | value_mismatch (pred 3 行 vs 标准答案 3 行)                                                                                    |
| 17  | falcon_dev_4  | wrong_answer   | 0  | empty_mismatch (pred 0 行 vs 标准答案 3 行)                                                                                    |
| 19  | falcon_dev_14 | wrong_answer   | 0  | value_mismatch (pred 5 行 vs 标准答案 1 行)                                                                                    |
| 18  | falcon_dev_19 | wrong_answer   | 0  | value_mismatch (pred 25 行 vs 标准答案 24 行)                                                                                  |
| 20  | falcon_dev_14 | wrong_answer   | 0  | empty_mismatch (pred 0 行 vs 标准答案 1 行)                                                                                    |
| 21  | falcon_dev_14 | wrong_answer   | 0  | value_mismatch (pred 13 行 vs 标准答案 20 行)                                                                                  |
| 22  | falcon_dev_28 | row_limit      | 0  | 标准答案 298 行超服务端 max_rows=100 截断                                                                                           |
| 23  | falcon_dev_14 | wrong_answer   | 0  | value_mismatch (pred 1 行 vs 标准答案 1 行)                                                                                    |
| 25  | falcon_dev_26 | wrong_answer   | 0  | value_mismatch (pred 10 行 vs 标准答案 10 行)                                                                                  |
| 26  | falcon_dev_20 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 28  | falcon_dev_4  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 29  | falcon_dev_8  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 30  | falcon_dev_16 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 31  | falcon_dev_17 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 32  | falcon_dev_18 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 33  | falcon_dev_18 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 24  | falcon_dev_15 | wrong_answer   | 0  | empty_mismatch (pred 0 行 vs 标准答案 1 行)                                                                                    |
| 34  | falcon_dev_21 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 36  | falcon_dev_17 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 37  | falcon_dev_24 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 38  | falcon_dev_15 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 35  | falcon_dev_18 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 39  | falcon_dev_26 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 40  | falcon_dev_4  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 41  | falcon_dev_20 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 42  | falcon_dev_21 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 43  | falcon_dev_26 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 45  | falcon_dev_28 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 46  | falcon_dev_24 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 44  | falcon_dev_5  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 48  | falcon_dev_7  | rate_limited   | 0  | 服务端限流 429                                                                                                                |
| 49  | falcon_dev_28 | rate_limited   | 0  | 服务端限流 429                                                                                                                |
| 47  | falcon_dev_26 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 50  | falcon_dev_24 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 52  | falcon_dev_7  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 53  | falcon_dev_4  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 54  | falcon_dev_4  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 51  | falcon_dev_9  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 55  | falcon_dev_20 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 56  | falcon_dev_5  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 57  | falcon_dev_4  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 58  | falcon_dev_16 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 59  | falcon_dev_5  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 60  | falcon_dev_8  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 62  | falcon_dev_18 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 61  | falcon_dev_21 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 63  | falcon_dev_18 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 64  | falcon_dev_15 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 65  | falcon_dev_15 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 67  | falcon_dev_26 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 27  | falcon_dev_20 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 68  | falcon_dev_26 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 66  | falcon_dev_21 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 71  | falcon_dev_15 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 70  | falcon_dev_16 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 72  | falcon_dev_14 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 73  | falcon_dev_24 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 69  | falcon_dev_15 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 75  | falcon_dev_26 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 76  | falcon_dev_26 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 78  | falcon_dev_15 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 74  | falcon_dev_14 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 80  | falcon_dev_20 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 79  | falcon_dev_15 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 77  | falcon_dev_4  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 81  | falcon_dev_26 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 83  | falcon_dev_21 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 84  | falcon_dev_4  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 85  | falcon_dev_5  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 86  | falcon_dev_26 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 87  | falcon_dev_20 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 88  | falcon_dev_14 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 89  | falcon_dev_5  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 82  | falcon_dev_14 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 91  | falcon_dev_26 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 93  | falcon_dev_7  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 92  | falcon_dev_15 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 90  | falcon_dev_28 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 96  | falcon_dev_8  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 95  | falcon_dev_16 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 97  | falcon_dev_5  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 94  | falcon_dev_18 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 100 | falcon_dev_14 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 101 | falcon_dev_21 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 102 | falcon_dev_9  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 99  | falcon_dev_28 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 103 | falcon_dev_18 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 104 | falcon_dev_9  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 98  | falcon_dev_26 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 105 | falcon_dev_28 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 108 | falcon_dev_9  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 109 | falcon_dev_20 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 110 | falcon_dev_15 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 107 | falcon_dev_18 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 111 | falcon_dev_18 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 112 | falcon_dev_14 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 113 | falcon_dev_21 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 106 | falcon_dev_15 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 115 | falcon_dev_4  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 116 | falcon_dev_21 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 118 | falcon_dev_4  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 114 | falcon_dev_20 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 119 | falcon_dev_16 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 120 | falcon_dev_14 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 117 | falcon_dev_26 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 121 | falcon_dev_19 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 122 | falcon_dev_16 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 124 | falcon_dev_19 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 125 | falcon_dev_16 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 126 | falcon_dev_8  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 128 | falcon_dev_5  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 127 | falcon_dev_15 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 129 | falcon_dev_15 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 123 | falcon_dev_28 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 131 | falcon_dev_20 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 132 | falcon_dev_20 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 134 | falcon_dev_14 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 133 | falcon_dev_21 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 135 | falcon_dev_15 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 136 | falcon_dev_18 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 137 | falcon_dev_24 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 130 | falcon_dev_7  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 138 | falcon_dev_21 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 139 | falcon_dev_21 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 142 | falcon_dev_14 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 140 | falcon_dev_15 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 144 | falcon_dev_17 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 143 | falcon_dev_8  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 145 | falcon_dev_20 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 141 | falcon_dev_14 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 148 | falcon_dev_24 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 146 | falcon_dev_17 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 150 | falcon_dev_20 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 147 | falcon_dev_8  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 151 | falcon_dev_4  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 152 | falcon_dev_4  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 153 | falcon_dev_21 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 149 | falcon_dev_4  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 155 | falcon_dev_4  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 157 | falcon_dev_28 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 156 | falcon_dev_5  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 158 | falcon_dev_15 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 159 | falcon_dev_24 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 160 | falcon_dev_4  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 161 | falcon_dev_21 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 154 | falcon_dev_14 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 163 | falcon_dev_17 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 165 | falcon_dev_16 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 166 | falcon_dev_21 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 164 | falcon_dev_24 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 167 | falcon_dev_8  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 168 | falcon_dev_26 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 169 | falcon_dev_21 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 162 | falcon_dev_28 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 172 | falcon_dev_14 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 171 | falcon_dev_14 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 173 | falcon_dev_14 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 174 | falcon_dev_28 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 175 | falcon_dev_15 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 176 | falcon_dev_7  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 177 | falcon_dev_20 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 170 | falcon_dev_5  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 178 | falcon_dev_8  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 179 | falcon_dev_20 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 182 | falcon_dev_24 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 181 | falcon_dev_4  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 183 | falcon_dev_15 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 184 | falcon_dev_20 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 180 | falcon_dev_15 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 185 | falcon_dev_28 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 186 | falcon_dev_15 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 189 | falcon_dev_21 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 188 | falcon_dev_19 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 187 | falcon_dev_21 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 192 | falcon_dev_7  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 191 | falcon_dev_21 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 190 | falcon_dev_21 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 193 | falcon_dev_14 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 195 | falcon_dev_4  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 194 | falcon_dev_21 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 197 | falcon_dev_9  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 198 | falcon_dev_19 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 200 | falcon_dev_15 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 199 | falcon_dev_24 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 201 | falcon_dev_26 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 196 | falcon_dev_17 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 203 | falcon_dev_21 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 202 | falcon_dev_19 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 206 | falcon_dev_18 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 204 | falcon_dev_17 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 208 | falcon_dev_24 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 207 | falcon_dev_15 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 209 | falcon_dev_14 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 205 | falcon_dev_26 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 211 | falcon_dev_21 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 212 | falcon_dev_4  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 213 | falcon_dev_19 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 215 | falcon_dev_20 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 210 | falcon_dev_8  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 216 | falcon_dev_20 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 214 | falcon_dev_24 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 217 | falcon_dev_15 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 218 | falcon_dev_5  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 219 | falcon_dev_26 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 220 | falcon_dev_21 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 221 | falcon_dev_15 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 224 | falcon_dev_16 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 223 | falcon_dev_17 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 222 | falcon_dev_26 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 225 | falcon_dev_21 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 228 | falcon_dev_16 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 227 | falcon_dev_17 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 230 | falcon_dev_24 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 226 | falcon_dev_20 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 232 | falcon_dev_21 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 231 | falcon_dev_9  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 233 | falcon_dev_21 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 229 | falcon_dev_19 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 235 | falcon_dev_21 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 237 | falcon_dev_26 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 234 | falcon_dev_14 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 238 | falcon_dev_20 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 239 | falcon_dev_14 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 240 | falcon_dev_21 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 236 | falcon_dev_15 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 241 | falcon_dev_21 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 243 | falcon_dev_15 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 242 | falcon_dev_18 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 245 | falcon_dev_21 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 246 | falcon_dev_21 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 247 | falcon_dev_5  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 248 | falcon_dev_4  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 244 | falcon_dev_17 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 249 | falcon_dev_9  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 250 | falcon_dev_26 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 253 | falcon_dev_4  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 251 | falcon_dev_28 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 252 | falcon_dev_15 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 256 | falcon_dev_7  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 255 | falcon_dev_20 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 257 | falcon_dev_14 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 254 | falcon_dev_15 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 259 | falcon_dev_20 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 260 | falcon_dev_19 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 258 | falcon_dev_20 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 261 | falcon_dev_21 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 264 | falcon_dev_26 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 263 | falcon_dev_20 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 265 | falcon_dev_8  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 262 | falcon_dev_24 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 268 | falcon_dev_14 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 266 | falcon_dev_20 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 269 | falcon_dev_16 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 267 | falcon_dev_26 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 271 | falcon_dev_16 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 272 | falcon_dev_21 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 273 | falcon_dev_18 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 270 | falcon_dev_28 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 276 | falcon_dev_20 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 277 | falcon_dev_19 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 275 | falcon_dev_5  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 274 | falcon_dev_18 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 279 | falcon_dev_20 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 280 | falcon_dev_7  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 278 | falcon_dev_17 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 281 | falcon_dev_8  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 282 | falcon_dev_26 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 285 | falcon_dev_24 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 286 | falcon_dev_8  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 283 | falcon_dev_14 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 287 | falcon_dev_16 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 288 | falcon_dev_9  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 289 | falcon_dev_24 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 284 | falcon_dev_17 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 291 | falcon_dev_7  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 290 | falcon_dev_21 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 292 | falcon_dev_20 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 294 | falcon_dev_14 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 295 | falcon_dev_5  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 296 | falcon_dev_16 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 297 | falcon_dev_5  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 293 | falcon_dev_14 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 298 | falcon_dev_5  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 300 | falcon_dev_26 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 299 | falcon_dev_14 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 301 | falcon_dev_28 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 303 | falcon_dev_14 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 304 | falcon_dev_15 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 305 | falcon_dev_28 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 302 | falcon_dev_18 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 306 | falcon_dev_4  | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 307 | falcon_dev_17 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |
| 308 | falcon_dev_18 | error          | 0  | HTTPError: 500 Server Error: Internal Server Error for url: <http://localhost:8888/api/conversation>                     |


