# RFC-001: 智能去重（Smart Dedup）— 分析与结论

## 背景

在 Small-to-Big RAG 架构中，长文本按段落/句子边界切分为多个 chunk。相邻 chunk 的边界处可能存在文本重叠，导致索引冗余。

## 分析

### 当前架构确保不会重复

BugVault 的检索链路经过两次聚合：

```
chunk 级 RRF → dict.fromkeys(parent_id) → fetch_records_by_ids
```

`fetch_records_by_ids` 回捞的是**完整的 parent 文档**，无论有多少个 chunk 命中同一个 parent，最终传给 LLM 的只有一份完整文档。**不存在"重复信息进入 LLM"的路径。**

### 切分重叠无害

```
Chunk 1: "方案 A\n\n方案 B"
Chunk 2: "方案 C"
```

即使 Chunk 1 和 Chunk 2 在边界处有 50 字重叠，也**不影响检索质量**——因为：
- 检索阶段：重叠文本提高命中概率，无害
- 聚合阶段 `fetch_records_by_ids` 只取 parent_id，不关心 chunk 文本
- 最终传给 LLM 的是完整 parent，重叠信息被合并

## 结论

**不在当前架构下实现智能去重。** 冗余问题已被 `fetch_records_by_ids` 天然解决。

## 何时重新考虑

如果未来检索链路改为"拼接 chunk 文本而非回捞 parent"，则需要去重。但那是一个完全不同的架构设计，届时再评估。
