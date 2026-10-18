# -*- coding: utf-8 -*-
"""从 Falcon 评测归因结论生成知识库条目并播种（benchmark/kb_seed.py）。

三类条目（对应六层方案的 L1/L2/L3/L5）：
  1. 全局常驻（visibility=global + is_pinned=1）—— L5 输出规范 + L3 清洗总则，
     注入所有对话 prompt；
  2. 分库枚举值（visibility=global + scope_schema_id=<库>，knowledge_type=value_domain）
     —— 枚举值全部从 MySQL 实采，消灭"钻石 vs Diamond"式枚举幻觉；
  3. 分库口径（calculation）—— 评分口径/销售额口径/占比分母等归因高频错因。

幂等：按 title 去重（同 title 且内容一致跳过；内容有变更时 PUT 原地更新）。
用法（管理员凭证走环境变量或默认 admin/REDACTED）：
  .venv\\Scripts\\python.exe benchmark\\kb_seed.py [--base-url http://localhost:8888]
"""
import argparse
import json
import os
import sys

import pymysql
import requests

# ── 1. 全局常驻条目（L5 输出规范 + L3 清洗总则） ──────────────────
GLOBAL_PINNED = [
    {
        "title": "输出规范：结果形态与口径（人人遵守）",
        "knowledge_type": "convention",
        "content": (
            "1. 最小列集：只输出题目要求的标识列+数值列，不加任何未要求的列"
            "（姓名、排名、中间计算列、原始状态列都不要附加）；实体标识默认输出 ID 列"
            "（store_id/product_id/customer_id/gameid 等），仅当题目明确要\"名称/店名\"才输出名称列；"
            "多列按\"维度ID→度量值→排名\"顺序，排名列一律放最后一列；价格/金额输出清洗后的数值，"
            "不输出带 $ 的原始字符串。\n"
            "2. \"占比/比例/份额\"的分母是全量数据的合计（先算全表总额再除），"
            "不是筛选后子集的合计；比率类输出原始小数比值，不乘 100，除非题面明确要百分比。\n"
            "3. 聚合类默认 INNER JOIN——只输出有匹配记录的实体（有订单的客户/有销量的商品）；"
            "仅当题面明确\"包含没有 X 的/每位 X 都要（含 0）\"或计数类要求补零时，才主表 LEFT JOIN "
            "聚合子查询 + COALESCE(cnt, 0)。\n"
            "4. 并列与排名：①\"每类最高/最多/占比最高\"类 Top-1 极值用 DENSE_RANK() OVER "
            "(PARTITION BY ... ORDER BY ... DESC)=1，保留并列的全部行，不要 ROW_NUMBER 或 LIMIT 1；"
            "②\"前 N 名/排行榜\"用 RANK()（并列同名次）+ WHERE rank<=N 过滤，不要 LIMIT N；"
            "③\"组内按值逐行排名\"（每行都带名次）默认 ROW_NUMBER()；排名列放 SELECT 最后一列；"
            "窗口 ORDER BY 不要加 id/name 等 tie-break 列。\n"
            "5. 不要自行添加题目未要求的 IS NOT NULL / TRIM(col)<>'' 过滤，也不要硬编码题面未列举的"
            "枚举集合——用 GROUP BY+HAVING 让数据驱动。\n"
            "6. 问题出现\"每月/各/分别\"才 GROUP BY；聚合结果不要把明细列混进 SELECT；"
            "整数列求平均写 AVG(CAST(col AS DOUBLE))，避免整型 AVG 的定点小数表示差异。"
        ),
    },
    {
        "title": "数据清洗总则：字符串数字必须先清洗再计算",
        "knowledge_type": "quality",
        "content": (
            "基准数据集中大量数值以字符串存储，计算前必须清洗：\n"
            "1. 金额类常见 $ 前缀：CAST(REPLACE(TRIM(col), '$', '') AS DECIMAL(10,2))\n"
            "2. 数量类常见千分位逗号与 + 后缀（如 installs \"1,000+\"）："
            "CAST(REPLACE(REPLACE(TRIM(col), ',', ''), '+', '') AS UNSIGNED)\n"
            "3. 直接 CAST 带非数字前缀的字符串会得到 0 或报错，必须先 REPLACE。\n"
            "4. NULL 与空字符串参与聚合前用 WHERE 过滤或 COALESCE 处理。"
        ),
    },
    {
        "title": "日期过滤规范：先确认字符串日期格式再比较",
        "knowledge_type": "convention",
        "content": (
            "基准库日期多为字符串且格式不统一，写 WHERE 前必须先确认格式：\n"
            "1. 'yyyy-MM-dd'（如 toy_sales.date）：可用 substr(date,1,4)='2018'、"
            "LIKE '2018%' 或 BETWEEN '2018-01-01' AND '2018-12-31'。\n"
            "2. 'MM/dd/yyyy'（如 city_ride_rides_data.date）：LIKE '2024-11%' 或 "
            "substr(date,1,4) 一行都匹配不到！必须重排："
            "substr(date,7,4)||'-'||substr(date,1,2)||'-'||substr(date,4,2) "
            "转成 'yyyy-MM-dd' 后再 BETWEEN。\n"
            "3. 不确定格式时先抽查几行样本（SELECT DISTINCT ... LIMIT 5）再写条件。"
        ),
    },
    {
        "title": "MySQL 8 语法陷阱：LIMIT 子查询与窗口函数写法",
        "knowledge_type": "convention",
        "content": (
            "1. MySQL 8 不支持 IN (SELECT ... ORDER BY ... LIMIT n) 形式的 LIMIT 子查询"
            "（报错 1235 LIMIT & IN/ALL/ANY/SOME）。TopN 集合要先包一层再引用："
            "JOIN (SELECT * FROM (SELECT ... LIMIT 10) t) top10 ON ... 或用 CTE。\n"
            "2. 窗口函数的 PARTITION/ORDER 列必须是确定存在的列；"
            "同一查询里既要窗口排名又要 GROUP BY 时，先在子查询/CTE 里聚合再开窗。"
        ),
    },
]

