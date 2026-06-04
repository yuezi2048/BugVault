# RAG 评估策略 — Evaluation Strategy

## 概述

BugVault 的 RAG 评估是一个**可选的、后处理的评分步骤**，在检索结果格式化之前对结果集做质量评分。评估结果以 `--- RAG Evaluation ---` 区块追加在工具返回文本的末尾，供 Agent 判断检索结果的可靠程度。

评估器基于**策略模式**（Strategy Pattern）设计，支持通过 `eval_depth` 参数在运行时选择不同评估粒度。

## 策略总览

| `eval_depth` | 策略 | Token 消耗 | 输出维度 |
|---|---|---|---|
| `"none"` | 跳过 | 0 | 无评估区块 |
| `"simple"` | 整体打分 | ~300 | `context_relevance` + `faithfulness` + `justification` |
| `"claim_level"` | CoT 声明提取 + 验证 | ~1500 | 同上 + `claims_analysis[]` 逐条明细 |

## Simple 策略

### 流程

```
query + top-K 检索文档
       │
       ▼
  一次 LLM API 调用
  prompt: "为 context_relevance(0-5) 和 faithfulness(0-5) 打分"
       │
       ▼
  RAGEvalResult:
    rag_confidence_score = context_relevance + faithfulness (0-10)
    evaluation = justification 文本
```

### 适用场景

- 快速判断检索质量
- 对 token 成本敏感的场景
- 不需要逐条验证细节

## Claim-Level 策略

### 三步骤思维链（CoT）

```
query + top-K 检索文档
       │
       ▼
  Step 1: Claim Extraction（声明提取）
  └─ LLM 从检索文档中提取所有原子事实声明
     例: "ValueError is raised if x is not found"
       │
       ▼
  Step 2: Claim Verification（逐条验证）
  └─ 对每条声明判断是否被源文档支持
     ✅ supported — 文档明确支持
     ❌ unsupported — 文档无法证实（潜在幻觉）
     ⚠️ partial  — 文档有提及但表述模糊
       │
       ▼
  Step 3: Scoring（精细打分）
  └─ faithfulness = supported_claims / total_claims
     context_relevance = 信息需求覆盖度 (0-5)
     rag_confidence_score = faithfulness × 5 + context_relevance (0-10)
```

### 输出示例

```json
{
  "claims_analysis": [
    {
      "claim": "ValueError is raised on missing key",
      "supported": true,
      "reason": "Explicitly stated in doc 1"
    },
    {
      "claim": "Python 3.11+ required",
      "supported": false,
      "reason": "No version info in retrieved docs"
    }
  ],
  "faithfulness": 0.5,
  "context_relevance": 4.0,
  "justification": "One unsupported claim about version requirement..."
}
```

## 双重降级保护

| 层级 | 触发条件 | 行为 | 标记 |
|---|---|---|---|
| 第 1 重 | `max_claim_evals_per_session` 超限 | 自动切换 simple | `strategy_used: "simple"` |
| 第 2 重 | 任意异常（JSON/超时/API） | 捕获 + 日志 + 切换 simple | `strategy_used: "simple (fallback_from_error)"` |

## Token 用量

每次评估返回 `prompt_tokens` / `completion_tokens` / `total_tokens`，供 Agent 做成本感知决策。

## 建议行动（suggested_action）

根据评估分数自动计算的结构化建议：

| Action | 条件 | 对 Agent 的指导 |
|---|---|---|
| **CONFIDENT** | score ≥ 7.0 且 faithfulness ≥ 0.8 | 直接采信回答 |
| **PARTIAL** | score ≥ 5.0 | 部分可采信，需补充 |
| **CAUTION** | faithfulness < 0.5 | 有幻觉风险，需交叉验证 |
| **INSUFFICIENT** | context_relevance < 2.0 | 检索方向偏差，建议换关键词重查 |

## 相关代码

| 文件 | 职责 |
|---|---|
| `src/bugvault/services/rag_evaluator_svc.py` | 策略协议 + Simple + ClaimLevel 实现 + RAGEvaluator 门面 |
| `src/bugvault/models/rag_eval_result.py` | RAGEvalResult 数据模型 |
| `src/bugvault/mcp_tools/tools.py` | `_append_eval_to_lines()` 格式化输出 |
| `src/bugvault/config.py` | `enable_rag_eval`, `eval_llm_*`, `max_claim_evals_per_session` |
