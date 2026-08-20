# Overview: QueryForge 全面代码分析与修复

## 完成内容
对 QueryForge 项目（约 80 个 Python 文件的 FastAPI NL→SQL 平台）完成了两个阶段的工作：
1. **全面代码分析** — 覆盖 Bug、性能、逻辑性、耦合性、模块化、安全性六大维度
2. **系统性修复实现** — 基于分析报告对 16 个文件进行修复，48 项验证全部通过

## 第一阶段：分析

### 方法
- 主理人（软件工坊）直接审阅 30+ 核心源文件
- 组建 GStack 团队，分派产品评审员、安全官、调查员三位专家并行分析
- 全部三位专家已完成，综合汇编为统一报告

### 关键发现（60 项）
- 🔴 严重 4 项：缺失 import 致启动崩溃、SyncEngine 分离对象持久化失败、Pickle RCE、SSRF+同步阻塞
- 🟠 重要 18 项：异常信息泄露、N+1 查询×3、Session 管理散乱、路由间耦合、SELECT * 只处理首表等
- 🟡 建议 23 项：SQL 网关默认放行、行级过滤注入、Prompt 注入、时区不一致、多轮对话缺审计等
- 🟢 良好 15 项：SQL 权限网关 AST 解析、DCL 单例+Lock、JWT pwd_ts 失效、Fernet 加密等

### 评分总览
| 维度 | 评分 | 说明 |
|------|------|------|
| 架构 | 6.5/10 | 分层正确但 Session 散乱、反向依赖 |
| 安全 | 7.5/10 | 上轮 4/10→7.5/10，Critical 已清零 |
| 性能 | 6/10 | N+1、同步阻塞、缓存无界 |
| 健壮性 | 7/10 | 安全设计 9/10，代码正确性 6/10 |

## 第二阶段：修复实现（16 文件，48 项验证全通过）

### P0 安全修复（3 项）
| # | 文件 | 修复内容 |
|---|------|----------|
| 1 | `core/retrieval/vector_store.py` | Pickle RCE 消除：np.savez + json.dump 替换 pickle；旧 .pkl 自动迁移 |
| 2 | `core/llm/client.py` | SSRF 防护：_validate_llm_url() + 共享 requests.Session 连接池 |
| 3 | `main.py` | 全局异常处理：生产环境返回通用消息，DEBUG 返回详情 |

### 数据库切换（3 项）
| # | 文件 | 修复内容 |
|---|------|----------|
| 4 | `app/config.py` | DATABASE_URL / DB_IS_SQLITE / DB_DIALECT 环境变量切换 |
| 5 | `db/database.py` | 统一 _create_engine()；PRAGMA 仅 SQLite；_ensure_column_generic() 通用迁移 |
| 6 | `services/sql/executor.py` + `download_model.py` | 替换硬编码 SQLite 引擎为共享引擎 |

### P1 性能与逻辑修复（5 项）
| # | 文件 | 修复内容 |
|---|------|----------|
| 7 | `services/sql/gateway.py` | 移除 break；dialect 参数化；_access_map 默认 NONE（默认拒绝） |
| 8 | `app/routers/chat_to_sql_router.py` | 无界 dict → TTLCache(maxsize=1000, ttl=300) |
| 9 | `scheduler/jobs/usage_stats.py` | 时区修复 + N+1 消除（batch .in_() 预加载） |
| 10 | `services/sync/engine.py` | N+1 消除（batch 列加载）+ 反向依赖消除 |
| 11 | `app/routers/system_router.py` | download_embedding 权限 CurrentUser → AdminUser |

### 模块化与耦合度（1 项）
| # | 文件 | 修复内容 |
|---|------|----------|
| 12 | `services/vector/__init__.py` + `service.py` | 新建向量服务模块，从 router 层移至 service 层 |

### 依赖更新
- `requirements.txt`：新增 `httpx>=0.27.0`、`cachetools>=5.3.0`

## 数据库切换使用方式

**默认（SQLite，适合个人/小型项目）**：无需任何配置，零开箱即用。

**切换到外部数据库（适合团队/企业）**：设置环境变量即可：
```bash
# MySQL
export DATABASE_URL="mysql+pymysql://user:password@host:3306/queryforge"

# PostgreSQL
export DATABASE_URL="postgresql+psycopg2://user:password@host:5432/queryforge"

# 可选：遥测库单独配置
export TELEMETRY_DATABASE_URL="mysql+pymysql://user:password@host:3306/queryforge_telemetry"

# 可选：连接池大小
export DB_POOL_SIZE=20
```

## 产出文件
- `deliverables/gstack/code-analysis-queryforge-2026-08-20.md` — 完整分析报告（60 条发现 + 15 条行动清单）
- `overview.md` — 本概览文档
