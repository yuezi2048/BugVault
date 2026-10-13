# 验证状态如何影响召回与排序（BV-4）

> 状态：设计稿（待评审）
> 关联：BV-1 #5（模型与门禁）、BV-3 #7（MCP 过滤）、BV-0 #4（重开 ADR）
> 日期：2026-10-13 · 依赖已定的 `status` 取值：`suspected` / `verified` / `invalidated`

## 0. 结论（TL;DR）

- **硬过滤**：默认在**排序前**剔除 `invalidated`；`suspected` **永不**被默认剔除。
- **软加权**：`verified` 作为**有界先验**参与排序，默认幅度 `0.15`（相对候选集内归一化相关度），不足以让弱相关记录压过强相关记录。
- **显式标注**：`suspected` 在结果行与 MCP 文本里显式标注（“未验证，谨慎采信”）。
- **顺序**：先**过滤**（硬约束）→ 再**排序**（软先验）。Cross-Encoder 只负责相关性，**不感知** status。

## 1. 背景

`status` 由 BV-1 引入后，若检索对它没有规则，`verified` 就只是数据库里的一个死字段：召回既不会优先可信记录，也不会避免已否决记录。本稿回答三个问题——默认是否排除 `invalidated`、`verified` 是否加权、`suspected` 是否标注，并给出与现有 RRF / Cross-Encoder 精排的叠加方式。

## 2. 决策

### D1 · 默认排除 `invalidated`？—— 排除，作为**硬过滤**
`invalidated` 表示“此方案已被证伪”，按定义不应作为修复建议返回。默认从候选集中移除。

### D2 · `verified` 是否加权 / 优先？—— 加权，但**有界**
`verified` 提高排序，但幅度受限，只能在**近似并列**时改变顺序，不能替代相关性本身。

### D3 · `suspected` 是否显式标注？—— 标注，但**不排除**
未验证 ≠ 错误。新记录默认即 `suspected`（BV-1），排除它会掩盖唯一或最新的线索。改为显式标注，把采信判断交给 agent 客户端（符合 CONTEXT.md 的 BugVault 边界）。

### D4 · 过滤与排序的先后？—— **先过滤、后排序**
`invalidated` 是硬约束，在排序前剔除；`verified` 是软先验，在相关性排序之后再叠加。二者不在同一阶段，避免互相污染。

## 3. 落点（现有流水线）

现有链路（`src/bugvault/services/retrieval_svc.py`）：

| # | 阶段 | 现状 | status 处理 |
|---|------|------|-------------|
| 1 | `build_filter_clause` + `_record_type_filter` | tech_stack / project_name / record_type 前过滤 | —— |
| 2 | 向量 chunks + FTS chunks → `rrf_fusion` | 得到 `_rrf_score` | —— |
| 3 | `_map_chunks_to_parent_records` | chunk → 父记录合并 | **① 硬过滤插在这里之后** |
| 4 | `rerank()` | `_distance`→semantic，或 `_rrf_score` + time decay | —— |
| 5 | Cross-Encoder | 得到 `_ce_score`，纯相关性重排 | —— |
| 6 | `_to_records` → `_format_retrieval_result` | 取 top_k、格式化 | **② 软加权在最后相关性阶段之后**、**③ 标注在格式化层** |

- **① 硬过滤**：在 `_map_chunks_to_parent_records` 之后、`rerank()` 之前剔除 `invalidated`。`status` 只在父记录（`bug_records`）上，`bugvault_chunks` 表**没有** `status` 列，所以无法在 ANN 阶段前过滤；父记录阶段是“最早拿得到 status”的位置。`_to_records` 再加一道安全网。
- **② 软加权**：在**最后一个**相关性阶段之后执行一次 `apply_status_prior`（无 CE 时接在 `rerank()` 后，有 CE 时接在 CE 后）。对候选集内的相关性分数做 min-max 归一化，再叠加 status 先验并重排。
- **③ 标注**：`_format_retrieval_result` 每条结果增加 `Status:` 行；若返回集中含 `suspected`，在顶部加一行 caution。

### 打分公式

```text
relevance_norm = minmax(relevance)        # 候选集内归一化到 [0, 1]
signal         = 1.0 if status == "verified" else 0.0
final          = relevance_norm + status_weight * signal   # 默认 status_weight = 0.15
```

