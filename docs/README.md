# QueryForge 文档地图

> 更新：2026-10-20 · 本文件是 docs/ 的索引入口；测试报告统一在 `docs/测试报告/`（HTML，脚本直接写入该目录，勿改名）。

## 使用与运维（日常查阅）

| 文档 | 内容 |
|---|---|
| [01-系统使用文档.md](01-系统使用文档.md) | 功能操作手册：登录/对话/知识库/同步/权限/审计，FAQ |
| [02-部署运维手册.md](02-部署运维手册.md) | 安装部署、环境要求、启动自检、向量模型下载 |
| [03-资产总表.md](03-资产总表.md) | 接口/路由/表/页面/调度/审计事件清单（**ci_guard.py 功能性引用，路径勿改**） |
| [04-新数据源接入指南.md](04-新数据源接入指南.md) | 接入新库的单一完整指南：SOP（P0~P8）+ 准确率治理清单 + 核对单 + 新类型扩展专题 |

## 设计与方案（开发参考）

| 文档 | 内容 |
|---|---|
| [05-系统架构设计.md](05-系统架构设计.md) | 总体架构、技术栈、代码结构、三库分离、认证与权限、向量检索 |
| [06-NL2SQL设计与实现.md](06-NL2SQL设计与实现.md) | NL2SQL 链路逐阶段详解、结果可解释性、扫描修复清单、知识库注入链路 |
| [07-ChatSQL模块化与全链路留痕设计.md](07-ChatSQL模块化与全链路留痕设计.md) | P1 StepTrace 留痕 / P2 RecallScope 解耦 / P3 模块红线（多处代码 docstring 引用，路径勿改） |
| [08-NL2SQL基准测试方案.md](08-NL2SQL基准测试方案.md) | 基准选型（Falcon/BIRD/Spider/DuSQL）、指标、对接流程、基线记录 |
| [09-NL2SQL评测失败类型手册.md](09-NL2SQL评测失败类型手册.md) | 跑批失败归因标准：宽口径五层比对、错误类型 A/B/C 三类、优化预算分配原则 |

## 测试报告（docs/测试报告/，10 份）

| 报告 | 覆盖 |
|---|---|
| NL2SQL验证测试报告.pdf / NL2SQL经典场景测试报告.pdf | 第一轮（milk_tea_sales 7 场景）/ 第二轮（northwind+sakila 10 题）手工验证 |
| BIRD基准NL2SQL测试报告.html | BIRD dev 24 题多轮合并（turbo/glm53/双模型/小库直通优化），去重后终版 |
| Falcon抽样5题 / 抽样30题报告（_20261017） | Falcon 前两轮抽样，逐题归因 |
| Falcon小批优化对比_20261018 / _第5轮 | 比对器修复 + KB 迭代的小批验证 |
| Falcon知识库优化对比_20261017 | KB A/B 评测（35 题，+1.4pp）与枚举照抄结论 |
| Falcon全量迭代收敛报告_20261019 | Falcon 全量 309 题三轮收敛终版（35.8%→74.0%），含残余失败分类 |
| Spider累计140题报告_glm53_20261020 | Spider dev 140 题三轮累计（严格 80.0% / 宽口径 85.0%），20 库全覆盖 |

## 基准评测（benchmark/，与《08-NL2SQL基准测试方案》配套）

```
benchmark/
├── spider/      # Spider 全流程：spider_bench.py（import/select/setup/test，多线程+宽口径比对）
│                #   analyze_spider.py（统一重算分桶）+ make_spider_cumulative_report.py（报告）
├── falcon/      # Falcon：run_eval.py（评测，workers+fallback 链）/ analyze_falcon.py（归因分桶）
│                #   make_falcon_full_report.py / falcon_import.py / setup_sync.py / kb_seed.py / make_kb_ab_report.py
├── bird/        # BIRD：qf_bench_run.py（评测）/ bird_to_mysql.py / bird_select_and_ground.py
│                #   make_bird_report.py / recompute_match.py
├── questions/   # 题目主档：falcon/questions_falcon.jsonl(309) / bird/bird_selected_questions.json /
│                #   spider/spider_selected.json(140，唯一主档)
├── results/     # 原始评测数据，按数据集分子目录（falcon/ bird/ spider/）；
│                #   报告一律产出 docs/测试报告/，不放本目录
│                #   Falcon 终版：falcon.c7.final.enriched.jsonl + full309(.r2)/kb35 enriched；
│                #   BIRD：bird_eval_*.json 7 份（合并报告输入）；Spider：extra30/extra100 + cumulative analysis
└── data/        # 数据集原始包（gitignore：falcon / bird / spider）
```

维护约定：中间过程结果（重试轮/小批轮/smoke）跑完即删，只保留进入正式报告的最终数据；报告 HTML 一律归 `docs/测试报告/`；新增数据集评测脚本建同级子目录（如 `dusql/`）。

## 归档（docs/archive/，已实施完毕的方案）

| 文档 | 说明 |
|---|---|
| [知识库改造实施方案.md](archive/知识库改造实施方案.md) | KB 全局常驻/版本化/用户偏好改造方案——已全部落地，机制现记录于《NL2SQL设计与实现》与《系统使用文档》 |

## 维护约定

1. **测试报告**：跑批产出统一 `docs/测试报告/`（HTML 格式），生成脚本放 `benchmark/`；被新报告完全覆盖的旧报告及时删除（如 Falcon 旧全量报告、Spider 分批报告已收敛）。
2. **路径稳定性**：`资产总表.md`（ci_guard.py 读取）、`ChatSQL模块化与全链路留痕设计.md`（多处代码 docstring）、`测试报告/`（报告脚本输出路径）移动前先改引用。
3. **合并原则**：同一主题只留一份主文档（历史过程文档合并或进 archive）；文档内引用路径同步更新。
