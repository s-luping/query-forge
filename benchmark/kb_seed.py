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
            "1. 只输出问题要求的列，不加任何未要求的列；差值/均值/占比类问题只返回单值列。\n"
            "2. \"占比/比例/份额\"的分母是全量数据的合计（先算全表总额再除），"
            "不是筛选后子集的合计；除非问题明确说\"占筛选结果的比\"。\n"
            "3. \"每位/每个/各 X 的…\"必须包含计数为 0 的 X：主表 LEFT JOIN 聚合子查询 + "
            "COALESCE(cnt, 0)，不要只对明细表 GROUP BY。\n"
            "4. 排名/TopN 的 ORDER BY 必须带次级排序列（如 id）保证并列时结果稳定；"
            "问题含\"前十/最高/排名\"时用窗口函数或 ORDER BY+LIMIT；"
            "问题要求输出\"排名\"列时，SELECT 必须包含 RANK()/ROW_NUMBER() 算出的排名列，"
            "不能只输出数值列。\n"
            "5. 问题出现\"每月/各/分别\"才 GROUP BY；聚合结果不要把明细列混进 SELECT。"
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

    # 已有条目（按 title 去重，记录 id/content 以便内容变更时原地更新）
    existing = {}
    r = s.get(f"{args.base_url}/api/knowledge?limit=100", timeout=30)
    for it in r.json().get("items", []):
        existing[it.get("title")] = {"id": it.get("id"), "content": it.get("content")}

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
            if info.get("content") == content:
                print(f"  跳过（已存在且内容一致）: {title}")
                skipped += 1
                return
            r = s.put(f"{args.base_url}/api/knowledge/{info['id']}", json=body, timeout=30)
            if r.status_code != 200:
                print(f"  [FAIL-UPDATE] {title}: {r.status_code} {r.text[:120]}")
                return
            created += 1
            print(f"  更新: {title} (id={info['id']})")
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
