# 向量索引构建详解

本文档描述 QueryForge 中向量索引的构建原理、流程和使用方法。

---

## 目录

1. [概述](#概述)
2. [架构设计](#架构设计)
3. [Embedding 模型](#embedding-模型)
4. [索引构建流程](#索引构建流程)
5. [SQL 生成流程中的检索环节](#sql-生成流程中的检索环节)
6. [触发方式](#触发方式)
7. [元数据持久化](#元数据持久化)
8. [存储结构](#存储结构)
9. [关键参数](#关键参数)
10. [降级策略](#降级策略)
11. [并发安全](#并发安全)
12. [API 参考](#api-参考)
13. [常见问题](#常见问题)

---

## 概述

QueryForge 使用**字段级向量索引 + 按表聚合**的 RAG（检索增强生成）方案来提升 SQL 生成质量：

```
用户问题 → 关键词提取 → 向量语义检索(top-K字段) → 按表聚合(获取完整表结构) → 构建Prompt → LLM生成SQL
```

核心思路：
- **检索阶段**：将用户自然语言问题编码为向量，在字段描述索引中搜索最相关的 top-K 个字段
- **聚合阶段**：收集这些字段所属的表（去重），获取这些表的**完整结构**作为 LLM 上下文

---

## 架构设计

### 组件关系

```
┌─────────────────────────────────────────────────────┐
│                   SQLPipeline / ChatSession          │
│  (流程编排器，协调全部步骤)                            │
├─────────────────────────────────────────────────────┤
│  step1: KeywordExtractor  ← jieba 分词 + TF 统计     │
│  step2: SchemaVectorStore ← 向量语义检索              │
│  step3: 按表聚合          ← 获取完整表结构             │
│  step4: 上下文整合         ← 知识库/历史查询          │
│  step5: LLM 生成 SQL       ← 大模型调用               │
│  step6: SQL 校验           ← 安全性检查               │
└─────────────────────────────────────────────────────┘
```

### 核心类

| 类 | 文件 | 职责 |
|---|------|------|
| `EmbeddingModel` | core/retrieval/vector_store.py | BGE-M3 模型封装，单例加载，路径缓存到 DB |
| `VectorIndex` | core/retrieval/vector_store.py | 纯 NumPy 向量索引，构建、搜索、pickle 持久化 |
| `SchemaVectorStore` | core/retrieval/vector_store.py | Schema 维度向量存储，管理字段索引 |
| `VectorIndexMeta` | models/vector_index.py | 索引元数据 ORM 模型（状态、字段数、路径） |
| `SQLPipeline` | core/retrieval/index_meta.py | 流程编排，元数据读写 |
| `KeywordExtractor` | core/retrieval/keywords.py | jieba 分词 + 停用词过滤 + TF 关键词提取 |

---

## Embedding 模型

### BGE-M3 模型

项目使用 **BAAI/bge-m3** 多语言嵌入模型：

| 属性 | 值 |
|------|-----|
| 模型名称 | `BAAI/bge-m3` |
| 向量维度 | **1024** |
| 支持语言 | 中文、英文、多语言 |
| 最大输入长度 | 8192 tokens |
| 本地路径 | `models/embeddings/bge-m3/` |
| 下载源 | ModelScope（`https://modelscope.cn`） |

### 模型加载与路径缓存

```python
# 单例模式，全局只加载一次
EmbeddingModel.get_instance()  # 首次调用加载模型
EmbeddingModel.get_instance()  # 后续调用返回缓存实例
```

加载优先级：
1. 从数据库 `EMBEDDING_MODEL_PATH` 读取缓存的路径 → 快速加载
2. 缓存失效（文件不存在）→ 扫描 `models/embeddings/` 目录 → 找到后写入 DB 缓存
3. 未找到 → 抛出异常，提示先运行 `download_model.py`

`EMBEDDING_MODEL_READY` 和 `EMBEDDING_MODEL_PATH` 两个键值存入 `system_config` 表，启动时自动同步一致性（ready=true 但 path 为空 → 自动扫描补齐）。

---

## 索引构建流程

### 构建触发条件

字段数量 >= `VECTOR_INDEX_THRESHOLD`（默认 **50**）：

```
字段数量 < 50  → 跳过索引构建，检索时直接查数据库
字段数量 >= 50 → 后台线程自动构建向量索引
```

### 详细构建步骤

#### Step 1: 收集字段文本

从主库 `queryforge.db`（db_schemas/db_tables/db_columns 三层）读取指定数据库的所有字段记录。

#### Step 2: 构造字段描述文本

```
格式: "{table_name}.{column_name}: {column_description}"
示例:
  "DM_KEY_BUDGET_INDICATOR_DATA.ACCOUNT: 科目名称"
  "DM_KEY_ACTUAL_INDICATOR_DATA.ACTUAL_VALUE: 实际金额"
```

#### Step 3: 批量向量化

调用 `EmbeddingModel.encode()` 将所有字段描述文本编码为向量矩阵（shape=N×1024）。

#### Step 4: 向量归一化

L2 归一化，使相似度计算可简化为内积：
```
余弦相似度 = 归一化向量的内积 = np.dot(vectors, query.T)
```

#### Step 5: 持久化

索引保存为 pickle 文件到 `db/vectors/{schema_name}_fields.pkl`，同时写入 `vector_index_meta` 表：

```python
# 数据库元数据
{
    "schema_name": "DM",
    "status": "ready",
    "field_count": 52,
    "table_count": 2,
    "dimension": 1024,
    "file_path": "D:\\...\\db\\vectors\\DM_fields.pkl",
    "built_at": "2026-06-10T15:44:43"
}
```

---

## 触发方式

索引有三种触发方式：

### 1. 自动触发（数据导入时）

```
CSV/JSON 导入
  → 解析 → 写入主库 db_schemas/db_tables/db_columns
  → 统计数据库总字段数 >= 50 ?
  → 是 → 标记 stale → 后台线程重建索引
  → 否 → 跳过
```

### 2. 首次查询触发

```
用户发起 SQL 生成请求
  → _try_load_vector_store()
  → 检查 vector_index_meta 表 status
  → status='ready' → 从 DB 路径直接加载
  → 元数据不存在 → 现场构建并写入元数据
```

### 3. 手动触发

```
前端"向量索引"页面点击 [重建]
  → POST /api/schema/build-vector-index {"schema_name": "DM"}
  → 全量重建
```

---

## 元数据持久化

### vector_index_meta 表

| 列 | 类型 | 说明 |
|----|------|------|
| schema_name | VARCHAR(100) | 数据库名称（唯一索引） |
| status | VARCHAR(20) | pending / building / ready / stale / error |
| field_count | INTEGER | 索引包含的字段数 |
| table_count | INTEGER | 索引覆盖的表数 |
| dimension | INTEGER | 向量维度（1024） |
| file_path | VARCHAR(500) | pickle 文件绝对路径 |
| error_message | TEXT | 构建失败时的错误信息 |
| built_at | DATETIME | 构建完成时间 |
| created_at | DATETIME | 记录创建时间 |

### 状态流转

```
pending ──→ building ──→ ready ──→ stale（新数据导入）
               │                     │
               └──→ error            └──→ building（重试）
```

### 查询优先级

```
get_vector_index_info(schema_name)
  → 查询 vector_index_meta 表
  → status='ready' → 直接返回元数据（不加载 pickle）
  → 元数据不可用 → 回退到磁盘检查 pickle 文件
```

---

## SQL 生成流程中的检索环节

### Step 1: 关键词提取

```python
keywords = keyword_extractor.extract("查询上个月销售额最高的前10个商品")
# → ["销售额", "商品", "上个月", "前10"]
```

### Step 2: 字段召回

```
关键词拼接 → EmbeddingModel.encode() → 查询向量(1024维)
  → VectorIndex.search(query_vector, top_k=20)
  → 返回 top-20 最相关字段元数据
```

### Step 3: 按表聚合

从召回字段中提取表名（去重）→ 限制最大表数（默认 10）→ 查询这些表的完整字段结构 → 构造 CSV 格式的 Schema 上下文。

### Step 4: 上下文整合 → System Prompt

```
【表结构】
schema_name, table_name, column_name, column_type, column_description, column_key, foreign_key
...

【规则】
1. 只生成SELECT查询语句
2. 确保所有列名和表名在表结构中存在
3. 使用适当的JOIN
4. 添加适当的WHERE条件
5. 基于上一轮SQL进行修改优化
6. 维度层级过滤：每个维度列必须添加WHERE条件，默认用最高级父节点

【领域知识】（可选）
...

只返回SQL语句，不要包含其他解释文字。
```

### Step 5: LLM 生成 SQL → Step 6: SQL 校验

---

## 存储结构

### 文件布局

```
项目根目录/
├── models/embeddings/bge-m3/      # BGE-M3 模型文件 (~2.2GB)
├── db/
│   ├── vectors/                   # 向量索引 pickle 文件
│   │   ├── DM_fields.pkl          # DM 数据库字段索引
│   │   └── default_fields.pkl     # 默认数据库索引
│   └── queryforge.db                # 主库（vector_index_meta 表存索引元数据）
```

### 索引文件格式 (.pkl)

```python
{
    "dimension": 1024,                    # 向量维度
    "vectors": np.ndarray,                # shape=(N, 1024), float32, L2归一化
    "documents": [                        # 字段描述文本
        "table.column: 描述", ...
    ],
    "metadata": [                         # 字段元数据
        {"table_name", "field_name", "description", "column_type", "sample_values"}, ...
    ]
}
```

---

## 关键参数

| 参数 | 默认值 | 存储位置 | 说明 |
|------|--------|---------|------|
| `VECTOR_INDEX_THRESHOLD` | **50** | system_config 表 | 字段数达到此阈值才自动构建索引 |
| `FIELD_RECALL_TOP_K` | **20** | system_config 表 | 向量检索时召回的最大字段数 |
| `MAX_TABLES` | **10** | system_config 表 | 按表聚合时包含的最大表数 |
| `EmbeddingModel._dimension` | **1024** | 代码常量 | BGE-M3 的向量维度（不可动态修改） |

> 前三个参数可在**系统设置 → 向量索引参数**页面在线修改，实时生效，无需重启。修改后写入 `system_config` 表，代码通过 `get_vector_config()` 读取。

---

## 降级策略

多层降级，确保任何环节失败不会导致服务不可用：

```
第1层: 向量索引加载
  ├── DB元数据 status='ready' → 使用向量语义检索
  └── 失败 → 扫描磁盘 pickle 文件
        ↓
第2层: pickle 加载
  ├── 成功 → 使用向量语义检索
  └── 失败 → 降级到数据库 LIKE 查询
        ↓
第3层: 数据库 LIKE 查询
  ├── 成功 → 返回关键词匹配的字段
  └── 失败 → 返回空，使用全部 Schema 作为上下文
```

---

## 并发安全

### 问题场景

```
时间 →
导入1(52字段)                    导入2(+3字段=55)
│                               │
├─ 标记stale → 启动构建线程1      │
│  ├─ 查询DB(52字段) → 编码...   │
│  │                            ├─ 标记stale → 启动构建线程2(等锁)
│  │                            │
│  ├─ 构建完成 → 尝试写ready     │
│  │  → 检测到stale → 跳过！     │
│  ├─ 重试 → 查询DB(55字段)      │
│  └─ 构建完成 → status=ready ✓  │
```

### 保护机制

1. **数据导入时标记 stale**：`_mark_index_stale()` 覆盖 `building` 状态
2. **构建完成时检测冲突**：如果状态被覆盖为 `stale`，不写入 `ready`
3. **自动重试**：检测到 stale 后重新查询数据库并重建，最多 3 次
4. **锁保护**：threading.Lock 确保同一时间只有一个构建线程运行

---

## API 参考

### 构建向量索引

```http
POST /api/schema/build-vector-index
Authorization: Bearer {token}
Content-Type: application/json

{
    "schema_name": "DM",
    "rebuild": false
}
```

### 获取索引信息（优先读 DB 元数据）

```http
GET /api/schema/vector-index-info?schema_name=DM
Authorization: Bearer {token}
```

响应：
```json
{
    "vector_dir": "D:\\...\\db\\vectors\\DM_fields.pkl",
    "field_count": 52,
    "should_build_index": true,
    "threshold": 50,
    "indexes": {
        "count": 52,
        "is_built": true,
        "filepath": "D:\\...\\db\\vectors\\DM_fields.pkl",
        "built_at": "2026-06-10T15:44:43",
        "table_count": 2
    },
    "status": "ready"
}
```

### 列出所有索引元数据（管理员）

```http
GET /api/schema/vector-index-list
Authorization: Bearer {token}
```

返回所有数据库的索引状态列表。

---

## 常见问题

### Q1: 如何判断索引是否已构建？

调用 `GET /api/schema/vector-index-info` 查看 `status` 字段，或访问前端"向量索引"管理页面。

### Q2: Schema 更新后索引会自动更新吗？

**会**。导入新 DDL/JSON/文件时，系统自动标记索引为 `stale` 并触发后台重建。如果担心未触发，可在"向量索引"页面手动点击[重建]。

### Q3: 为什么字段少时不构建索引？

字段数 < 50 时，数据库 LIKE 查询性能足够好（毫秒级），向量索引的额外开销（模型加载 ~2GB 内存、编码耗时）反而更大。

### Q4: 模型下载失败怎么办？

1. 确认网络可访问 ModelScope（`https://modelscope.cn`）
2. 手动运行 `python download_model.py`
3. 或手动下载模型文件放到 `models/embeddings/bge-m3/` 目录
4. 重启服务后路径自动写入数据库

### Q5: EMBEDDING_MODEL_PATH 为空怎么办？

重启服务即可。`_sync_embedding_model_path()` 在启动时检测到 `READY=true` 但 `PATH` 为空会自动扫描目录并补齐。

### Q6: 向量检索和数据库查询的结果会不同吗？

会。向量检索基于**语义相似度**（"价格"能匹配"金额"），数据库 LIKE 查询基于**字符串匹配**。向量检索的召回质量更高，尤其是中英文混合查询场景。

### Q7: 如何调整向量索引参数？

访问**系统设置 → 向量索引参数**，直接编辑保存即可，实时生效无需重启。常用场景：

| 场景 | 调整建议 |
|------|----------|
| Schema 字段少但查询复杂 | 降低 `VECTOR_INDEX_THRESHOLD`（如 30） |
| 数据库表非常多 | 增加 `MAX_TABLES`（如 15-20） |
| 检索精度不够 | 增加 `FIELD_RECALL_TOP_K`（如 30-50） |
| 检索速度慢 | 减少 `FIELD_RECALL_TOP_K` |
