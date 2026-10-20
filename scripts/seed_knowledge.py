# -*- coding: UTF-8 -*-
"""知识库补充种子脚本 — 幂等，可重复执行

定位：把「读 docs + 采实况」沉淀出来的领域知识一次性写入 knowledge_items，
      与 API 创建路径保持一致（create + record_version + 权限规则自校验）。
      不替代知识库管理页的日常维护；页面上改坏了可用版本恢复，本脚本只增不改。

知识来源（均有事实依据，非脑补）：
  - docs/01-系统使用文档.md §4/§7         知识类型用法与管理员最佳实践
  - docs/06-NL2SQL设计与实现.md            注入链路与降级策略
  - docs/archive/知识库改造实施方案.md    global/pin/版本化机制与六层映射
  - docs/测试报告/Falcon知识库优化对比_20261017.html
                                          枚举值必须逐字符照抄实采值、结果形态规范
  - scripts/sample_enum_values.py 实采   DM 库 PERIODS/SCENARIO/VERSION 等原样值
  - db 元数据 + 既有 4 条知识            表结构、科目编码、EETotal/PJTotal 约定

用法：
    .venv\\Scripts\\python.exe scripts\\seed_knowledge.py --dry-run   # 只看会写什么
    .venv\\Scripts\\python.exe scripts\\seed_knowledge.py             # 执行（默认 admin）
    .venv\\Scripts\\python.exe scripts\\seed_knowledge.py --admin-id 1

安全约束：
    - 幂等：同名（title）条目已存在即跳过；别名 / payload.related_tables 缺失时补写，
      绝不覆盖线上 content 与页面已填过的关联表
    - global/pinned 仅允许 admin 用户创建；pin 总数受 MAX_PINNED_GLOBAL=20 约束
    - 全程走 ORM + 版本快照，与 knowledge_router 创建路径同构
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.logger import logger  # noqa: E402
from crud.base import session_scope  # noqa: E402
from crud.knowledge import MAX_PINNED_GLOBAL, knowledge_crud  # noqa: E402
from models.knowledge import KnowledgeItem  # noqa: E402
from models.schema import DbSchema, DbTableRelation  # noqa: E402
from models.user import User  # noqa: E402

# ── 知识条目（scope_schema_id 在运行时按库名解析，见 _resolve_schema_ids） ──

# ── 知识条目声明的关联表（写入 payload.related_tables） ──
# 用途：向量召回按列名/描述语义排序，「费用合计/EETotal/AA0003」这类业务问法
# 排不进 top-K（DM 事实表列名是通用英文、无采样值）；recall_knowledge 命中
# entity_map/选表口径等条目时，按 payload.related_tables 把事实表扩进上下文，
# 避免判断步因"表缺失"反复误拦截（2026-10-19 conv8 连续 5 轮拦截事故）。
DM_FACT_TABLES = [
    'DM_KEY_ACTUAL_INDICATOR_DATA_METRIC',
    'DM_KEY_ACTUAL_INDICATOR_DATA',
    'DM_KEY_BUDGET_INDICATOR_DATA_METRIC',
    'DM_KEY_BUDGET_INDICATOR_DATA',
]

KNOWLEDGE_ENTRIES = [
    {
        'title': '枚举值必须逐字符照抄实采值',
        'type': 'convention', 'scope': None, 'visibility': 'global', 'pinned': 1,
        'aliases': ['枚举', '取值', '实采值', '编码', 'WHERE'],
        'content': (
            'WHERE/ON 条件中的枚举值必须使用知识库 value_domain 条目或维表给出的实采原样值，'
            '逐字符照抄（含大小写、前后空格），禁止按常识推测、禁止把编码写成中文名'
            '（如把 \'Diamond\' 写成 \'钻石\'）。\n'
            '查不到实采值时，先查对应维表取 DISTINCT，禁止把猜测值写进 SQL。\n'
            '示例（DM 库）：期间 PERIODS=\'01\'~\'12\'/\'Q1\'~\'Q4\'/\'YearTotal\'；'
            '场景 SCENARIO=\'AnnualBudget\'；版本 VERSION=\'Report\'；币种 CURRENCY=\'CNY\'。'
        ),
    },
    {
        'title': '结果形态与排序规范',
        'type': 'convention', 'scope': None, 'visibility': 'global', 'pinned': 1,
        'aliases': ['排序', '排名', 'TOP', '占比', '比例', '并列', '零值', '结果形态'],
        'content': (
            '- 汇总查询一行一个维度对象：GROUP BY 出现几个维度就输出几列，'
            '禁止把多个指标拼成一个字符串列。\n'
            '- 占比/比例类指标必须写明分母口径（哪张表、什么过滤条件），分母独立计算，禁止估算。\n'
            '- ORDER BY 必须带确定性次级排序键（如编码/主键）；只按指标排序时并列行顺序不稳定，'
            '重复提问结果可能不一致。\n'
            '- 无匹配数据时正常返回 0 行，禁止 COALESCE 臆造兜底值；'
            '"含零值"的名单类查询才用 LEFT JOIN + COALESCE(cnt, 0)。\n'
            '- 金额单位默认为元（CNY），SQL 内不做单位换算，除非用户明确要求。'
        ),
    },
    {
        'title': 'DM 事实表选择：实际数/预算数 × 明细/指标卡',
        'type': 'note', 'scope': 'DM', 'visibility': 'global', 'pinned': 0,
        'aliases': ['实际数', '预算数', '指标卡', '管理报表', '管报', 'DM_KEY',
                    'ACTUAL_VALUE', '事实表'],
        'related_tables': DM_FACT_TABLES,
        'content': (
            'DM 库四张事实表选表规则：\n'
            '1. 实际数首选 DM_KEY_ACTUAL_INDICATOR_DATA_METRIC（指标卡结果表）：'
            '主键 YEARS+PERIODS+ACCOUNT+ENTITY+PROJECT_LINE，金额字段 ACTUAL_VALUE，'
            '无 SCENARIO/VERSION/CURRENCY/PHASE 列。\n'
            '2. 实际数全维度明细 DM_KEY_ACTUAL_INDICATOR_DATA：额外含 PHASE/VERSION/父子ID，'
            '金额字段同为 ACTUAL_VALUE。\n'
            '3. 预算数 DM_KEY_BUDGET_INDICATOR_DATA_METRIC（指标卡）/ '
            'DM_KEY_BUDGET_INDICATOR_DATA（明细，另含 CURRENCY/BUDGETCENTER/MISC/SPARE1~3）：'
            '金额字段是 DATA，不是 ACTUAL_VALUE。\n'
            '4. 预算表必须同时指定 SCENARIO 与 VERSION（默认 AnnualBudget/Report），'
            '否则同一指标混合多个场景多个版本。\n'
            '5. 指标卡结果表科目域只含合计级与费用明细级（实采 24 个，如 AA0001 收入合计、'
            'AA0003 费用合计）；其他明细科目（共 267 个）必须用 *_INDICATOR_DATA 明细表。\n'
            '6. 全年用 PERIODS=\'YearTotal\' 一行直取；按月度汇总用 PERIODS IN (\'01\'~\'12\')；'
            '切勿把 \'YearTotal\' 与月度行放进同一个 SUM（会翻倍）。'
        ),
    },
    {
        'title': 'DM 期间/年度/场景/版本实采值域',
        'type': 'value_domain', 'scope': 'DM', 'visibility': 'global', 'pinned': 0,
        'aliases': ['PERIODS', 'QUARTERS', 'SCENARIO', 'VERSION', 'YEARS', 'PHASE',
                    'CURRENCY', '期间', '年度', '季度', '场景', '版本', '月份'],
        'content': (
            '以下为 2026-10-19 对 DM 库实采的原样值，查询条件必须使用这些值：\n'
            '- PERIODS（四张事实表一致）：\'01\'~\'12\'、\'Q1\'~\'Q4\'、\'YearTotal\'\n'
            '- QUARTERS（仅指标卡结果表有）：\'Q1\'~\'Q4\'；月/年行为 NULL，按季度汇总注意空值\n'
            '- YEARS（整数）：实际数 2024~2026；预算数 2016~2026（明细表实采）\n'
            '- SCENARIO（仅预算表有）：\'Actual\'、\'AnnualBudget\'、\'Q1Fcst\'、\'Q2Fcst\'、'
            '\'Q3Fcst\'、\'Q4Fcst\'\n'
            '- VERSION（仅预算表有）：\'Final\'、\'Report\'、\'V01\'、\'V03\'、\'V10\'\n'
            '- CURRENCY（仅预算明细表有）：\'CNY\'\n'
            '- PHASE（仅明细表有）：\'PH00\'、\'PHTotal\' 及 \'PH1100\'~\'PH2600\' 阶段编码'
        ),
    },
    {
        'title': '维表使用说明（ODS 维度表 / EPMDEV 层级视图）',
        'type': 'note', 'scope': None, 'visibility': 'global', 'pinned': 0,
        'aliases': ['维表', 'DIM_BUDGET_HYPLN', 'BI_CYHP', '层级', '父子',
                    'OBJECT_CODE', '维度表'],
        'content': (
            '- ODS.DIM_BUDGET_HYPLN_ACCOUNT/ENTITY/PROJECT/PERIOD/SCENARIO/VERSION/YEARS/PHASE：'
            'OBJECT_CODE=编码、OBJECT_NAME=名称、PARENT_ID=父节点。事实表（DM_KEY_*）已冗余 '
            '*_NAME 列，仅在需要按名称模糊查、遍历父子层级、取全量维度清单时才 JOIN 维表。\n'
            '- EPMDEV.BI_CYHP_ALL_*_V（科目/部门/产品线/期间/场景/版本/年度视图）：'
            '带 LEVEL、IS_FATHER、ACCOUNT_PATH 的层级维表，查层级用这套。'
            'EPMDEV 是独立数据源（Oracle，另一台服务器），不能与 DM/ODS 跨库 JOIN，只能单独查询。\n'
            '- 事实表与维表按 OBJECT_CODE 等值连接（已在「表关系」登记，生成 SQL 时优先使用）。'
        ),
    },
    {
        'title': '示例：各部门全年实际收入',
        'type': 'sample_qa', 'scope': 'DM', 'visibility': 'global', 'pinned': 0,
        'aliases': ['各部门', '部门收入', '实际收入', '全年', '收入'],
        'content': (
            '问题：2025年全年各部门实际收入是多少？\n'
            '正确写法：\n'
            "SELECT ENTITY, ENTITY_NAME, SUM(ACTUAL_VALUE) AS actual_revenue\n"
            'FROM DM_KEY_ACTUAL_INDICATOR_DATA_METRIC\n'
            "WHERE YEARS = '2025' AND PERIODS = 'YearTotal' AND ACCOUNT = 'AA0001'\n"
            "  AND ENTITY <> 'EETotal' AND PROJECT_LINE = 'PJTotal'\n"
            'GROUP BY ENTITY, ENTITY_NAME\n'
            'ORDER BY actual_revenue DESC, ENTITY\n'
            "要点：部门取明细须排除合计节点 'EETotal'；产品线不指定用合计节点 'PJTotal'；"
            "全年用 'YearTotal'；收入科目编码 'AA0001'。"
        ),
    },
    {
        'title': '示例：全年费用预算与实际对比',
        'type': 'sample_qa', 'scope': 'DM', 'visibility': 'global', 'pinned': 0,
        'aliases': ['预算对比', '预实对比', '费用', '预算执行', '差异'],
        'content': (
            '问题：2025年全年各科目费用预算与实际对比？\n'
            '正确写法（实际子查询 LEFT JOIN 预算子查询，按 ACCOUNT 关联）：\n'
            'SELECT a.ACCOUNT, a.ACCOUNT_NAME, b.budget_amt, a.actual_amt,\n'
            '       a.actual_amt - b.budget_amt AS diff\n'
            'FROM (SELECT ACCOUNT, ACCOUNT_NAME, SUM(ACTUAL_VALUE) AS actual_amt\n'
            '      FROM DM_KEY_ACTUAL_INDICATOR_DATA_METRIC\n'
            "      WHERE YEARS='2025' AND PERIODS='YearTotal' AND ENTITY='EETotal' "
            "AND PROJECT_LINE='PJTotal'\n"
            '      GROUP BY ACCOUNT, ACCOUNT_NAME) a\n'
            'LEFT JOIN (SELECT ACCOUNT, SUM(DATA) AS budget_amt\n'
            '      FROM DM_KEY_BUDGET_INDICATOR_DATA_METRIC\n'
            "      WHERE YEARS='2025' AND PERIODS='YearTotal' AND SCENARIO='AnnualBudget' "
            "AND VERSION='Report'\n"
            "        AND ENTITY='EETotal' AND PROJECT_LINE='PJTotal'\n"
            '      GROUP BY ACCOUNT) b ON a.ACCOUNT = b.ACCOUNT\n'
            'ORDER BY diff\n'
            '要点：实际表金额字段 ACTUAL_VALUE、预算表金额字段 DATA；'
            "预算子查询必须带 SCENARIO='AnnualBudget' AND VERSION='Report'；"
            '两表科目域不同（实际 24 个、预算 15 个），以实际侧为准 LEFT JOIN，缺预算侧为 NULL。'
        ),
    },
    {
        'title': '口语词到科目编码/维度字段映射（DM）',
        'type': 'entity_map', 'scope': 'DM', 'visibility': 'global', 'pinned': 0,
        'aliases': ['收入', '营收', '成本', '费用', '工资', '薪酬', '部门', '产品线',
                    '项目', '全年', '预算', '实际', '利润'],
        'related_tables': DM_FACT_TABLES,
        'content': (
            '- 收入/营收/营业额 → ACCOUNT=\'AA0001\'（收入合计）\n'
            '- 成本/变动成本 → ACCOUNT=\'AA0002\'（变动成本合计）\n'
            '- 费用/总费用 → ACCOUNT=\'AA0003\'（费用合计）\n'
            '- 薪酬/工资/福利 → \'AA000301\'；广告/市场费 → \'AA000302\'；'
            '内容/版权费 → \'AA000303\'；通讯/带宽费 → \'AA000304\'；差旅/应酬 → \'AA000305\'\n'
            '- 所得税 → \'AA0008\'；利息收入/费用 → \'AA0009\'；其他收入/费用 → \'AA0010\'\n'
            '- 部门/组织/公司主体 → ENTITY（全公司合计用 \'EETotal\'，取各部门明细排除 \'EETotal\'）\n'
            '- 产品线/项目/产品 → PROJECT_LINE（全部合计用 \'PJTotal\'）\n'
            '- 全年/年度累计 → PERIODS=\'YearTotal\'；单月 → \'01\'~\'12\'；季度 → \'Q1\'~\'Q4\'\n'
            '- 预算/预算数 → 预算表 + SCENARIO=\'AnnualBudget\' + VERSION=\'Report\'；'
            '实际/实际数 → 实际数表\n'
            '- 利润口径见知识库「指标--利润」；以上编码属指标卡结果表域，'
            '明细科目用 *_INDICATOR_DATA 明细表。'
        ),
    },
    {
        'title': 'DM 库数据质量与清洗陷阱',
        'type': 'quality', 'scope': 'DM', 'visibility': 'global', 'pinned': 0,
        'aliases': ['数据质量', '陷阱', '注意事项', 'Actual场景', '空值'],
        'content': (
            '- 预算表（DM_KEY_BUDGET_*）里混有 SCENARIO=\'Actual\' 的行：查预算必须显式指定 '
            'SCENARIO（默认 \'AnnualBudget\'），不能因"表名是 BUDGET"就不过滤。\n'
            '- QUARTERS 列仅季度行有值，月/年行为 NULL：按季度汇总注意空值分支。\n'
            '- 实际明细表 VERSION 列为空（NULL/空串），只有预算表有版本概念。\n'
            '- DM_KEY_ACTUAL_INDICATOR_DATA_METRIC 没有 SCENARIO/VERSION/CURRENCY/PHASE 列，'
            'SQL 里引用这些列会直接报错。\n'
            '- *_NAME 与编码列一一对应，GROUP BY 时编码与名称一起分组，不要只按名称分组（重名风险）。'
        ),
    },
    {
        'title': 'MySQL 8 语法陷阱：LIMIT 子查询与窗口函数写法',
        'type': 'convention', 'scope': None, 'visibility': 'global', 'pinned': 1,
        'aliases': ['MySQL', 'LIMIT', '子查询', '窗口函数', 'TopN', '语法'],
        'content': (
            '1. MySQL 8 不支持 IN (SELECT ... ORDER BY ... LIMIT n) 形式的 LIMIT 子查询'
            '（报错 1235 LIMIT & IN/ALL/ANY/SOME）。TopN 集合要先包一层再引用：'
            'JOIN (SELECT * FROM (SELECT ... LIMIT 10) t) top10 ON ... 或用 CTE。\n'
            '2. 窗口函数的 PARTITION/ORDER 列必须是确定存在的列；'
            '同一查询里既要窗口排名又要 GROUP BY 时，先在子查询/CTE 里聚合再开窗。'
        ),
    },
    {
        'title': '排名与 TopN 口径（RANK/DENSE_RANK/ROW_NUMBER 选用）',
        'type': 'convention', 'scope': None, 'visibility': 'global', 'pinned': 0,
        'aliases': ['排名', '排行', 'TopN', '前三', '前十', '前N', '最高', '最多', '并列', 'RANK'],
        'content': (
            '1. "每类最高/最多/占比最高"类 Top-1 极值用 DENSE_RANK() OVER '
            '(PARTITION BY ... ORDER BY ... DESC)=1，保留并列的全部行，不要 ROW_NUMBER 或 LIMIT 1；\n'
            '2. "前 N 名/排行榜"用 RANK()（并列同名次）+ WHERE rank<=N 过滤，不要 LIMIT N；\n'
            '3. "组内按值逐行排名"（每行都带名次）默认 ROW_NUMBER()；排名列放 SELECT 最后一列；\n'
            '4. 整数列求平均写 AVG(CAST(col AS DOUBLE))，避免整型 AVG 的定点小数表示差异；\n'
            '5. 不添加用户未要求的过滤条件，不硬编码题面未列举的枚举集合——'
            '用 GROUP BY+HAVING 让数据驱动；确需按枚举过滤时用实采原样值。'
        ),
    },
]

# ── 表关系（与既有 3 条同模式：事实表维度列 = DIM_BUDGET_HYPLN_*.OBJECT_CODE） ──
# left_schema=DM(id=1)，right_schema=ODS(id=2)，同库服务器跨库 JOIN
RELATION_SPECS = [
    # (left_table, left_column, right_table, right_column)
    ('DM_KEY_ACTUAL_INDICATOR_DATA', 'ACCOUNT', 'DIM_BUDGET_HYPLN_ACCOUNT', 'OBJECT_CODE'),
    ('DM_KEY_ACTUAL_INDICATOR_DATA', 'ENTITY', 'DIM_BUDGET_HYPLN_ENTITY', 'OBJECT_CODE'),
    ('DM_KEY_ACTUAL_INDICATOR_DATA', 'PROJECT_LINE', 'DIM_BUDGET_HYPLN_PROJECT', 'OBJECT_CODE'),
    ('DM_KEY_BUDGET_INDICATOR_DATA', 'ACCOUNT', 'DIM_BUDGET_HYPLN_ACCOUNT', 'OBJECT_CODE'),
    ('DM_KEY_BUDGET_INDICATOR_DATA', 'ENTITY', 'DIM_BUDGET_HYPLN_ENTITY', 'OBJECT_CODE'),
    # 注意：预算明细表的产品线列名是 PROJECT（无 _LINE 后缀）
    ('DM_KEY_BUDGET_INDICATOR_DATA', 'PROJECT', 'DIM_BUDGET_HYPLN_PROJECT', 'OBJECT_CODE'),
    ('DM_KEY_BUDGET_INDICATOR_DATA_METRIC', 'ACCOUNT', 'DIM_BUDGET_HYPLN_ACCOUNT', 'OBJECT_CODE'),
    ('DM_KEY_BUDGET_INDICATOR_DATA_METRIC', 'ENTITY', 'DIM_BUDGET_HYPLN_ENTITY', 'OBJECT_CODE'),
    ('DM_KEY_BUDGET_INDICATOR_DATA_METRIC', 'PROJECT_LINE', 'DIM_BUDGET_HYPLN_PROJECT', 'OBJECT_CODE'),
]


def _resolve_schema_ids() -> dict:
    """库名 → schema id（DM=1/ODS=2/EPMDEV=3 的解析不写死，按名查）"""
    with session_scope() as db:
        return {s.name: s.id for s in db.query(DbSchema).all()}


def _check_admin(admin_id: int) -> bool:
    with session_scope() as db:
        user = db.query(User).filter(User.id == admin_id).first()
        return bool(user and user.role == 'admin' and user.is_active)


def seed_knowledge(admin_id: int, dry_run: bool) -> tuple:
    """写入知识条目，返回 (created, skipped) 标题列表

    幂等语义：同名条目已存在即跳过；仅当**别名**或 **payload.related_tables**
    与脚本定义不一致时补一次同步（内容以页面维护为准，脚本绝不覆盖用户改过的
    content；related_tables 仅填补缺失，不覆盖页面已填过的关联表）。
    """
    schema_ids = _resolve_schema_ids()
    created, skipped = [], []
    pinned_count = knowledge_crud.count_global_pinned()
    for spec in KNOWLEDGE_ENTRIES:
        title = spec['title']
        want_aliases = json.dumps(spec['aliases'], ensure_ascii=False)
        want_related = spec.get('related_tables') or []
        with session_scope() as db:
            exists = db.query(KnowledgeItem).filter(
                KnowledgeItem.title == title).first()
            if exists and exists.aliases != want_aliases and not dry_run:
                exists.aliases = want_aliases
                db.commit()
                knowledge_crud.record_version(exists.id, 'update', admin_id)
                logger.info(f"知识条目别名已同步: id={exists.id} {title}")
            if exists and want_related and not dry_run:
                # payload.related_tables 补写：仅填补缺失（"只增不改"），
                # 覆盖页面改动过的 payload 中的关联表
                try:
                    cur_payload = json.loads(exists.payload or '{}')
                except (json.JSONDecodeError, TypeError):
                    cur_payload = {}
                if not cur_payload.get('related_tables'):
                    cur_payload['related_tables'] = want_related
                    exists.payload = json.dumps(cur_payload, ensure_ascii=False)
                    db.commit()
                    knowledge_crud.record_version(exists.id, 'update', admin_id)
                    logger.info(f"知识条目关联表已补写: id={exists.id} {title}")
        if exists:
            skipped.append(title)
            continue
        if spec['visibility'] == 'global' and spec['pinned'] and pinned_count >= MAX_PINNED_GLOBAL:
            logger.warning(f"常驻条目已达上限 {MAX_PINNED_GLOBAL}，跳过 pin: {title}")
            spec = {**spec, 'pinned': 0}
        scope_id = schema_ids.get(spec['scope']) if spec['scope'] else None
        if spec['scope'] and scope_id is None:
            logger.warning(f"作用域库不存在，按全局处理: {title} (scope={spec['scope']})")
        if dry_run:
            created.append(f"{title} [dry-run]")
            continue
        item = knowledge_crud.create(
            user_id=admin_id,
            title=title,
            content=spec['content'],
            knowledge_type=spec['type'],
            aliases=json.dumps(spec['aliases'], ensure_ascii=False),
            payload=json.dumps({'related_tables': spec.get('related_tables', [])},
                               ensure_ascii=False),
            scope_schema_id=scope_id,
            visibility=spec['visibility'],
            is_pinned=spec['pinned'],
        )
        knowledge_crud.record_version(item.id, 'create', admin_id)
        if spec['pinned']:
            pinned_count += 1
        created.append(title)
        logger.info(f"知识条目已创建: id={item.id} {title} "
                    f"(type={spec['type']}, scope={spec['scope']}, pinned={spec['pinned']})")
    return created, skipped


def seed_relations(admin_id: int, dry_run: bool) -> tuple:
    """补齐表关系，返回 (created, skipped) 描述列表"""
    schema_ids = _resolve_schema_ids()
    left_sid, right_sid = schema_ids.get('DM'), schema_ids.get('ODS')
    if left_sid is None or right_sid is None:
        raise SystemExit('[ERR] DM/ODS 库不存在，无法登记关系')
    created, skipped = [], []
    for left_table, left_col, right_table, right_col in RELATION_SPECS:
        key = f'{left_table}.{left_col} = {right_table}.{right_col}'
        with session_scope() as db:
            exists = db.query(DbTableRelation).filter(
                DbTableRelation.left_schema_id == left_sid,
                DbTableRelation.left_table == left_table,
                DbTableRelation.left_column == left_col,
                DbTableRelation.right_schema_id == right_sid,
                DbTableRelation.right_table == right_table,
                DbTableRelation.right_column == right_col,
            ).first()
        if exists:
            skipped.append(key)
            continue
        if dry_run:
            created.append(f'{key} [dry-run]')
            continue
        with session_scope() as db:
            db.add(DbTableRelation(
                schema_id=left_sid,
                left_schema_id=left_sid, right_schema_id=right_sid,
                left_table=left_table, left_column=left_col,
                right_table=right_table, right_column=right_col,
                join_type='LEFT JOIN', relation_type='1:N',
                description='', created_by=admin_id,
            ))
        created.append(key)
        logger.info(f"表关系已登记: {key}")
    return created, skipped


def main():
    parser = argparse.ArgumentParser(description='知识库补充种子（幂等，可重复执行）')
    parser.add_argument('--admin-id', type=int, default=1, help='管理员用户 id（默认 1）')
    parser.add_argument('--dry-run', action='store_true', help='只打印将写入的内容，不落库')
    args = parser.parse_args()

    if not args.dry_run and not _check_admin(args.admin_id):
        raise SystemExit(f'[ERR] user_id={args.admin_id} 不是有效管理员，'
                         f'global/pinned 条目拒绝创建')

    k_created, k_skipped = seed_knowledge(args.admin_id, args.dry_run)
    r_created, r_skipped = seed_relations(args.admin_id, args.dry_run)

    print(f"\n知识条目：新增 {len(k_created)}，已存在跳过 {len(k_skipped)}")
    for t in k_created:
        print(f"  + {t}")
    for t in k_skipped:
        print(f"  = {t}（已存在，跳过）")
    print(f"\n表关系：新增 {len(r_created)}，已存在跳过 {len(r_skipped)}")
    for t in r_created:
        print(f"  + {t}")
    for t in r_skipped:
        print(f"  = {t}（已存在，跳过）")
    if args.dry_run:
        print("\n[dry-run] 未写入任何数据。")


if __name__ == '__main__':
    main()
