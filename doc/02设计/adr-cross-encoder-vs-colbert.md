# ADR-001: 重排策略选型 — Cross-Encoder vs ColBERT

## 背景

BugVault 的检索流水线在 V1 阶段已完成 **Vector + FTS 双路召回 → RRF 融合**。为进一步提升排序质量，需要引入精排（Re-rank）策略。

## 候选方案

### 方案 A：Cross-Encoder（选用）

- **接入方式**：通过 `fastembed.rerank.cross_encoder.TextCrossEncoder` 加载 ONNX 格式的交叉编码器
- **模型示例**：`Xenova/ms-marco-MiniLM-L-6-v2`（80MB）、`BAAI/bge-reranker-base`（1GB）
- **工作方式**：对 RRF 融合后的 top-N 候选做 (query, doc) 逐对打分，O(n) 前向传播
- **依赖**：零新增，fastembed 已通过 `fastembed.rerank` 内置支持

### 方案 B：ColBERT（放弃）

- **接入方式**：需安装 `colbert-ir` 库，依赖 PyTorch
- **模型示例**：`colbert-ir/colbertv2.0`（~400MB）
- **工作方式**：Late Interaction — 编码 query 和 doc 为 token-level 向量后做 MaxSim 运算
- **依赖**：新增 ~1.5GB（PyTorch + colbert + CUDA 驱动可选）

## 决策

**选用 Cross-Encoder，放弃 ColBERT。**

### 理由

| 维度 | Cross-Encoder | ColBERT | 决策依据 |
|------|---------------|---------|----------|
| **候选集规模** | 20 条 → 20 次前向，可接受 | 百万级检索优势，但 BugVault 只需重排 20 条 | CE 够用 |
| **存储开销** | 80MB – 1GB ONNX 模型 | ~1.5GB PyTorch 运行环境 | CE 轻量 |
| **LanceDB 集成** | 纯后处理，无需额外索引 | 需独立索引（无法复用 LanceDB） | CE 无侵入 |
| **冷启动** | 懒加载 ~2s | PyTorch 首次导入 ~10s+ | CE 更友好 |
| **重排准确率** | 业界公认 > Cross-Encoder > Bi-Encoder | Late Interaction 介于两者之间 | CE 差距优势 |
| **中文支持** | `bge-reranker-base` / `jina-reranker-v2-multilingual` | 需额外微调 | CE 开箱即用 |

### 关键权衡

ColBERT 在**检索阶段**（从百万级候选中召回）有明显优势，但 BugVault 的检索阶段已经由 LanceDB 的 ANN + Tantivy FTS 完成。精排阶段只需处理 **top-20 候选**，此时 Cross-Encoder 的逐对打分更为精准。

## 后续优化方向

- 候选集从 `top_k * 4` 调整到 `top_k * 8`（当 Cross-Encoder 吞吐量足够时）
- 模型替换为 `jina-reranker-v2-base-multilingual` 以提升多语言（含中文）错误日志的排序质量
