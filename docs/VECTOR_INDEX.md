# 向量索引构建详解

本文档详细描述 QueryForge 中向量索引的构建原理、流程和使用方法。

---

## 目录

1. [概述](#概述)
2. [架构设计](#架构设计)
3. [Embedding 模型](#embedding-模型)
4. [索引构建流程](#索引构建流程)
5. [SQL 生成流程中的检索环节](#sql-生成流程中的检索环节)
6. [触发方式](#触发方式)
7. [存储结构](#存储结构)
8. [关键参数](#关键参数)
9. [降级策略](#降级策略)
10. [API 参考](#api-参考)
11. [常见问题](#常见问题)

---

## 概述

QueryForge 使用**字段级向量索引 + 按表聚合**的 RAG（检索增强生成）方案来提升 SQL 生成质量：

```
用户问题 → 关键词提取 → 向量语义检索(top-K字段) → 按表聚合(获取完整表结构) → LLM生成SQL
```

核心思路：
- **检索阶段**：将用户自然语言问题编码为向量，在字段描述索引中搜索最相关的 top-K 个字段
- **聚合阶段**：收集这些字段所属的表（去重），获取这些表的**完整结构**作为 LLM 上下文

这样做的好处是：检索精度高（字段粒度），上下文完整（表粒度），不会因为只给了部分字段而导致 LLM 遗漏关联字段。

---

## 架构设计

### 组件关系

```
┌─────────────────────────────────────────────────────┐
│                   SQLPipeline                        │
│  (流程编排器，协调全部步骤)                            │
├─────────────────────────────────────────────────────┤
│  step1: KeywordExtractor  ← jieba 分词 + TF 统计     │
│  step2: SchemaVectorStore ← 向量语义检索              │
│  step3: 按表聚合          ← 获取完整表结构             │
│  step4: 上下文整合         ← 补充知识/历史查询         │
│  step5: LLM 生成 SQL       ← 大模型调用               │
│  step6: SQL 校验           ← 安全性检查               │
└─────────────────────────────────────────────────────┘
```

### 核心类

| 类 | 文件 | 职责 |
|---|------|------|
| `EmbeddingModel` | [core/VectorStore.py](core/VectorStore.py) | BGE-M3 模型封装，单例加载，提供文本→向量编码 |
| `VectorIndex` | [core/VectorStore.py](core/VectorStore.py) | 纯 NumPy 向量索引，构建、搜索、持久化 |
| `SchemaVectorStore` | [core/VectorStore.py](core/VectorStore.py) | Schema 维度向量存储，管理字段索引 |
| `SQLPipeline` | [core/SQLPipeline.py](core/SQLPipeline.py) | 流程编排，协调检索→聚合→生成全流程 |
| `KeywordExtractor` | [core/KeywordExtractor.py](core/KeywordExtractor.py) | jieba 分词 + 停用词过滤 + TF 关键词提取 |

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

### 模型加载机制

```python
# 单例模式，全局只加载一次，避免重复初始化开销
EmbeddingModel.get_instance()  # 首次调用加载模型
EmbeddingModel.get_instance()  # 后续调用返回缓存实例
```

加载优先级：
1. 先检查本地 `models/embeddings/bge-m3/` 目录
2. 如果本地不存在，抛出异常（需先运行 `download_model.py` 下载）
3. 不支持在线自动下载，确保离线可用

### 向量编码

```python
# 批量编码文本为向量
embeddings = EmbeddingModel.encode(["user.name: 用户姓名", "order.amount: 订单金额"])
# 返回 shape=(2, 1024) 的 float32 numpy 数组
```

---

## 索引构建流程

### 构建触发条件

索引构建需要满足 **字段数 >= 阈值**（默认 50）：

```
字段数量 < 50  → 跳过索引构建，检索时直接查数据库
字段数量 >= 50 → 后台线程自动构建向量索引
```

设计理由：字段少时数据库 LIKE 查询足够快，无需向量索引的额外开销。

### 详细构建步骤

#### Step 1: 收集字段文本

从 `sys_schema` 表中读取用户的所有 Schema 字段：

```sql
SELECT table_name, column_name, column_description, column_type
FROM schema
WHERE user_id = ? AND schema_name = ?
```

#### Step 2: 构造字段描述文本

将每个字段拼接为便于语义检索的文本：

```
格式: "{table_name}.{column_name}: {column_description}"

示例:
  "user.name: 用户姓名"
  "user.age: 用户年龄"
  "order.amount: 订单金额"
  "order.create_time: 创建时间"
```

#### Step 3: 批量向量化

调用 `EmbeddingModel.encode()` 将所有字段描述文本一次性编码为向量矩阵：

```
输入: ["user.name: 用户姓名", "user.age: 用户年龄", ...]
输出: shape=(N, 1024) 的 float32 矩阵
```

#### Step 4: 向量归一化

对每个向量做 L2 归一化，使相似度计算可以简化为内积：

```python
norms = np.linalg.norm(vectors, axis=1, keepdims=True)
norms[norms == 0] = 1          # 避免除零
vectors = vectors / norms       # 归一化到单位球面
```

余弦相似度 = 归一化向量的内积 = `np.dot(vectors, query.T)`

#### Step 5: 持久化到磁盘

将索引序列化为 pickle 文件：

```
db/vectors/user_{user_id}/{schema_name}_fields.pkl

文件内容:
{
    "dimension": 1024,
    "vectors": np.ndarray,     # 归一化后的向量矩阵
    "documents": ["表.字段: 描述", ...],  # 原始字段文本
    "metadata": [{table_name, field_name, description, column_type, sample_values}, ...]
}
```

### 构建时机

```
┌──────────────────────────────────────────────────┐
│  Schema 导入 (DDL/JSON/文件上传)                   │
│  ↓                                                │
│  保存到 sys_schema 数据库                          │
│  ↓                                                │
│  检查字段数 >= 50 ?                                │
│  ├── 是 → _auto_build_vector_index() 后台线程构建  │
│  └── 否 → 跳过                                    │
└──────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────┐
│  SQL 查询时 (首次请求)                             │
│  ↓                                                │
│  _try_load_vector_store()                        │
│  ├── 本地 .pkl 文件存在 → 加载已有索引              │
│  ├── 字段数 >= 50 但索引不存在 → 现场构建           │
│  └── 字段数 < 50 → 跳过，使用数据库查询             │
└──────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────┐
│  手动触发 (API)                                    │
│  POST /api/schema/build-vector-index              │
│  ↓                                                │
│  强制执行构建，忽略阈值检查                         │
└──────────────────────────────────────────────────┘
```

---

## SQL 生成流程中的检索环节

完整的 6 步流程：

### Step 1: 关键词提取

```python
# 使用 jieba 分词 + TF 统计
keywords = keyword_extractor.extract("查询上个月销售额最高的前10个商品", top_k=10)
# → ["销售额", "商品", "上个月", "前10"]
```

内置停用词过滤掉无意义词汇（"的"、"了"、"查询"、"显示" 等）和纯数字。

### Step 2: 字段召回

```
                     ┌── 向量索引可用？
                     │
         ┌─ 是 ──────┤
         │           └── 否 → 数据库 LIKE 查询（降级）
         ↓
  将关键词拼接: "销售额 商品 上个月 前10"
         ↓
  EmbeddingModel.encode() → 查询向量 (1024维)
         ↓
  VectorIndex.search(query_vector, top_k=20)
         ↓
  返回 top-20 最相关的字段元数据
```

**向量搜索**（`VectorIndex.search`）：

```python
# 1. 归一化查询向量
query = query / np.linalg.norm(query)

# 2. 计算余弦相似度（归一化后等价于内积）
similarities = np.dot(vectors, query.T).flatten()

# 3. 取 top-k 索引
top_indices = np.argsort(similarities)[-top_k:][::-1]

# 4. 返回 (文档文本, 元数据, 距离)
return [(documents[i], metadata[i], 1.0 - similarities[i]) for i in top_indices]
```

### Step 3: 按表聚合

```python
# 从召回字段中提取表名（去重）
table_names = list(set(f['table_name'] for f in recalled_fields))

# 限制最大表数（默认 10），超过时按字段命中数排序取前10
if len(table_names) > MAX_TABLES:
    # 按每个表的命中字段数降序排列，优先保留命中多的表
    ...

# 查询这些表的完整字段结构
complete_fields = get_table_complete_fields(table_names)

# 构造 CSV 格式的 Schema 上下文
```

**聚合效果示例**：

```
召回字段: user.id, user.name, order.amount
       ↓ 按表聚合
获取完整结构:
  - user 表: id, name, age, email, phone, address, ...
  - order 表: id, user_id, amount, status, create_time, ...
```

### Step 4: 上下文整合

将补充知识（字段示例值、表间关系、领域知识）和历史成功查询整合到上下文。

### Step 5: LLM 生成 SQL

将构造好的 prompt 发送给大模型生成 SQL。

### Step 6: SQL 校验

验证生成的 SQL 安全性（只允许 SELECT/WITH，禁止 DROP/DELETE/UPDATE/INSERT 等）。

---

## 存储结构

### 文件布局

```
项目根目录/
├── models/
│   └── embeddings/
│       └── bge-m3/                  # BGE-M3 模型文件
│           ├── config.json
│           ├── pytorch_model.bin    # 模型权重 (~2.2GB)
│           ├── tokenizer.json
│           └── ...
├── db/
│   ├── vectors/                     # 向量索引存储
│   │   └── user_{user_id}/
│   │       ├── {schema_name}_fields.pkl    # 字段级索引
│   │       └── default_fields.pkl          # 默认 schema 索引
│   └── sys_schema.db                # Schema 元数据（SQLite）
```

### 索引文件格式

```python
# 序列化格式 (.pkl)
{
    "dimension": 1024,                    # 向量维度
    "vectors": np.ndarray,                # shape=(N, 1024), float32, L2归一化
    "documents": [                        # 字段描述文本列表
        "users.name: 用户姓名",
        "orders.amount: 订单金额",
        ...
    ],
    "metadata": [                         # 字段元数据列表
        {
            "table_name": "users",
            "field_name": "name",
            "description": "用户姓名",
            "column_type": "varchar(100)",
            "sample_values": "张三,李四"
        },
        ...
    ]
}
```

---

## 关键参数

| 参数 | 默认值 | 位置 | 说明 |
|------|--------|------|------|
| `VECTOR_INDEX_THRESHOLD` | **50** | `SQLPipeline` / `SchemaVectorStore` | 字段数达到此阈值才构建向量索引 |
| `FIELD_RECALL_TOP_K` | **20** | `SQLPipeline` | 向量检索时召回的最大字段数 |
| `MAX_TABLES` | **10** | `SQLPipeline` | 聚合时包含的最大表数 |
| `EmbeddingModel._dimension` | **1024** | `VectorStore` | BGE-M3 的向量维度 |
| `EmbeddingModel._model_name` | **bge-m3** | `VectorStore` | 使用的 embedding 模型名称 |

### 调整建议

| 场景 | 建议调整 |
|------|----------|
| Schema 字段少但查询复杂 | 降低 `VECTOR_INDEX_THRESHOLD`（如 30） |
| 数据库表非常多 | 增加 `MAX_TABLES`（如 15-20） |
| 检索精度不够 | 增加 `FIELD_RECALL_TOP_K`（如 30-50） |
| 检索速度慢 | 减少 `FIELD_RECALL_TOP_K` |
| 模型太大加载慢 | 换用小模型如 `bge-small-zh`（512维） |

---

## 降级策略

系统设计了多层降级，确保任何环节失败都不会导致服务不可用：

```
第1层: 向量索引加载
  ├── 成功 → 使用向量语义检索
  └── 失败 → 降级到数据库 LIKE 查询
        ↓
第2层: 数据库 LIKE 查询
  ├── 成功 → 返回关键词匹配的字段
  └── 失败 → 返回空列表
        ↓
第3层: 字段召回为空
  └── 跳过按表聚合，使用全部 Schema 作为上下文
```

### 降级触发条件

1. **模型未安装** → `ImportError` → 不构建索引
2. **模型文件损坏** → `RuntimeError` → 不构建索引
3. **字段数量 < 50** → 不构建索引，直接查库
4. **索引文件不存在** → 尝试现场构建，失败则查库
5. **embedding 编码异常** → 捕获异常，降级到查库

降级时系统行为不变，只是检索精度略有下降（关键词匹配 vs 语义匹配）。

---

## API 参考

### 构建向量索引

```http
POST /api/schema/build-vector-index
Authorization: Bearer {token}
Content-Type: application/json

{
    "schema_name": "mydb",    // 可选，不指定则构建所有
    "rebuild": false          // 是否强制重建
}
```

响应：
```json
{
    "success": true,
    "message": "向量索引构建成功",
    "result": {
        "success": true,
        "indexes": {
            "fields": { "count": 256 }
        },
        "field_count": 256
    }
}
```

### 获取索引信息

```http
GET /api/schema/vector-index-info?schema_name=mydb
Authorization: Bearer {token}
```

响应：
```json
{
    "user_id": 1,
    "dimension": 1024,
    "vector_dir": "db/vectors/user_1",
    "field_count": 256,
    "should_build_index": true,
    "threshold": 50,
    "indexes": {
        "fields": {
            "count": 256,
            "is_built": true,
            "filepath": "db/vectors/user_1/mydb_fields"
        }
    }
}
```

---

## 常见问题

### Q1: 如何判断索引是否已构建？

调用 `GET /api/schema/vector-index-info`，检查 `fields.is_built` 字段。

也可以直接检查文件：`db/vectors/user_{user_id}/{schema_name}_fields.pkl` 是否存在。

### Q2: 索引文件有多大？

索引文件大小取决于字段数量：

```
文件大小 ≈ N × (1024 × 4 + 文本长度) 字节

示例: 1000 个字段 ≈ 1000 × (4096 + 200) ≈ 4.3 MB
      10000 个字段 ≈ 43 MB
```

### Q3: Schema 更新后索引会自动更新吗？

**不会**。当前版本需要手动重建索引：
```http
POST /api/schema/build-vector-index  {"schema_name": "xxx", "rebuild": true}
```

### Q4: 为什么字段少时不构建索引？

字段数 < 50 时，数据库 LIKE 查询性能足够好（毫秒级），向量索引的额外开销（模型加载 ~2GB 内存、编码耗时）反而更大。

### Q5: 模型下载失败怎么办？

1. 确认网络可访问 ModelScope（`https://modelscope.cn`）
2. 手动运行 `python download_model.py`
3. 或手动下载模型文件放到 `models/embeddings/bge-m3/` 目录

### Q6: 能否换用其他 Embedding 模型？

可以。修改 `core/VectorStore.py` 中的 `EmbeddingModel._model_name`，并确保维度匹配。常用选择：

| 模型 | 维度 | 语言 | 大小 |
|------|------|------|------|
| BAAI/bge-m3 | 1024 | 多语言 | ~2.2GB |
| BAAI/bge-large-zh-v1.5 | 1024 | 中文 | ~1.3GB |
| BAAI/bge-small-zh-v1.5 | 512 | 中文 | ~95MB |
| sentence-transformers/all-MiniLM-L6-v2 | 384 | 英文 | ~90MB |

### Q7: 向量检索和数据库查询的结果会不同吗？

会。向量检索基于**语义相似度**（"价格"能匹配"金额"），数据库 LIKE 查询基于**字符串匹配**。向量检索的召回质量更高，尤其是中英文混合查询场景。

### Q8: 导入 Schema 后多久可以使用向量检索？

- 字段 >= 50：导入时触发**后台线程**异步构建，通常几秒内完成（取决于字段数量和机器性能）
- SQL 查询时：如果索引不存在会**同步构建**，首次查询可能有 1-3 秒延迟
