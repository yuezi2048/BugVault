# RFC-002: Sentence Window Retrieval — 分析与方案

## 背景

当前检索策略：固定大小 chunk（800 字）→ 按 `parent_id` 聚合 → 回捞整个 parent 文档。

```python
# 当前链路
chunk(800字) → parent_id → fetch_records_by_ids → 完整 parent → Cross-Encoder
```

**问题**：如果 parent 文档很长（如 Stack Overflow 问答包含大量讨论），回捞整个文档会将噪声一并送入 LLM 和 Cross-Encoder，稀释核心信息。

## Sentence Window 方案

### 索引阶段

将文档按**句子**建立索引，而非固定大小的 chunk：

```
文档: "Nginx 在高并发下返回 502。原因是 worker 连接数不足。解决方案是增加 worker_connections。"
          ↓ 切句
Sentence 1: "Nginx 在高并发下返回 502。"
Sentence 2: "原因是 worker 连接数不足。"
Sentence 3: "解决方案是增加 worker_connections。"
```

### 检索阶段

```
用户搜索: "Nginx 502"
     ↓
匹配到: Sentence 1（置信度最高）
     ↓
窗口扩展 (window=±1):
  → "Nginx 在高并发下返回 502。原因是 worker 连接数不足。"
     ↓
传给 Cross-Encoder / LLM
```

### 优势对比

| 维度 | 当前 Small-to-Big | Sentence Window |
|---|---|---|
| 索引粒度 | 800 字符固定块 | 单句 |
| 抗噪声能力 | 弱（回捞整个 parent） | 强（只扩窗口） |
| 实现复杂度 | 低 | 中（需切句器 + 窗口逻辑） |
| 回捞查询次数 | 1 次 IN | 1 次 IN（不变） |
| 适用数据 | 精炼排障记录 | 含噪声的长文本 |

### 实现路径

需要改动三处：

#### 1. `BugRecord.to_chunks()` 改为句级切分

```python
def to_chunks(self, window_sentences: int = 0):
    """当 window_sentences=0 时保持现有 800 字行为"""
    sentences = _split_to_sentences(body)
    for sent in sentences:
        chunks.append({
            "search_text": sent,
            "sentence_idx": idx,          # 新增：句子序号
            "window_group": idx // 5,      # 新增：窗口分组
        })
```

#### 2. LanceDB 索引新增 `sentence_idx` 和 `window_group` 字段

用于检索后按窗口聚合。

#### 3. 检索链路新增窗口聚合

```python
# 当前：按 parent_id 聚合
parent_ids = list(dict.fromkeys(chunk.parent_id for chunk in results))

# Sentence Window：按 parent_id + window_group 聚合
windows = list(dict.fromkeys(
    (chunk.parent_id, chunk.window_group) for chunk in results
))
# 然后按窗口回捞句子序列拼接
```

## 结论

### 当前不建议实现

| 原因 | 说明 |
|---|---|
| BugVault 当前数据精炼 | 归档 119 条 + SO ~2000 条，无长文本噪声 |
| 实现成本 | 需要修改 chunk schema + 切句器 + 检索聚合逻辑 |
| 投入产出比 | 数据量 < 1 万条时收益不明显 |

### 何时重新考虑

- 数据来源扩展到 GitHub Issues 或长文档问答
- 单条 parent 平均长度超过 2000 字
- 用户反馈检索结果"被无关内容稀释"