# ── 2. 分库枚举值（value_domain，global + scope；值从 MySQL 实采） ──
# (schema, title, aliases, [(table.column), ...])
SCOPED_ENUMS = [
    ("falcon_dev_28", "在线商店枚举值（承运商/支付/配送状态）",
     ["承运商", "配送", "支付", "交易状态", "shipment", "carrier", "payment"],
     ["online_shop_shipments.carrier", "online_shop_shipments.shipment_status",
      "online_shop_shipments.shipment_status_detail", "online_shop_payment.payment_method",
      "online_shop_payment.transaction_status", "online_shop_products.category"]),
    ("falcon_dev_15", "信用卡客户枚举值（客户分组/等级/交易分段）",
     ["钻石", "钻石客户", "客户分组", "客户等级", "交易分段", "VG1",
      "customer_segment", "vintage", "diamond"],
     ["credit_card_customer_base.Customer_Segment",
      "credit_card_customer_base.Customer_Vintage_Group",
      "credit_card_card_base.Card_Family",
      "credit_card_transaction_base.Transaction_Segment",
      "credit_card_transaction_base.Transaction_Segment"]),
    ("falcon_dev_20", "网约车司机枚举值（城市/活跃状态/优惠码）",
     ["活跃司机", "司机", "城市", "优惠码", "active", "city", "promo"],
     ["city_ride_drivers_data.Active_Status", "city_ride_drivers_data.City",
      "city_ride_rides_data.City", "city_ride_rides_data.Promo_Code"]),
    ("falcon_dev_14", "玩具店枚举值（门店位置/商品类目）",
     ["门店", "商业区", "商品类目", "玩具", "store", "category", "location"],
     ["toy_stores.Store_Location", "toy_products.Product_Category"]),
    ("falcon_dev_8", "Google Play 枚举值与清洗（类型/分级/下载量/价格）",
     ["应用", "付费", "免费", "下载量", "价格", "分级", "installs", "price"],
     ["googleplaystore.type", "googleplaystore.content_rating"]),
    ("falcon_dev_4", "保理业务枚举值（争议状态/账单方式）",
     ["争议", "发票", "账单", "逾期", "disputed", "paperless"],
     ["finance_factoring_data.Disputed", "finance_factoring_data.PaperlessBill"]),
    ("falcon_dev_19", "WHO 健康数据枚举值（地区/性别/收入组/指标）",
     ["欧洲", "地区", "性别", "收入", "预期寿命", "region", "sex"],
     ["alcohol_life_expectancy_verbose.RegionDisplay",
      "alcohol_life_expectancy_verbose.SexDisplay",
      "alcohol_life_expectancy_verbose.WorldBankIncomeGroupDisplay",
      "alcohol_life_expectancy_verbose.GhoDisplay"]),
    ("falcon_dev_26", "足球数据枚举值（联赛/射门结果/主客场/赛季）",
     ["联赛", "射门", "进球", "赛季", "主队", "league", "season", "shot"],
     ["football_leagues.name", "football_shots.shotResult",
      "football_teamstats.location", "football_teamstats.result"]),
    ("falcon_dev_21", "电商订单枚举值（订单状态/类目/城市）",
     ["订单状态", "配送", "退货", "商品类目", "客户", "卡萨布兰卡", "order"],
     ["e_orders.OrderStatus", "e_products.Category", "e_customers.City"]),
    ("falcon_dev_24", "闪购电商枚举值（反馈/配送/支付/客群）",
     ["反馈", "配送", "支付", "客群", "情绪", "sentiment", "delivery"],
     ["blinkit_customer_feedback.sentiment", "blinkit_customer_feedback.feedback_category",
      "blinkit_customers.customer_segment", "blinkit_orders.delivery_status",
      "blinkit_orders.payment_method"]),
    ("falcon_dev_16", "学校成绩枚举值（科目/考试日期）",
     ["科目", "老师", "学生", "成绩", "subject", "exam"],
     ["school_subjects.SubjectName", "school_marks.ExamDate"]),
    ("falcon_dev_7", "游戏销量枚举值（类型/平台）",
     ["游戏", "类型", "销量", "genre", "platform"],
     ["vgsales.genre", "vgsales.Platform"]),
]