- `relevance` 优先取 `_ce_score`（有 CE 时），否则取 `rerank()` 的 combined 分数。
- 单候选 / 归一化退化（max == min）时 `relevance_norm = 1.0`，不因除零而丢弃。
- `invalidated` 已硬过滤，不进入打分；被显式 `target_status` 取回时 `signal = 0.0`（不奖励）。
- 加性 + 归一化是关键：CE 原始分可能为负，乘性加权会失效。

## 4. 默认行为与可配置项

新增配置（沿用 `BUGVAULT_` 前缀，`src/bugvault/config.py`）：

| 配置项 | 默认 | 含义 |
|--------|------|------|
| `retrieval_exclude_statuses` | `("invalidated",)` | 默认硬过滤的状态集合 |
| `retrieval_status_weight` | `0.15` | `verified` 先验幅度；`0` 即关闭加权 |

MCP 每次调用新增 `target_status`（BV-3 落地）：

- **省略** → 用默认硬过滤（排除 `invalidated`）。
- `target_status=["suspected","verified"]` → 只返回这两类。
- `target_status=["invalidated"]` → 显式取回被否决记录（用于复盘），且不奖励。
- 显式指定 `target_status` 时**替换**默认硬过滤集合；若只指定单一状态，则关闭加权（过滤已足够，避免二次偏置）。

**空结果反馈**：默认过滤后结果为空、但存在被过滤掉的 `invalidated` 命中时，返回一行提示：“N 条 `invalidated` 命中已被默认排除，可用 `target_status` 取回”。这**不是** Empty retrieval（CONTEXT.md）——真正的无命中仍返回空。

## 5. 理由

- **过滤与排序分离**：status 是“记录可信度”先验，不是“查询相关性”。混在一起要么误杀“相关但未验证”，要么误升“已验证但无关”。
- **软加权有界（0.15）**：`verified` 只在相关性近似并列时改变顺序，符合“验证是加分项，不是替代证据”。这与 ADR-0002「检索指标必要但不充分」一致。
- **过滤前置**：避免 `invalidated` 占用候选槽（当前 `rerank_limit = top_k * 4`），提高有效 top_k 命中率。
- **suspected 不排除**：新沉淀默认即 `suspected`，排除会摧毁多数召回。
- **CE 不感知 status**：保持 Cross-Encoder 职责单一、可替换；status 作为其后的显式先验叠加。

## 6. 反例与边界

1. **一律硬过滤 `invalidated`** → 误标或后来复验的记录被永久隐藏。→ 只做默认过滤、不改数据；`target_status` 可显式取回；空结果给提示。
2. **`verified` 权重过大** → 不相关但已验证的记录压过精确匹配的 `suspected`。→ 权重有界 + 仅候选集内归一化。
3. **先排序、后过滤** → `invalidated` 占槽，top_k 不满。→ 过滤前置到父记录阶段；必要时提高 over-fetch。
4. **排除 `suspected`** → 新记录（默认 suspected）几乎不可召回。→ 明确永不默认排除。
5. **在 CE 之后做乘性加权** → CE 分数可能为负，乘性语义反转。→ 归一化 + 加性。
6. **边界（chunks 无 status）** → 无法在 ANN 阶段过滤；本稿不做 chunks schema 扩展（超出 BV-2 范围），改用父记录阶段过滤 + 安全网。若将来 `invalidated` 大量挤占候选，再评估把 status 投影进 chunks。

## 7. 与 ADR 的关系（需显式标注）

本设计为检索**增加**过滤/排序语义，**与 ADR-0001「不再增加检索特性」相冲突**；仅在 BV-0 的重开 ADR 落地后成立。请 BV-0 在 “superseded in part” 中显式覆盖本点。

## 8. 下游接口契约

- **BV-3 #7**：`target_status` 直接映射 D1（默认排除）/ D4（先过滤后排序）；显式列表替换默认集合。
- **BV-2 #6**：只需保证 `status` 随父记录持久化；`bugvault_chunks` 表不改。
- **BV-6 #10**：Convention 可复用同一规则，仅需注意 `scope` 与 status 的语义边界（CONTEXT.md），不要用 `scope` 表达验证状态。
- **验收映射**：默认规则 = §2 D1/D4；理由 = §5；反例 = §6。
