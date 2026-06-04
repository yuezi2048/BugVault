# 元数据预过滤 — Metadata Pre-filtering

> 参见 [v1.1 架构总览](04.v1.1-architecture.md) · [评估策略](evaluation-strategy.md)

## 动机

纯语义向量搜索存在一个经典问题：不同语言的同类错误在语义空间上极度接近。

例如 Python 的 `ModuleNotFoundError` 和 Java 的 `ClassNotFoundException`，在 bge-small-zh-v1.5 的 512 维向量空间中可能只有 0.1 的余弦距离。如果不做预过滤，查询 Python 错误时会同时召回 Java 的假阳性结果，误导 Agent 给出跨语言的错误方案。

## 解决方案

在 ANN 向量检索和 FTS 全文检索之前，先通过 `WHERE` 子句对 `tech_stack` 和 `project_name` 字段做 SQL 级别的行过滤，缩小候选集后再计算向量相似度。

## 参数

| 参数 | 类型 | 作用 | 示例 |
|---|---|---|---|
| `target_tech_stack` | `str \| None` | 按技术栈过滤 | `"Python"`, `"Java"`, `"Go"` |
| `target_project_name` | `str \| None` | 按项目名过滤 | `"order-svc"`, `"bugvault-v2"` |

## 实现细节

### 过滤语法

```sql
LOWER(tech_stack) LIKE '%python%' AND LOWER(project_name) LIKE '%order-svc%'
```

### 大小写容错

使用 `LOWER()` 函数将字段值和过滤值均转为小写比较，确保 `Python`、`python`、`PYTHON` 均能匹配。

### SQL 注入防护

```python
def _sanitise_filter_value(raw: str) -> str:
    """只允许字母、数字、空格、下划线、连字符、点。"""
    return re.sub(r"[^a-zA-Z0-9_\-\. ]", "", raw.strip())
```

### 双路透传

WHERE 过滤条件**同时作用于** Vector ANN 和 FTS BM25 两路查询。不会出现一路过滤另一路全表扫描导致 RRF 融合时脏数据卷土重来的情况。

```python
filter_clause = _build_filter_clause(target_tech_stack, target_project_name)
vec_results = db.search(query_emb, filter_clause=filter_clause)
fts_results = db.search_fts(query_text, filter_clause=filter_clause)
```

## 效果

- 过滤前：ANN 直接从 75 条全量记录中召回 top-5，跨语言噪声无法排除
- 过滤后：先缩小到 ~30 条 Python 记录，再从 30 条中召回 top-5，零跨语言污染

## 相关代码

| 文件 | 职责 |
|---|---|
| `src/bugvault/mcp_tools/tools.py` | `_sanitise_filter_value()` + `_build_filter_clause()` |
| `src/bugvault/database/lancedb_client.py` | `search(filter_clause)` + `search_fts(filter_clause)` |