# ── 3. 分库口径条目（calculation，global + scope） ────────────────
SCOPED_CALIBERS = [
    ("falcon_dev_20", "网约车「司机评分」口径（高频错因）",
     ["评分", "平均评分", "司机评分", "rating"],
     "「司机的平均评分」指司机档案 city_ride_drivers_data.average_rating 字段的值"
     "（静态档案评分），不是行程表 city_ride_rides_data.Rating 的平均值。"
     "涉及\"平均行程次数及其平均评分\"类问题：行程次数从 rides 表计数，"
     "评分直接取 drivers.average_rating，两者分别聚合后按城市求平均。"),
    ("falcon_dev_14", "玩具店「销售额」口径与占比分母（高频错因）",
     ["销售额", "占比", "比例", "销售"],
     "销售额 = Units × Product_Price（Product_Price 含 $ 前缀必须清洗后相乘）。"
     "「占全部区域/总销售额的比例」分母 = 所有区域销售额总和；"
     "筛选类目时比例分母仍是全量总额。"),
    ("falcon_dev_20", "网约车「行程日期」格式（高频错因）",
     ["日期", "11月", "2024年", "月份", "接单", "date"],
     "city_ride_rides_data.date 为 'MM/dd/yyyy' 字符串（如 '11/11/2024'），"
     "用 LIKE '2024-11%' 或 substr(date,1,4) 过滤会得到 0 行。"
     "过滤某年某月必须写 substr(date,7,4)='2024' AND substr(date,1,2)='11'，"
     "或重组为 'yyyy-MM-dd' 后 BETWEEN '2024-11-01' AND '2024-11-30'。"),
    ("falcon_dev_14", "玩具店「销售额排名」输出与日期格式（高频错因）",
     ["销售额", "排名", "销售"],
     "「销售额排名」类问题必须输出排名列本身："
     "RANK() OVER (ORDER BY total_sales DESC) AS `排名`，不能只输出店铺名和销售额两列。"
     "销售额必须先清洗价格再相乘：CAST(REPLACE(TRIM(p.product_price), '$', '') AS DECIMAL(10,2)) * "
     "CAST(units AS SIGNED)，直接 CAST '$39.99' 会得到 0。"
     "toy_sales.date 为 'yyyy-MM-dd'，按年过滤用 substr(date,1,4)='2018' 或 LIKE '2018%'。"),
    ("falcon_dev_4", "保理业务「发票金额比例」分母口径（高频错因）",
     ["比例", "占比", "发票金额", "逾期"],
     "\"发票金额的比例\"分母 = 全表 InvoiceAmount 总和（不区分是否争议）；"
     "平均逾期天数 = AVG(CAST(DaysLate AS SIGNED))，按 customerID 分组。"),
    ("falcon_dev_5", "独角兽库口径与输出规范（高频错因）",
     ["估值", "独角兽", "排名", "行业", "加入", "valuation", "unicorn"],
     "1. valuation 形如 '$140'（单位十亿美元，无 B/M 后缀），清洗 = "
     "CAST(REPLACE(valuation, '$', '') AS DECIMAL(12,2))；结果列必须输出清洗后的数值，"
     "绝不能把 '$140' 原始字符串列直接 SELECT 输出。\n"
     "2. date_joined 已是 'yyyy-MM-dd' 格式：按年过滤用 YEAR(date_joined)=2020 或 "
     "substr(date_joined,1,4)='2020'，禁止 STR_TO_DATE/strftime 二次解析（会得 NULL 空结果）。\n"
     "3. 「排名/最新加入/最高估值」类题输出列 = 题目明确要求的列；「排名前五有哪些」输出"
     "(industry, company, 估值数值)，勿输出名次列；题目明确要「排名」列时才输出名次列。\n"
     "4. 「前 N 且高于行业平均」复合题：先用 join 行业平均子查询过滤 > 平均，"
     "再对过滤后的集合 ROW_NUMBER() 排名取前 N；先排名后过滤结果会错。\n"
     "5. 每国/每行业「估值最高/最新加入的一家」= ROW_NUMBER() OVER (PARTITION BY ... "
     "ORDER BY date_joined DESC)=1，不要 join MAX 写法（并列会多行）；"
     "不要加 date_joined IS NOT NULL 等额外过滤（NULL 行也占一个名额，标准口径含 NULL 行）。\n"
     "6. 「城市/行业内按估值从高到低的排名」的排名列用 DENSE_RANK()（并列估值同名次），"
     "窗口 ORDER BY 不加 company 等 tie-break 列。\n"
     "7. industry/company 存在大小写变体（如 'Artificial intelligence' 与 'Artificial Intelligence'"
     " 是标准口径下的两个不同分组），按其分组/排名/去重时须加 COLLATE utf8mb4_bin "
     "（如 PARTITION BY industry COLLATE utf8mb4_bin、GROUP BY company COLLATE utf8mb4_bin）。\n"
     "8. 占比/比例输出原始小数比值（num/total），不要乘 100 变百分比，除非题目明确要百分比；"
     "「公司数量」用 COUNT(DISTINCT company)。"),
    ("falcon_dev_18", "世界经济库口径与单位（高频错因）",
     ["旅游", "失业", "生活成本", "腐败", "收入", "国家", "tourism", "unemployment"],
     "1. 五张表（cost_of_living / tourism / unemployment / corruption / richest_countries）"
     "的数值列在库中已是数值类型（double/bigint），比较、排序、聚合直接用列值，无需 CAST/REPLACE。\n"
     "2. 单位：percentage_of_gdp 存的是百分数值（35.96 表示 35.96%）；"
     "receipts_in_billions 单位十亿美元（5 亿美元 = 0.5）；receipts_per_tourist 单位美元；"
     "annual_income 年度人均收入（美元）；corruption_index 范围 0~100。\n"
     "3. 「全球平均」= 全表 AVG，不加任何过滤。\n"
     "4. 多条件国家题：各表分别过滤后按 country INNER JOIN，输出列只保留题目要求的列。\n"
     "5. 「列出 X 和 Y 的排名情况」= 输出 X、Y 原值列 + 各自的排名列"
     "（ROW_NUMBER() OVER (ORDER BY X DESC) 等），共 4~5 列，不要只输出排名列。\n"
     "6. 「旅游收入前十的国家」先 ORDER BY receipts_in_billions DESC LIMIT 10 取 Top10，"
     "再对这 10 国做后续条件统计（TopN 子查询需包一层再 JOIN，MySQL 不支持 LIMIT IN 子查询）。"),
    ("falcon_dev_9", "互联网用户库口径（高频错因）",
     ["互联网", "蜂窝", "宽带", "订阅", "用户数", "cellular", "broadband"],
     "1. 数值列（cellular_subscription / broadband_subscription / no_of_internet_users / "
     "internet_users）已是数值类型，直接比较聚合，无需 CAST。\n"
     "2. 「国家」计数/去重以 code 为准（COUNT(DISTINCT code)）；entity 含 'World'"
     "（code=OWID_WRL）与地区聚合行，按题意保留，不要排除。\n"
     "3. 「排名 + 平均值」类题逐行输出：值列 + ROW_NUMBER() OVER (ORDER BY 值 DESC) 排名列 + "
     "AVG(值) OVER (PARTITION BY entity) 平均列，不要 GROUP BY 合并成每国一行。\n"
     "4. 输出列只保留题目要求的列（国家、值、排名），不加 code/year 等未要求列。"),
    ("falcon_dev_17", "电商库口径（高频错因）",
     ["订单", "运费", "分期", "体积", "重量", "销量", "shipping", "installments"],
     "1. 「体积重量」（计费体积重）= product_length_cm × product_width_cm × "
     "product_height_cm / 6000（航空体积重标准，单位 kg），按订单 SUM 后再求平均；"
     "不要把重量与体积分成两列输出。\n"
     "2. 「分期付款」= payment_installments >= 2（值域 1~5）。\n"
     "3. 「超过平均运价」= 高于全表平均 AVG(shipping_charges)（全局单值），"
     "不是分类内/订单内平均。\n"
     "4. 「每个产品类别的销量排名」= 类别级聚合：过滤高运价订单后按类别 GROUP BY，"
     "总销售额 = SUM(price)，输出 类别 + 总销售额 + RANK() OVER (ORDER BY 总销售额 DESC) "
     "共 3 列；不要输出 product_id 级明细，也不要按 sales_count 排名。"),
    ("falcon_dev_14", "玩具店口径补充（高频错因）",
     ["玩具销售额", "玩具", "门店", "店铺", "城市", "排名"],
     "1. 「玩具销售额排名/统计」类问题若点名\"玩具\"而非按类别分组：标准口径限 "
     "Product_Category = 'Toys'（本库含 Art & Crafts 等多品类），不要把所有品类都算进去。\n"
     "2. 「每个城市的店铺/各店铺的 X」按店铺级（store_id）分组输出，不要合并到城市级；"
     "输出列含题目要求的列。\n"
     "3. 「排名前 N 且 <X」复合条件：先按 <X 过滤，再对过滤后的集合排名取前 N。\n"
     "4. 金额/利润/销售额类统计只统计实际发生销售的店铺（销售表 INNER JOIN），"
     "不要 LEFT JOIN 给无销售店铺补 0 行；仅\"计数为 0 也要出现\"类问题才需要 LEFT JOIN 补零。"),
    ("falcon_dev_21", "电商订单口径（高频错因）",
     ["订单", "客户", "购买", "数量", "金额", "order"],
     "1. 「订单总金额/购买总数量」类条件按订单行级判定：先 WHERE quantity = 4 AND "
     "totalamount > 200 过滤订单行，再取客户 DISTINCT；不要按客户 SUM 聚合后判定"
     "（\"总数量为4件\"指单笔订单 4 件，不是客户累计）。\n"
     "2. 订单状态/类目/城市等 WHERE 值必须逐字符照抄知识条目给出的枚举值："
     "是 Canceled 不是 Cancelled，是 Shipped 不是\"已发货\"，类别是 Tools 不是\"工具箱\"。"),
    ("falcon_dev_20", "网约车评分与城市归属口径（高频错因）",
     ["评分", "司机", "城市", "行程", "促销", "优惠码", "promo"],
     "1. 行为条件中的\"平均评分高于X\"（如总距离>100 且平均评分>4.0）取该司机行程表 Rating 的 AVG，"
     "不是司机档案 Average_Rating；仅\"司机的平均评分\"静态口径才用 Average_Rating。\n"
     "2. \"X城市司机\"默认按司机档案 drivers.City 过滤；题面明确\"在该城市接单/有行程\"才按行程表 City。\n"
     "3. \"最近行程中使用过优惠码\"：先对每位司机求 MAX(转日期) 得最近日期，只汇总该日期当天的优惠码行程，"
     "不是汇总全部行程。\n"
     "4. \"实际支付金额\"= Fare × 折扣系数：SAVE20→0.8、DISCOUNT10→0.9、WELCOME5→0.95（题面未给出但为固定口径）；"
     "Promo_Code 实际值仅这三个+NULL，IS NOT NULL 与 IN 三值等价。\n"
     "5. \"评分排前三的行程\"按司机分组各取前三（RANK PARTITION BY driver_id ≤3）再按司机汇总；"
     "对比基线（城市平均距离/评分）与主过滤同范围（活跃司机内、促销订单内），不要用全量做基线。"),
    ("falcon_dev_20", "网约车输出与粒度口径（高频错因）",
     ["哪些司机", "输出", "标记", "排名", "日均收入", "里程"],
     "1. \"哪些司机\"类只输出 driver_id（至多附一个统计值列），不要附加 Name/经验年限/排名列；"
     "布尔标记输出 'Yes'/'No'，不要'是'/'否'；列序标识列在前。\n"
     "2. 城市级汇总题按 city GROUP BY 输出城市行（如各城市总里程/均费/达标司机日均收入的均值），"
     "不按司机逐行展开；日均收入=SUM(Fare)/COUNT(DISTINCT Date)。\n"
     "3. \"平均服务里程\"按行程粒度 AVG(distance_km)（单次行程均值），不是司机总里程均值，"
     "也不要把无行程司机按 0 计入。\n"
     "4. Date 列为 'MM/dd/yyyy' 字符串，过滤前必须重排为 yyyy-MM-dd 或分别取 substr。\n"
     "5. \"里程费最高\"类排序键按 distance_km 降序，不是按 Fare。"),
    ("falcon_dev_14", "玩具店输出列对齐与指标口径（高频错因）",
     ["店铺", "产品", "利润", "利润率", "平均售价", "增长"],
     "1. 店铺/产品默认输出 store_id/product_id（题面明确要\"店名\"才输出名称列）；"
     "列序：维度→度量→排名（排名列置尾，勿放首列）；利润率分布类输出×100 百分数且不四舍五入。\n"
     "2. 价格类指标（平均售价/品类均价）一律基于 toy_sales JOIN toy_products 的销售记录计算，"
     "禁止用 toy_inventory 库存价；JOIN 后直接 AVG 即按销售行重复计权（gold 口径如此），不要先按产品去重。\n"
     "3. \"玩具\"品类过滤仅用于求玩具的具体量值/排名（限 Product_Category='Toys'）；"
     "占比、超均值、总量阈值、增长识别等与全量对比的场景不加过滤（全品类）。\n"
     "4. \"销售情况\"类输出逐笔明细行（date/store_id/product_id/units/成本/品类均价），不聚合；"
     "增长识别输出 product_id+月份两列，不加增长额列。\n"
     "5. toy_sales 存在 product_id 不在产品表的孤儿行（33/30/24/23），INNER JOIN 会静默剔除，"
     "窗口排名在剔除前计算。\n"
     "6. \"库存高于平均水平\"的平均=AVG(Stock_On_Hand) 全库存明细行均值；"
     "\"销售总量≤N 的产品及店铺累计\"=按(店,产品)合计≤N 筛组合，店铺累计=该店入选组合之和，输出 ID+两个销量列。"),
    ("falcon_dev_26", "足球数据排名与关联口径（高频错因）",
     ["排名", "前", "球员", "联赛", "首发", "替补", "角球", "净胜球"],
     "1. 排名并列必须同名次：聚合值排名用 RANK()（如客队角球总和 26 组并列），\"前 N\"用 rank<=N 过滤，"
     "勿 ROW_NUMBER/LIMIT；\"X 数排名联赛前 10\"= 先按其余条件过滤，再按 leagueID 分区取 RANK<=10（每联赛各取前 10）。\n"
     "2. 聚合仅输出有记录实体：\"各球员累计X\"只 INNER 输出有出场记录的球员，勿 LEFT JOIN 全员补 0。\n"
     "3. 比赛类输出标识用 gameid，不输出日期列（题目明确要日期除外）；只输出最小列集。\n"
     "4. \"净胜球高于1\"按单场 homeGoals-awayGoals>1 逐场判定，不做主队场均。\n"
     "5. football_appearances.substituteIn：0=首发，非 0 为替补（值域杂），替补判定用 substituteIn<>0，勿用=1。\n"
     "6. 统计列（shotsOnTarget/corners/yellowCards）为整数字符串，求均值写 AVG(col*1.0) 转浮点；"
     "appearances JOIN games 无索引极慢，先过滤 season 再关联。"),
    ("falcon_dev_21", "电商口径补充：聚合范围与指标定义（高频错因）",
     ["客户", "库存", "分类", "平均", "最近", "一年", "销售金额"],
     "1. \"每位/各客户聚合\"仅 INNER 输出有匹配记录的客户（有已发货订单的才输出），勿 LEFT JOIN 全部客户补 0。\n"
     "2. \"低于平均\"按分组内均值比较（各分类自身均价），勿用全局均价。\n"
     "3. \"订单总数量\"=COUNT(orderid) 订单条数，不是 SUM(Quantity)；\"销售金额\"=数量×商品单价，"
     "占比按商品级输出（该商品销售额/其类别总额）。\n"
     "4. \"最近一年\"以库内 MAX(OrderDate) 回溯（本库为 2022-12-29），不用当前系统日期。\n"
     "5. \"哪种类别最多\"保留并列：RANK()=1 输出全部并列类别，勿 LIMIT 1。\n"
     "6. \"不同状态的商品总库存\"先对(orderstatus,productid)去重再汇总库存，勿按订单行重复累计。\n"
     "7. 标注类文案照知识条目：'是大额订单'/'否'；订单明细不额外 join 客户表输出姓名列。"),
    ("falcon_dev_24", "闪购数据口径（高频错因）",
     ["准时", "配送", "损坏", "保质期", "品牌", "品类"],
     "1. 排名并列用 RANK()：\"占比最高\"只输出 RANK=1 全部并列者（多为仅 1 单即 100% 的小样本），"
     "勿输出全员比率清单；平均保质期并列极多（365 天 142 个品牌），必须 RANK 并列且不额外输出排名列。\n"
     "2. delivery_status 枚举：'On Time'/'Slightly Delayed'/'Significantly Delayed'，"
     "orders 与 delivery_performance 两表等价（按 order_id 关联）；品类唯一值 'Dairy & Breakfast'，用等值匹配。\n"
     "3. 性能：本库无二级索引，orders×order_items×products 三表直接 join 必超时——"
     "先把 orders×order_items 按 product_id 聚合成小结果集（约 0.4s），再 join products 取品牌。\n"
     "4. \"超过平均值\"按注册月份分组求各月平均，仅统计有订单客户，勿用全体总平均。"),
    ("falcon_dev_28", "在线商店实体名与金额口径（高频错因）",
     ["产品", "类目", "电子", "键盘", "鼠标", "金额", "支付", "承运商", "等待"],
     "1. product_name/category 只存英文值（如 'Gaming Keyboard'/'Wireless Mouse'，"
     "category='Electronics'/'Accessories'/'Furniture'/'Home & Kitchen'）；"
     "题面中文实体（游戏键盘/无线鼠标/电子产品）必须先译成对应英文值再做 = 或 LIKE，"
     "用中文直接匹配命中 0 行。\n"
     "2. \"订单总金额/消费总额\"默认对 online_shop_payment.amount 求和，不用 orders.total_price；"
     "\"高于平台平均支付金额X倍\"作用于客户级聚合（客户总消费>5×AVG(全表 amount)），"
     "不是单笔比较（单笔 max/avg≈2.79，必空）。\n"
     "3. \"等待天数\"=DATEDIFF(delivery_date, shipment_date)（发货到送达），不是下单到发货。\n"
     "4. \"发货时效排名\"按承运商聚合：先算各承运商平均运输时长排名，同时输出三状态计数列，"
     "输出承运商级汇总行不输出订单明细；shipment_status 枚举 'Delivered'/'Shipped'/'Pending'。\n"
     "5. 多列结果按题面提及顺序输出（如\"客户全名及其订单号/交易状态\"列序=全名,状态,订单ID）；"
     "排名列题面未要求时不输出。"),
    ("falcon_dev_15", "信用卡口径与分组维度（高频错因）",
     ["使用率", "客户分组", "资历", "白金", "平均", "比值"],
     "1. \"使用率/占比\"输出原始比率 SUM(消费)/SUM(额度)，不乘 100；比值类只输出比值一列，"
     "不带 Transaction_ID 等附加列。\n"
     "2. \"客户分组/资历分组\"统一指 Customer_Vintage_Group（VG1/VG2/VG3），"
     "不是 Customer_Segment（'Diamond'/'Gold'/'Platinum'）。\n"
     "3. \"超过平均\"的比较基准取同范围子集内部平均（如白金卡客户中超过平均=白金卡交易自身 AVG）。\n"
     "4. 严禁硬编码题面未列举的枚举集合（SEG11~25、卡族、VG 列表等）过滤——GROUP BY+HAVING 数据驱动。\n"
     "5. Transaction_Date 实存 'YYYY-MM-DD' 格式，按字符串比较即可，勿按 'DD-Mon-YY' 解析（会全 NULL）。"),
    ("falcon_dev_8", "Google Play 数据质量口径（高频错因）",
     ["应用", "重复", "去重", "评分", "安卓", "更新", "前5%", "适配"],
     "1. 表内同一 app 有重复行（9196 行 vs 去重 9097 个）：应用计数用 COUNT(DISTINCT app)；"
     "Top-N（下载量前3/前10、每类最高价）先 GROUP BY app 去重再排序取前 N；输出 app 名单加 DISTINCT。\n"
     "2. rating 约 1367 行 NULL：任何分母/排名/平均先 WHERE rating IS NOT NULL AND rating<>''；"
     "content_rating 可能为 NULL，分组统计前剔除空值组。\n"
     "3. android_ver 有区间格式 '4.0.3 - 7.1.1'：判断\"适配X及以上\"含 '-' 的取后半段（上界）CAST 比较；"
     "'Varies with device' CAST 为 0 自然排除。\n"
     "4. last_updated 已是 'YYYY-MM-DD' ISO 格式，直接字符串比较/DATE()，勿按 '%M %d, %Y' 解析（得 NULL）；"
     "题面要求显示更新日期时须带出该列。"),
    ("falcon_dev_7", "游戏销量口径（高频错因）",
     ["游戏数量", "排名", "类型", "平台", "销售额"],
     "1. \"游戏数量\"一律 COUNT(DISTINCT name) 按游戏名去重（同名多平台行会重复计数）。\n"
     "2. vgsales 自带 rank 列（全球排名），\"销售额及排名\"直接 SELECT rank 输出，勿在子集内重算。\n"
     "3. \"各类型前五平台\"类输出明细行 (genre, platform, 合计, AVG(global_sales) 组内单游戏均值)，"
     "勿聚合成每类型一行；极值并列用 DENSE_RANK 全取，销售额加 >0 过滤排除零销售组。"),
    ("falcon_dev_16", "学校成绩输出口径（高频错因）",
     ["姓名", "学生", "老师", "前两名", "平均分", "人数"],
     "1. 姓名输出用 CONCAT 合并单列（教师 CONCAT(lastname,' ',firstname)），学生按 gold 附带成绩数值列与 studentid，"
     "输出列集对齐勿增删；平均分不四舍五入。\n"
     "2. \"人数排名\"并列用 RANK() 并列同号，勿 ROW_NUMBER。\n"
     "3. 整数列求均值写 AVG(CAST(col AS DOUBLE))，避免与标准答案浮点表示不一致。"),
    ("falcon_dev_4", "保理业务口径补充（高频错因）",
     ["季度", "逾期", "最后一次", "国家", "排名"],
     "1. \"季度末结算\"=结算月份 IN (3,6,9,12) 即可，不要求当日为季末最后一天；关联键=客户+年+月。\n"
     "2. \"最后一次逾期/最后一张\"按 DueDate 对该客户全部发票排序取最新（不预筛 DaysLate>0）再验金额。\n"
     "3. \"每个国家累计\"按 countrycode GROUP BY 汇总，仅输出 (countrycode, 累计额) 两列。\n"
     "4. 金额排名并列用 DENSE_RANK 并列同号；\"按逾期天数前五\"用 ROW_NUMBER OVER (ORDER BY dayslate DESC)<=5；"
     "列序 (invoicenumber, dayslate, invoiceamount, 排名)；均值用 AVG(CAST(col AS DOUBLE))。"),
    ("falcon_dev_19", "WHO 健康数据口径（高频错因）",
     ["地区", "高收入", "均值", "国家"],
     "1. \"高收入国家超地区均值\"：先筛 WorldBankIncomeGroupDisplay='High_income' AND 指定年份，"
     "地区均值仅在该高收入子集上计算（gold 不滤 Sex/Gho，重复行参与均值），输出国家去重列表。\n"
     "2. 与 verbose 表连接用 COLLATE utf8mb4_bin 精确比较，避免口音不敏感排序规则把 "
     "Cote d'Ivoire 与 Côte d'Ivoire 等变体误匹配（gold 为二进制精确匹配）。"),
    ("falcon_dev_17", "电商类目精确匹配（高频错因）",
     ["电子产品", "类目", "品类", "electronics"],
     "product_category_name 必须先按知识条目实采枚举精确匹配（电子产品实采值='electronics'）；"
     "禁止臆测拼写或 LIKE '%eletronic%' 等未实采的模糊匹配（不命中任何行导致空结果）。"),
]

