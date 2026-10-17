# Baseline 评测汇总

- 题集: questions_falcon  llm_config_id: 7
- 时间: 2026-10-17 19:47:30
- 题数: 309  EX: 0.3042 (94/309)
- 状态分桶: {"ok": 94, "wrong_answer": 174, "need_more_info": 26, "exec_error": 11, "row_limit": 1, "error": 3}
- 平均耗时: 148.2s  Token: {"prompt": 175119, "completion": 427200}

| qid | schema | status | EX | note |
|---|---|---|---|---|
| 0 | falcon_dev_14 | ok | 1 | multiset_perm |
| 2 | falcon_dev_16 | ok | 1 | multiset_perm |
| 4 | falcon_dev_20 | ok | 1 | multiset_perm |
| 1 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 5 行 vs 标准答案 5 行) |
| 3 | falcon_dev_16 | ok | 1 | multiset |
| 5 | falcon_dev_28 | need_more_info | 0 | 系统判定信息不足: ["客户所属州字段：customers 表缺少 state/州 独立字段，仅有 address 文本字段", "address 字段的数据格式未知，无法确认能否从中解析出州信息（如是否为'城市, 州, 邮编'格式）"] |
| 8 | falcon_dev_8 | wrong_answer | 0 | value_mismatch (pred 6 行 vs 标准答案 6 行) |
| 7 | falcon_dev_8 | wrong_answer | 0 | value_mismatch (pred 43 行 vs 标准答案 43 行) |
| 6 | falcon_dev_4 | ok | 1 | multiset |
| 10 | falcon_dev_8 | wrong_answer | 0 | value_mismatch (pred 3 行 vs 标准答案 3 行) |
| 9 | falcon_dev_14 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 2 行) |
| 11 | falcon_dev_8 | ok | 1 | multiset |
| 12 | falcon_dev_24 | ok | 1 | multiset_perm |
| 15 | falcon_dev_14 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 4 行) |
| 14 | falcon_dev_21 | ok | 1 | multiset_perm |
| 17 | falcon_dev_4 | ok | 1 | multiset_perm |
| 13 | falcon_dev_17 | ok | 1 | multiset |
| 16 | falcon_dev_28 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 3 行) |
| 19 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 8 行 vs 标准答案 1 行) |
| 20 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 1 行) |
| 18 | falcon_dev_19 | ok | 1 | multiset_perm |
| 22 | falcon_dev_28 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 298 行) |
| 21 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 13 行 vs 标准答案 20 行) |
| 23 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 1 行) |
| 24 | falcon_dev_15 | ok | 1 | multiset |
| 27 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 22 行 vs 标准答案 22 行) |
| 25 | falcon_dev_26 | wrong_answer | 0 | value_mismatch (pred 10 行 vs 标准答案 10 行) |
| 26 | falcon_dev_20 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 1 行) |
| 30 | falcon_dev_16 | wrong_answer | 0 | value_mismatch (pred 6 行 vs 标准答案 10 行) |
| 29 | falcon_dev_8 | exec_error | 0 | SQL 执行失败: (pymysql.err.ProgrammingError) (1064, "You have an error in your SQL syntax; check the manual that corresponds |
| 31 | falcon_dev_17 | ok | 1 | multiset_perm |
| 33 | falcon_dev_18 | ok | 1 | multiset_perm |
| 32 | falcon_dev_18 | ok | 1 | multiset |
| 34 | falcon_dev_21 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 1 行) |
| 35 | falcon_dev_18 | ok | 1 | multiset_perm |
| 37 | falcon_dev_24 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 1704 行) |
| 36 | falcon_dev_17 | ok | 1 | multiset |
| 38 | falcon_dev_15 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 3 行) |
| 40 | falcon_dev_4 | wrong_answer | 0 | value_mismatch (pred 2 行 vs 标准答案 1 行) |
| 39 | falcon_dev_26 | wrong_answer | 0 | value_mismatch (pred 100 行 vs 标准答案 380 行) |
| 41 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 100 行 vs 标准答案 46 行) |
| 28 | falcon_dev_4 | wrong_answer | 0 | value_mismatch (pred 75 行 vs 标准答案 75 行) |
| 43 | falcon_dev_26 | ok | 1 | multiset_perm |
| 42 | falcon_dev_21 | wrong_answer | 0 | value_mismatch (pred 32 行 vs 标准答案 33 行) |
| 44 | falcon_dev_5 | ok | 1 | multiset_perm |
| 45 | falcon_dev_28 | wrong_answer | 0 | value_mismatch (pred 5 行 vs 标准答案 5 行) |
| 46 | falcon_dev_24 | ok | 1 | multiset |
| 48 | falcon_dev_7 | wrong_answer | 0 | value_mismatch (pred 10 行 vs 标准答案 10 行) |
| 49 | falcon_dev_28 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 3 行) |
| 50 | falcon_dev_24 | ok | 1 | multiset_perm |
| 51 | falcon_dev_9 | need_more_info | 0 | 系统判定信息不足: ["总人口字段或互联网用户渗透率字段", "连续三年的具体时间范围或定义"] |
| 53 | falcon_dev_4 | wrong_answer | 0 | value_mismatch (pred 37 行 vs 标准答案 48 行) |
| 52 | falcon_dev_7 | wrong_answer | 0 | value_mismatch (pred 23 行 vs 标准答案 724 行) |
| 55 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 4 行 vs 标准答案 3 行) |
| 56 | falcon_dev_5 | wrong_answer | 0 | value_mismatch (pred 9 行 vs 标准答案 9 行) |
| 57 | falcon_dev_4 | ok | 1 | ordered |
| 54 | falcon_dev_4 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 64 行) |
| 59 | falcon_dev_5 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 4 行) |
| 58 | falcon_dev_16 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 1 行) |
| 60 | falcon_dev_8 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 2 行) |
| 61 | falcon_dev_21 | wrong_answer | 0 | value_mismatch (pred 15 行 vs 标准答案 15 行) |
| 63 | falcon_dev_18 | ok | 1 | ordered |
| 62 | falcon_dev_18 | ok | 1 | ordered |
| 65 | falcon_dev_15 | ok | 1 | multiset_perm |
| 66 | falcon_dev_21 | wrong_answer | 0 | value_mismatch (pred 4 行 vs 标准答案 4 行) |
| 64 | falcon_dev_15 | wrong_answer | 0 | value_mismatch (pred 20 行 vs 标准答案 19 行) |
| 47 | falcon_dev_26 | need_more_info | 0 | 系统判定信息不足: ["射门记录与球队的关联字段（如 football_shots.teamID 或 football_appearances.teamID）", "头球射门在 shotType 字段中的具体取值（如 'Head'）"] |
| 67 | falcon_dev_26 | wrong_answer | 0 | value_mismatch (pred 197 行 vs 标准答案 197 行) |
| 70 | falcon_dev_16 | ok | 1 | multiset |
| 71 | falcon_dev_15 | wrong_answer | 0 | value_mismatch (pred 13 行 vs 标准答案 13 行) |
| 68 | falcon_dev_26 | wrong_answer | 0 | value_mismatch (pred 10 行 vs 标准答案 52 行) |
| 72 | falcon_dev_14 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 3 行) |
| 73 | falcon_dev_24 | row_limit | 0 | 标准答案 11723 行超服务端 max_rows=2000 截断 |
| 74 | falcon_dev_14 | ok | 1 | multiset_perm |
| 75 | falcon_dev_26 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 144 行) |
| 76 | falcon_dev_26 | ok | 1 | multiset |
| 78 | falcon_dev_15 | ok | 1 | multiset_perm |
| 69 | falcon_dev_15 | wrong_answer | 0 | value_mismatch (pred 2 行 vs 标准答案 2 行) |
| 77 | falcon_dev_4 | ok | 1 | multiset_perm |
| 80 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 21 行 vs 标准答案 22 行) |
| 81 | falcon_dev_26 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 98 行) |
| 82 | falcon_dev_14 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 3 行) |
| 83 | falcon_dev_21 | wrong_answer | 0 | value_mismatch (pred 3 行 vs 标准答案 2 行) |
| 84 | falcon_dev_4 | ok | 1 | ordered |
| 85 | falcon_dev_5 | wrong_answer | 0 | value_mismatch (pred 75 行 vs 标准答案 79 行) |
| 79 | falcon_dev_15 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 1 行) |
| 86 | falcon_dev_26 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 1 行) |
| 89 | falcon_dev_5 | error | 0 | HTTPError: 500 Server Error: Internal Server Error for url: http://localhost:8888/api/conversation |
| 87 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 1 行) |
| 90 | falcon_dev_28 | ok | 1 | multiset |
| 92 | falcon_dev_15 | wrong_answer | 0 | value_mismatch (pred 3 行 vs 标准答案 3 行) |
| 93 | falcon_dev_7 | ok | 1 | ordered |
| 94 | falcon_dev_18 | ok | 1 | multiset_perm |
| 95 | falcon_dev_16 | need_more_info | 0 | 系统判定信息不足: ["用于表示'地区'的字段（如城市/省份/区域），当前仅有 school_students.Address 详细地址字段，无法直接作为地区分组依据"] |
| 91 | falcon_dev_26 | wrong_answer | 0 | value_mismatch (pred 20 行 vs 标准答案 20 行) |
| 96 | falcon_dev_8 | ok | 1 | multiset |
| 88 | falcon_dev_14 | exec_error | 0 | SQL 执行失败: (pymysql.err.ProgrammingError) (1064, "You have an error in your SQL syntax; check the manual that corresponds |
| 98 | falcon_dev_26 | wrong_answer | 0 | value_mismatch (pred 95 行 vs 标准答案 95 行) |
| 97 | falcon_dev_5 | wrong_answer | 0 | value_mismatch (pred 112 行 vs 标准答案 112 行) |
| 101 | falcon_dev_21 | ok | 1 | multiset_perm |
| 100 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 12 行 vs 标准答案 12 行) |
| 103 | falcon_dev_18 | need_more_info | 0 | 系统判定信息不足: ["包含订单信息的表（订单金额、订单编号等）", "订单所属州（state）字段", "支付方式字段（用于筛选信用卡支付）", "运费字段（用于与平均值比较）"] |
| 104 | falcon_dev_9 | wrong_answer | 0 | value_mismatch (pred 222 行 vs 标准答案 223 行) |
| 102 | falcon_dev_9 | ok | 1 | multiset |
| 105 | falcon_dev_28 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 69 行) |
| 106 | falcon_dev_15 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 1 行) |
| 108 | falcon_dev_9 | ok | 1 | ordered |
| 107 | falcon_dev_18 | ok | 1 | multiset_perm |
| 110 | falcon_dev_15 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 3 行) |
| 109 | falcon_dev_20 | ok | 1 | multiset_perm |
| 111 | falcon_dev_18 | ok | 1 | multiset_perm |
| 112 | falcon_dev_14 | exec_error | 0 | SQL 执行失败: (pymysql.err.NotSupportedError) (1235, "This version of MySQL doesn't yet support 'LIMIT & IN/ALL/ANY/SOME sub |
| 113 | falcon_dev_21 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 3 行) |
| 115 | falcon_dev_4 | wrong_answer | 0 | value_mismatch (pred 83 行 vs 标准答案 83 行) |
| 114 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 5 行) |
| 116 | falcon_dev_21 | ok | 1 | multiset |
| 99 | falcon_dev_28 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 1 行) |
| 119 | falcon_dev_16 | ok | 1 | multiset_perm |
| 118 | falcon_dev_4 | wrong_answer | 0 | value_mismatch (pred 5 行 vs 标准答案 5 行) |
| 120 | falcon_dev_14 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 7 行) |
| 122 | falcon_dev_16 | ok | 1 | multiset_perm |
| 117 | falcon_dev_26 | exec_error | 0 | SQL 执行失败: (pymysql.err.OperationalError) (1054, "Unknown column 'fp.season' in 'where clause'")
[SQL: SELECT
    p.playe |
| 121 | falcon_dev_19 | ok | 1 | ordered |
| 123 | falcon_dev_28 | wrong_answer | 0 | value_mismatch (pred 100 行 vs 标准答案 14 行) |
| 125 | falcon_dev_16 | wrong_answer | 0 | value_mismatch (pred 2 行 vs 标准答案 2 行) |
| 124 | falcon_dev_19 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 3 行) |
| 126 | falcon_dev_8 | exec_error | 0 | SQL 执行失败: (pymysql.err.OperationalError) (1054, "Unknown column 'install_num' in 'window order by'")
[SQL: WITH cleaned  |
| 127 | falcon_dev_15 | wrong_answer | 0 | value_mismatch (pred 3 行 vs 标准答案 3 行) |
| 128 | falcon_dev_5 | wrong_answer | 0 | value_mismatch (pred 239 行 vs 标准答案 239 行) |
| 130 | falcon_dev_7 | wrong_answer | 0 | value_mismatch (pred 9 行 vs 标准答案 9 行) |
| 131 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 1 行) |
| 133 | falcon_dev_21 | wrong_answer | 0 | value_mismatch (pred 2 行 vs 标准答案 2 行) |
| 129 | falcon_dev_15 | ok | 1 | multiset_perm |
| 132 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 5 行 vs 标准答案 5 行) |
| 135 | falcon_dev_15 | wrong_answer | 0 | value_mismatch (pred 3 行 vs 标准答案 3 行) |
| 134 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 9 行 vs 标准答案 9 行) |
| 136 | falcon_dev_18 | wrong_answer | 0 | value_mismatch (pred 23 行 vs 标准答案 23 行) |
| 138 | falcon_dev_21 | ok | 1 | multiset |
| 137 | falcon_dev_24 | ok | 1 | multiset_perm |
| 140 | falcon_dev_15 | wrong_answer | 0 | value_mismatch (pred 3 行 vs 标准答案 3 行) |
| 142 | falcon_dev_14 | ok | 1 | multiset_perm |
| 141 | falcon_dev_14 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 1 行) |
| 143 | falcon_dev_8 | ok | 1 | multiset_perm |
| 144 | falcon_dev_17 | need_more_info | 0 | 系统判定信息不足: ["利润的计算依据：缺少商品成本/进价等成本字段，无法从现有字段推导总利润"] |
| 145 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 1 行) |
| 147 | falcon_dev_8 | wrong_answer | 0 | value_mismatch (pred 46 行 vs 标准答案 44 行) |
| 148 | falcon_dev_24 | wrong_answer | 0 | value_mismatch (pred 100 行 vs 标准答案 267 行) |
| 139 | falcon_dev_21 | ok | 1 | multiset |
| 146 | falcon_dev_17 | ok | 1 | multiset |
| 149 | falcon_dev_4 | ok | 1 | multiset_perm |
| 150 | falcon_dev_20 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 120 行) |
| 151 | falcon_dev_4 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 2 行) |
| 152 | falcon_dev_4 | ok | 1 | multiset_perm |
| 153 | falcon_dev_21 | wrong_answer | 0 | value_mismatch (pred 200 行 vs 标准答案 135 行) |
| 154 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 3 行 vs 标准答案 8 行) |
| 155 | falcon_dev_4 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 5 行) |
| 156 | falcon_dev_5 | need_more_info | 0 | 系统判定信息不足: ["公司成立日期字段（如 founding_date/成立时间）：当前表仅有 date_joined（加入独角兽榜单日期），无法计算平均成立年限"] |
| 157 | falcon_dev_28 | need_more_info | 0 | 系统判定信息不足: ["商品库存量字段：已召回表中没有任何库存/stock/inventory 相关字段，order_items.quantity 为订单购买数量，不能代表商品库存"] |
| 158 | falcon_dev_15 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 13 行) |
| 159 | falcon_dev_24 | ok | 1 | multiset |
| 162 | falcon_dev_28 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 10 行) |
| 161 | falcon_dev_21 | ok | 1 | multiset |
| 164 | falcon_dev_24 | ok | 1 | multiset |
| 163 | falcon_dev_17 | ok | 1 | multiset |
| 166 | falcon_dev_21 | wrong_answer | 0 | value_mismatch (pred 3 行 vs 标准答案 3 行) |
| 165 | falcon_dev_16 | wrong_answer | 0 | value_mismatch (pred 10 行 vs 标准答案 10 行) |
| 160 | falcon_dev_4 | ok | 1 | ordered |
| 167 | falcon_dev_8 | wrong_answer | 0 | value_mismatch (pred 33 行 vs 标准答案 33 行) |
| 170 | falcon_dev_5 | wrong_answer | 0 | value_mismatch (pred 174 行 vs 标准答案 174 行) |
| 169 | falcon_dev_21 | ok | 1 | multiset_perm |
| 172 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 7 行 vs 标准答案 11 行) |
| 173 | falcon_dev_14 | ok | 1 | multiset |
| 174 | falcon_dev_28 | wrong_answer | 0 | value_mismatch (pred 100 行 vs 标准答案 3 行) |
| 175 | falcon_dev_15 | wrong_answer | 0 | value_mismatch (pred 2 行 vs 标准答案 2 行) |
| 176 | falcon_dev_7 | wrong_answer | 0 | value_mismatch (pred 578 行 vs 标准答案 578 行) |
| 177 | falcon_dev_20 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 2 行) |
| 171 | falcon_dev_14 | need_more_info | 0 | 系统判定信息不足: ["明确的国家字段或 Store_Location 的格式说明，以便过滤墨西哥的玩具店"] |
| 179 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 39 行 vs 标准答案 39 行) |
| 178 | falcon_dev_8 | ok | 1 | multiset |
| 181 | falcon_dev_4 | ok | 1 | multiset_perm |
| 180 | falcon_dev_15 | ok | 1 | multiset |
| 182 | falcon_dev_24 | wrong_answer | 0 | value_mismatch (pred 265 行 vs 标准答案 265 行) |
| 168 | falcon_dev_26 | exec_error | 0 | SQL 执行失败: (pymysql.err.ProgrammingError) (1111, 'Invalid use of group function')
[SQL: SELECT p.name
FROM football_appea |
| 183 | falcon_dev_15 | exec_error | 0 | SQL 执行失败: (pymysql.err.OperationalError) (1054, "Unknown column 'ccb.Customer_Segment' in 'field list'")
[SQL: SELECT
   |
| 184 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 45 行 vs 标准答案 5 行) |
| 185 | falcon_dev_28 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 365 行) |
| 186 | falcon_dev_15 | ok | 1 | multiset_perm |
| 187 | falcon_dev_21 | wrong_answer | 0 | value_mismatch (pred 3 行 vs 标准答案 3 行) |
| 188 | falcon_dev_19 | ok | 1 | multiset_perm |
| 189 | falcon_dev_21 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 4 行) |
| 191 | falcon_dev_21 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 40 行) |
| 192 | falcon_dev_7 | wrong_answer | 0 | value_mismatch (pred 100 行 vs 标准答案 368 行) |
| 190 | falcon_dev_21 | ok | 1 | multiset |
| 193 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 20 行 vs 标准答案 19 行) |
| 194 | falcon_dev_21 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 2 行) |
| 196 | falcon_dev_17 | ok | 1 | multiset |
| 195 | falcon_dev_4 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 1 行) |
| 197 | falcon_dev_9 | wrong_answer | 0 | value_mismatch (pred 223 行 vs 标准答案 223 行) |
| 199 | falcon_dev_24 | ok | 1 | multiset_perm |
| 200 | falcon_dev_15 | wrong_answer | 0 | value_mismatch (pred 3 行 vs 标准答案 3 行) |
| 201 | falcon_dev_26 | need_more_info | 0 | 系统判定信息不足: ["球员级别的射正数字段或 shotResult 中代表射正的具体取值"] |
| 198 | falcon_dev_19 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 26 行) |
| 202 | falcon_dev_19 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 1 行) |
| 203 | falcon_dev_21 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 36 行) |
| 204 | falcon_dev_17 | ok | 1 | multiset |
| 205 | falcon_dev_26 | need_more_info | 0 | 系统判定信息不足: ["球员与球队的关联关系（如 football_appearances 缺少 teamID，无法确定球员属于哪支球队）", "“场均进球”和“助攻效率”的具体计算口径（如场均进球是总场均还是主场场均，助攻效率是每90分钟 |
| 206 | falcon_dev_18 | ok | 1 | multiset_perm |
| 208 | falcon_dev_24 | wrong_answer | 0 | value_mismatch (pred 3 行 vs 标准答案 3 行) |
| 207 | falcon_dev_15 | wrong_answer | 0 | value_mismatch (pred 2 行 vs 标准答案 2 行) |
| 210 | falcon_dev_8 | wrong_answer | 0 | value_mismatch (pred 10 行 vs 标准答案 10 行) |
| 211 | falcon_dev_21 | ok | 1 | multiset_perm |
| 212 | falcon_dev_4 | ok | 1 | multiset_perm |
| 213 | falcon_dev_19 | need_more_info | 0 | 系统判定信息不足: ["啤酒消费量对应的年份字段或1990年啤酒消费量数据所在表", "alcohol_drinks 表中与年份、地区、收入组关联的字段"] |
| 209 | falcon_dev_14 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 1 行) |
| 214 | falcon_dev_24 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 30 行) |
| 217 | falcon_dev_15 | need_more_info | 0 | 系统判定信息不足: ["分组维度：按 Customer_Segment 还是 Customer_Vintage_Group 分组", "信用额度使用率的计算口径：已用额度如何获取（是否用交易金额汇总、是否考虑还款、时间范围等）", "若基于 |
| 216 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 3 行 vs 标准答案 18 行) |
| 215 | falcon_dev_20 | exec_error | 0 | SQL 执行失败: (pymysql.err.ProgrammingError) (1064, "You have an error in your SQL syntax; check the manual that corresponds |
| 218 | falcon_dev_5 | wrong_answer | 0 | value_mismatch (pred 33 行 vs 标准答案 34 行) |
| 221 | falcon_dev_15 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 1 行) |
| 220 | falcon_dev_21 | wrong_answer | 0 | value_mismatch (pred 63 行 vs 标准答案 21 行) |
| 219 | falcon_dev_26 | need_more_info | 0 | 系统判定信息不足: ["球员个人犯规次数数据"] |
| 224 | falcon_dev_16 | ok | 1 | multiset_perm |
| 223 | falcon_dev_17 | ok | 1 | multiset_perm |
| 225 | falcon_dev_21 | ok | 1 | multiset |
| 226 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 11 行 vs 标准答案 12 行) |
| 222 | falcon_dev_26 | error | 0 | HTTPError: 500 Server Error: Internal Server Error for url: http://localhost:8888/api/conversation |
| 227 | falcon_dev_17 | ok | 1 | multiset |
| 228 | falcon_dev_16 | wrong_answer | 0 | value_mismatch (pred 5 行 vs 标准答案 5 行) |
| 230 | falcon_dev_24 | need_more_info | 0 | 系统判定信息不足: ["“当月”具体指哪个时间范围（如注册当月、订单发生月份、当前月份等）", "“平均值”的计算基准（如所有客户、2024年新注册客户、按月份分组等）", "是计算客户在当月的订单总金额还是单笔订单金额", "输出“客户详 |
| 229 | falcon_dev_19 | ok | 1 | multiset_perm |
| 231 | falcon_dev_9 | wrong_answer | 0 | value_mismatch (pred 211 行 vs 标准答案 214 行) |
| 232 | falcon_dev_21 | wrong_answer | 0 | value_mismatch (pred 127 行 vs 标准答案 127 行) |
| 233 | falcon_dev_21 | ok | 1 | multiset |
| 235 | falcon_dev_21 | wrong_answer | 0 | value_mismatch (pred 4 行 vs 标准答案 4 行) |
| 234 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 7 行 vs 标准答案 3 行) |
| 237 | falcon_dev_26 | need_more_info | 0 | 系统判定信息不足: ["球员所属球队的标识（如 football_appearances 表中的 teamID 或球员-球队关联表）"] |
| 236 | falcon_dev_15 | wrong_answer | 0 | value_mismatch (pred 3 行 vs 标准答案 3 行) |
| 238 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 16 行 vs 标准答案 16 行) |
| 241 | falcon_dev_21 | wrong_answer | 0 | value_mismatch (pred 4 行 vs 标准答案 4 行) |
| 240 | falcon_dev_21 | wrong_answer | 0 | value_mismatch (pred 12 行 vs 标准答案 12 行) |
| 239 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 4 行 vs 标准答案 4 行) |
| 242 | falcon_dev_18 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 1 行) |
| 244 | falcon_dev_17 | ok | 1 | ordered |
| 243 | falcon_dev_15 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 1 行) |
| 245 | falcon_dev_21 | ok | 1 | multiset_perm |
| 246 | falcon_dev_21 | wrong_answer | 0 | value_mismatch (pred 3 行 vs 标准答案 3 行) |
| 247 | falcon_dev_5 | wrong_answer | 0 | value_mismatch (pred 49 行 vs 标准答案 48 行) |
| 249 | falcon_dev_9 | ok | 1 | ordered |
| 248 | falcon_dev_4 | wrong_answer | 0 | value_mismatch (pred 83 行 vs 标准答案 5 行) |
| 250 | falcon_dev_26 | need_more_info | 0 | 系统判定信息不足: ["球员与球队的关联关系（如 football_appearances 表中缺少 teamID，无法确定球员属于哪支球队）", "时间范围（赛季）未指定，可能影响主队胜率计算"] |
| 252 | falcon_dev_15 | wrong_answer | 0 | value_mismatch (pred 3 行 vs 标准答案 3 行) |
| 251 | falcon_dev_28 | ok | 1 | multiset_perm |
| 253 | falcon_dev_4 | wrong_answer | 0 | value_mismatch (pred 50 行 vs 标准答案 50 行) |
| 255 | falcon_dev_20 | ok | 1 | multiset_perm |
| 254 | falcon_dev_15 | ok | 1 | multiset_perm |
| 256 | falcon_dev_7 | wrong_answer | 0 | value_mismatch (pred 10 行 vs 标准答案 10 行) |
| 257 | falcon_dev_14 | need_more_info | 0 | 系统判定信息不足: ["销售排名的计算依据（如按销量、销售额、日期等）", "排名的范围（如店铺内所有产品、所有店铺内该产品、全局等）", "是否基于最新销售日期当天的数据还是历史累计数据"] |
| 259 | falcon_dev_20 | need_more_info | 0 | 系统判定信息不足: ["折扣码对应的折扣金额或折扣比例", "实际支付金额的计算规则（Fare 是否为折后金额）"] |
| 258 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 1 行) |
| 260 | falcon_dev_19 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 1 行) |
| 261 | falcon_dev_21 | need_more_info | 0 | 系统判定信息不足: ["“商品总库存量”具体指什么：是订单中的商品数量（e_orders.Quantity）还是产品表中的库存量（e_products.StockQuantity）？", "若指库存量，如何按订单状态分组？需要明确关联逻辑（ |
| 262 | falcon_dev_24 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 316 行) |
| 263 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 8 行 vs 标准答案 9 行) |
| 264 | falcon_dev_26 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 1 行) |
| 265 | falcon_dev_8 | wrong_answer | 0 | value_mismatch (pred 10 行 vs 标准答案 10 行) |
| 266 | falcon_dev_20 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 2 行) |
| 268 | falcon_dev_14 | ok | 1 | multiset_perm |
| 269 | falcon_dev_16 | ok | 1 | multiset_perm |
| 267 | falcon_dev_26 | wrong_answer | 0 | value_mismatch (pred 5 行 vs 标准答案 7 行) |
| 271 | falcon_dev_16 | wrong_answer | 0 | value_mismatch (pred 10 行 vs 标准答案 10 行) |
| 272 | falcon_dev_21 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 5 行) |
| 274 | falcon_dev_18 | need_more_info | 0 | 系统判定信息不足: ["高人均GDP的具体标准（如人均GDP大于某个数值，或排名前N）"] |
| 273 | falcon_dev_18 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 1 行) |
| 270 | falcon_dev_28 | error | 0 | HTTPError: 500 Server Error: Internal Server Error for url: http://localhost:8888/api/conversation |
| 275 | falcon_dev_5 | ok | 1 | ordered |
| 276 | falcon_dev_20 | ok | 1 | multiset_perm |
| 277 | falcon_dev_19 | wrong_answer | 0 | value_mismatch (pred 168 行 vs 标准答案 167 行) |
| 278 | falcon_dev_17 | wrong_answer | 0 | value_mismatch (pred 9 行 vs 标准答案 9 行) |
| 279 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 5 行 vs 标准答案 5 行) |
| 280 | falcon_dev_7 | exec_error | 0 | SQL 执行失败: (pymysql.err.ProgrammingError) (1064, "You have an error in your SQL syntax; check the manual that corresponds |
| 281 | falcon_dev_8 | ok | 1 | multiset |
| 283 | falcon_dev_14 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 1 行) |
| 284 | falcon_dev_17 | wrong_answer | 0 | value_mismatch (pred 8 行 vs 标准答案 3 行) |
| 285 | falcon_dev_24 | wrong_answer | 0 | value_mismatch (pred 44 行 vs 标准答案 44 行) |
| 286 | falcon_dev_8 | need_more_info | 0 | 系统判定信息不足: ["营收字段或可用于计算营收的精确数据（如精确安装量、价格数值）", "营收的计算口径（如总营收 = 价格 × 安装量）"] |
| 288 | falcon_dev_9 | wrong_answer | 0 | value_mismatch (pred 41 行 vs 标准答案 41 行) |
| 287 | falcon_dev_16 | ok | 1 | multiset |
| 282 | falcon_dev_26 | exec_error | 0 | SQL 执行失败: QueuePool limit of size 1 overflow 2 reached, connection timed out, timeout 30.00 (Background on this error at |
| 289 | falcon_dev_24 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 1 行) |
| 290 | falcon_dev_21 | ok | 1 | multiset |
| 292 | falcon_dev_20 | wrong_answer | 0 | value_mismatch (pred 15 行 vs 标准答案 15 行) |
| 291 | falcon_dev_7 | wrong_answer | 0 | value_mismatch (pred 12 行 vs 标准答案 60 行) |
| 293 | falcon_dev_14 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 1 行) |
| 294 | falcon_dev_14 | need_more_info | 0 | 系统判定信息不足: ["库存周转率的具体计算公式（如销售成本/平均库存，还是销售数量/库存量）", "平均库存的计算方式及所需的时间点或时间段库存数据（toy_inventory缺少日期字段）", "'开业三年后'的具体时间范围（是开业满三 |
| 296 | falcon_dev_16 | need_more_info | 0 | 系统判定信息不足: ["学生所在城市的字段（如 City）或从 Address 中提取城市的方法"] |
| 297 | falcon_dev_5 | wrong_answer | 0 | value_mismatch (pred 3 行 vs 标准答案 3 行) |
| 295 | falcon_dev_5 | wrong_answer | 0 | value_mismatch (pred 636 行 vs 标准答案 636 行) |
| 298 | falcon_dev_5 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 2 行) |
| 299 | falcon_dev_14 | wrong_answer | 0 | value_mismatch (pred 1 行 vs 标准答案 1 行) |
| 300 | falcon_dev_26 | exec_error | 0 | SQL 执行失败: QueuePool limit of size 1 overflow 2 reached, connection timed out, timeout 30.00 (Background on this error at |
| 301 | falcon_dev_28 | ok | 1 | multiset_perm |
| 302 | falcon_dev_18 | wrong_answer | 0 | value_mismatch (pred 5 行 vs 标准答案 3 行) |
| 303 | falcon_dev_14 | ok | 1 | multiset_perm |
| 304 | falcon_dev_15 | wrong_answer | 0 | value_mismatch (pred 19 行 vs 标准答案 19 行) |
| 305 | falcon_dev_28 | need_more_info | 0 | 系统判定信息不足: ["等待天数的具体计算方式（如 delivery_date - shipment_date 或 order_date - shipment_date 或当前日期 - shipment_date）", "最近一次发货的粒度 |
| 306 | falcon_dev_4 | wrong_answer | 0 | empty_mismatch (pred 0 行 vs 标准答案 10 行) |
| 307 | falcon_dev_17 | need_more_info | 0 | 系统判定信息不足: ["电子产品类目对应的 product_category_name 具体值（如 'eletronicos' 等）"] |
| 308 | falcon_dev_18 | wrong_answer | 0 | value_mismatch (pred 3 行 vs 标准答案 24 行) |