MYSQL = dict(host="127.0.0.1", port=3306, user="root", password="REDACTED",
             charset="utf8mb4", autocommit=True)


def sample_enum_values(cur, schema, table_col, limit=15):
    """实采枚举值，返回去重后的值列表（字符串化，截断）"""
    t, c = table_col.split(".", 1)
    try:
        cur.execute(f"SELECT DISTINCT `{c}` FROM `{schema}`.`{t}` LIMIT {limit}")
        vals = []
        for row in cur.fetchall():
            v = "" if row[0] is None else str(row[0]).strip()
            if v and v not in vals:
                vals.append(v[:40])
        return vals
    except Exception as e:
        print(f"  [WARN] 采样 {schema}.{table_col} 失败: {e}")
        return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=os.environ.get("QF_BASE_URL", "http://localhost:8888"))
    ap.add_argument("--user", default=os.environ.get("QF_USER", "admin"))
    ap.add_argument("--password", default=os.environ.get("QF_PASSWORD", "REDACTED"))
    args = ap.parse_args()

    s = requests.Session()
    r = s.post(f"{args.base_url}/login",
               json={"username": args.user, "password": args.password}, timeout=30)
    r.raise_for_status()
    print("登录成功")

    # schema 名 → id
    r = s.get(f"{args.base_url}/api/schema/schemas", timeout=30)
    schema_ids = r.json().get("schema_ids", {})

    # 已有条目（按 title 去重，记录 id/content/visibility 以便变更时原地更新）
    existing = {}
    r = s.get(f"{args.base_url}/api/knowledge?limit=100", timeout=30)
    for it in r.json().get("items", []):
        existing[it.get("title")] = {"id": it.get("id"), "content": it.get("content"),
                                     "visibility": it.get("visibility")}

    created = skipped = 0

    def create_entry(title, knowledge_type, content, aliases, scope_name=None,
                     pinned=0):
        nonlocal created, skipped
        body = {
            "title": title, "knowledge_type": knowledge_type, "content": content,
            "aliases": aliases, "visibility": "global", "is_pinned": pinned,
            "scope_schema_id": schema_ids.get(scope_name) if scope_name else None,
        }
        if title in existing:
            info = existing[title]
            if info.get("content") == content and info.get("visibility") == "global":
                print(f"  跳过（已存在且内容/可见性一致）: {title}")
                skipped += 1
                return
            r = s.put(f"{args.base_url}/api/knowledge/{info['id']}", json=body, timeout=30)
            if r.status_code != 200:
                print(f"  [FAIL-UPDATE] {title}: {r.status_code} {r.text[:120]}")
                return
            created += 1
            why = "可见性恢复 global" if info.get("content") == content else "内容更新"
            print(f"  更新({why}): {title} (id={info['id']})")
            return
        r = s.post(f"{args.base_url}/api/knowledge", json=body, timeout=30)
        if r.status_code != 200:
            print(f"  [FAIL] {title}: {r.status_code} {r.text[:120]}")
            return
        created += 1
        print(f"  创建: {title} (scope={scope_name}, pinned={pinned})")

    print("== 全局常驻条目")
    for e in GLOBAL_PINNED:
        create_entry(e["title"], e["knowledge_type"], e["content"], [], None, pinned=1)

    my = pymysql.connect(**MYSQL)
    cur = my.cursor()
    print("== 分库枚举值条目（实采）")
    for schema, title, aliases, table_cols in SCOPED_ENUMS:
        lines = [f"以下为 {schema} 库真实取值（查询 WHERE 条件必须使用这些原样值，"
                 "不要自造中文或其它写法，字符串区分大小写按存储原样）："]
        seen_cols = set()
        for tc in table_cols:
            if tc in seen_cols:
                continue
            seen_cols.add(tc)
            vals = sample_enum_values(cur, schema, tc)
            if vals:
                lines.append(f"- {tc}: {json.dumps(vals, ensure_ascii=False)}")
        create_entry(title, "value_domain", "\n".join(lines), aliases, schema)
    print("== 分库口径条目")
    for schema, title, aliases, content in SCOPED_CALIBERS:
        create_entry(title, "calculation", content, aliases, schema)
    my.close()

    print(f"\n完成: 新建 {created} 条，跳过 {skipped} 条")


if __name__ == "__main__":
    main()
