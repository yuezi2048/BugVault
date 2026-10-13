# BugVault 项目全景文档

> 一句话定位：**给 AI 编程客户端装上「项目级长时记忆」的本地 MCP 服务——同样的错误只犯一次，项目规约只教一遍。**
>
> 文档基线：`2026-09-03`，以当前工作区代码为准（HEAD `d62b482`，另有未提交的持久化模块重构）。
> 本文件是总纲。与旧文档冲突时，以**代码 + 本文件**为准；文中所有「历史口径」均明确标注时间与来源，未经验证的指标不当作当前事实。

---

## 目录

1. [项目是什么（第一性原理）](#1-项目是什么第一性原理)
2. [运行形态与交付](#2-运行形态与交付)
3. [系统能力地图：MCP 工具](#3-系统能力地图mcp-工具)
4. [架构分层](#4-架构分层)
5. [数据模型与存储设计](#5-数据模型与存储设计)
6. [检索子系统 RetrievalModule](#6-检索子系统-retrievalmodule)
7. [保存 / 持久化子系统 RecordPersistence](#7-保存--持久化子系统-recordpersistence)
8. [RAG 评估子系统](#8-rag-评估子系统)
9. [反思与预防规则](#9-反思与预防规则)
10. [可观测性与上线护栏](#10-可观测性与上线护栏)
11. [版本演进](#11-版本演进)
12. [关键技术决策与已否决方案](#12-关键技术决策与已否决方案)
13. [质量验证与数据资产](#13-质量验证与数据资产)
14. [边界、风险与工程债](#14-边界风险与工程债)
15. [后续路线](#15-后续路线)
- [附录 A：面试口径速查](#附录-a面试口径速查)
- [附录 B：文档与源码地图](#附录-b文档与源码地图)

---

## 1. 项目是什么（第一性原理）

### 1.1 要解决的底层问题

1. **AI 编程助手能力很强，但没有跨会话的项目记忆。** 它只记得当前对话；不记得这个项目昨天踩过什么坑、规定用哪个框架、测试文件叫什么后缀。
2. **没有记忆，最贵的浪费是「重复犯错」。** 同一个 bug 修好之后，换一个会话可能再犯；项目规约（金额单位、ID 类型、目录约定）被反复违反；工程师反复 debug、反复 review 同一类问题。
3. **人类对抗遗忘的武器（文档、笔记）对 AI 不生效。** 聊天记录不可检索、文档 AI 不会主动读、把规则塞进 prompt 上下文放不下。

结论：AI 编程工具缺的不是能力，而是「一个可持续积累、每次开工前自动查询的项目记忆」。

### 1.2 BugVault 的价值主张

BugVault 用一个闭环解决上述问题：

```text
排障中（检索历史经验）
   ↓
解决后（保存结构化记录）
   ↓
复盘后（沉淀预防规则）
   ↓
下一次会话（先查再动手）—— 永不再犯
```

具体价值：

- **对个人开发者**：同一类问题不 debug 第二遍，同一条 review 意见不提第二遍。
- **对团队**：个人踩坑经验与项目规约变成可继承资产，新人或新 Agent 直接受益。
- **对安全与合规**：全部数据本地存储（LanceDB + Markdown），无云端、无 API 费用、代码不出机器。
- **对 AI 生态**：通过 MCP 标准协议交付，「一次编写，处处运行」，不绑定某个客户端。

### 1.3 边界（本项目不是做什么）

- **不是 Agent 框架**：不负责规划、不修改代码、不执行 Agent Loop；决策权在 MCP 客户端。
- **不是 Web 服务**：运行形态是 Python stdio MCP Server，由客户端拉起（Claude Code / Cursor / Claude Desktop 等）。
- **价值依赖客户端调用工具**：若客户端或 Skill 跳过检索/保存，BugVault 无法自动干预。
- **当前是单用户本地工具端点**：没有多租户、鉴权、分布式任务可靠性。

---

## 2. 运行形态与交付

### 2.1 形态

- Python ≥ 3.13，`uv` 管理依赖，`hatchling` 构建。
- 依赖核心：`mcp`（协议）、`lancedb`（向量库）、`fastembed`（本地 ONNX 嵌入/重排）、`pydantic`（模型与校验）、`ladybug`（图叠加层）。
- 启动：`uv run python -m bugvault.main`（或安装后 `bugvault`）。

### 2.2 客户端接入

```json
{
  "mcpServers": {
    "bugvault": {
      "command": "/path/to/uv",
      "args": ["run", "--directory", "/绝对路径/bugvault", "python", "-m", "bugvault.main"]
    }
  }
}
```

### 2.3 数据与配置

- 数据根目录默认 `~/.bugvault/`（可用 `BUGVAULT_DATA_ROOT` 覆盖）。
- 全部配置走环境变量，前缀 `BUGVAULT_`（pydantic-settings）。
- 关键配置（代码默认值，`src/bugvault/config.py`）：

| 配置 | 默认 | 含义 |
|---|---|---|
| `BUGVAULT_DATA_ROOT` | `~/.bugvault` | 数据根目录 |
| `BUGVAULT_EMBEDDING_MODEL` | `BAAI/bge-small-zh-v1.5` | 本地嵌入模型（512 维） |
| `BUGVAULT_TOP_K` | `5` | 最终返回条数 |
| `BUGVAULT_MIN_SEMANTIC_SCORE` | `0.50` | ANN 语义底线（低于即丢弃） |
| `BUGVAULT_ENABLE_FTS` | `true` | BM25 双路召回开关 |
| `BUGVAULT_ENABLE_RERANKER` | `true` | Cross-Encoder 精排开关 |
| `BUGVAULT_RERANKER_MODEL` | `jinaai/jina-reranker-v2-base-multilingual` | 精排模型（约 1.1 GB） |
| `BUGVAULT_ENABLE_RECENCY_DECAY` | `false` | 时间衰减（默认关，旧经验仍有价值） |
| `BUGVAULT_ENABLE_ASYNC_EMBEDDING` | `true` | 后台异步嵌入 + 入库 |
| `BUGVAULT_ENABLE_RAG_EVAL` | `false` | 可选外部裁判 LLM 评估 |
| `BUGVAULT_EVAL_LLM_MODEL` | `gpt-4o-mini` | 裁判模型（兼容 OpenAI 协议） |
| `BUGVAULT_MAX_CLAIM_EVALS_PER_SESSION` | `10` | claim-level 评估熔断上限 |
| `BUGVAULT_ENABLE_REFLECTION_TOOL` | `true` | 复盘工具开关 |
| `BUGVAULT_THREAD_POOL_WORKERS` | `2` | 异步 I/O 线程数 |

> 注意：`.env.example` 中个别注释与代码默认值不一致（如 `MIN_SEMANTIC_SCORE` 注释为 0.65、`SERVER_VERSION` 为 1.0.0），属文档欠维护项，以代码为准。

---

## 3. 系统能力地图：MCP 工具

默认配置暴露 **5 个工具**（4 个基础工具 + 1 个可关闭的反思工具）。

| 工具 | 职责 | 何时调用 | 备注 |
|---|---|---|---|
| `save_bug_experience` | 保存已解决的 Bug 经验 | 修完 Bug / 异常后 | 4 个必填字段 |
| `retrieve_bug_experience` | 开工前检索历史坑 | 改业务/DB/API/性能/安全相关代码前 | 支持技术栈/项目过滤 + 可选 RAG 评估 |
| `save_convention` | 保存项目规约（架构/命名/测试/风格） | 用户纠正「规则类」问题后 | v2.0 引入 |
| `retrieve_convention` | 开工前查项目规约 | 涉及架构/命名/UI 规范时 | 与 bug 检索共用管线，按 `record_type` 过滤 |
| `reflect_and_prevent_error`（可选） | 根因反思 + 写预防规则 | Agent 系统性误解 / 同类 Bug 反复 / 架构误判 | 写入 `CLAUDE.md` |

工具 description 内置决策树，引导 Agent 判断「先查坑、再查规约」还是「纯样式改动直接开工」，降低乱调用。

---

## 4. 架构分层

### 4.1 目录结构与单向依赖

```text
src/bugvault/
├── main.py                     # 入口：配置 + 依赖装配 + stdio 事件循环
├── config.py                   # pydantic-settings 全局配置
├── observability.py            # AI 调用日志 / 错误分类 / token 成本估算
├── mcp_tools/tools.py          # 协议适配层：tool schema、路由、文本契约
├── services/                   # 领域服务（业务逻辑唯一来源）
│   ├── retrieval_svc.py        # RetrievalModule：检索全流程
│   ├── persistence_svc.py      # RecordPersistence：校验→归档→入库→图投影
│   ├── archive_svc.py          # Markdown 归档（Bug / Convention）
│   ├── embedding_svc.py        # fastembed 封装（含批量 API）
│   ├── reranker_svc.py         # Cross-Encoder 单例封装
│   ├── rag_evaluator_svc.py    # RAG 评估：策略模式 + 双重降级
│   ├── reflection_svc.py       # CLAUDE.md 预防规则读写
│   ├── ingestion_svc.py        # 必填字段校验 + 补问话术
│   └── db_maintenance_svc.py   # 清库、归档重导入、并发重建
├── database/
│   ├── lancedb_client.py       # LanceDB DAO（双表、FTS、迁移、锁）
│   └── graph_db.py             # LadybugDB 图叠加层（写侧投影）
├── models/                     # BugRecord / ConventionRecord / RAGEvalResult / PreventionRule / ErrorCode
└── utils/                      # stdout_guard / logger(trace_id) / text_utils
```

依赖纪律（代码约定，非强制的 import-lint）：

```text
protocol (mcp_tools)  →  services（领域逻辑）  →  database / models / utils
```

`mcp_tools` 不直接 import `database`，只通过 service 对象访问存储。

### 4.2 进程模型与并发设计

- **异步主循环**：MCP stdio 事件循环处理 JSON-RPC。
- **同步 I/O 下放线程池**：LanceDB 读写、embedding、重排等阻塞操作通过 `run_in_executor` 提交到共享 `ThreadPoolExecutor`，保证事件循环不阻塞。
- **LanceDB 并发保护**：Python `_table` 在并发下不保证可见性，DAO 内用 `threading.Lock` 串行化搜索/写入。
- **模型单例 + 惰性加载**：Embedding 启动预热；Cross-Encoder 首次调用加载（1.1 GB，冷启动慢），后续复用；加载失败降级不崩溃。
- **stdout 守护**：`stdout_guard` 必须在任何三方库 import 前生效，拦截 tqdm/rich 等对 stdout 的污染，保障 MCP stdio 的 JSON-RPC 纯净。

### 4.3 一次请求的可追溯性

`handle_call_tool` 入口：

1. 生成 `trace_id`（12 位 hex，contextvars 贯穿本次调用）。
2. 写 `ai_call.jsonl` entry 日志。
3. 路由到具体 handler → 业务执行。
4. 写 exit 日志（状态 / error_code / 耗时）。
5. 异常统一捕获分类，返回文本错误，不影响服务存活。

---

## 5. 数据模型与存储设计

### 5.1 领域模型

**BugRecord（Bug 经验）**——4 必填：

| 字段 | 约束 | 说明 |
|---|---|---|
| `bug_title` | 1–256 | 短标题 |
| `error_log_snippet` | 1–32768 | 报错/堆栈（自动剥 ANSI 色码） |
| `tried_methods` | 1–8192 | 已尝试（失败的路径） |
| `final_solution` | 1–16384 | 最终方案 |
| `project_name` / `tech_stack` / `root_cause` | 可选 | 元数据与根因 |
| `record_id` | 自动 | `MD5(bug_title + error_log_snippet)` 去重键 |
| `create_time` | 自动 | ISO-8601 UTC |

**ConventionRecord（项目规约）**——4 必填：

| 字段 | 语义 | 映射到共享表列 |
|---|---|---|
| `convention_name` | 规则名 | `bug_title` |
| `trigger_context` | 适用场景 | `error_log_snippet` |
| `incorrect_behavior` | 不该做的行为 | `tried_methods` |
| `correct_behavior` | 该怎么做 | `final_solution` |
| `scope` / `tags` | 适用范围/标签 | `project_name` / `tech_stack` |
| `record_id` | `MD5(convention_name + trigger_context)` | — |
| `record_type` | 恒为 `"convention"` | 鉴别器 |

**RAGEvalResult**：评估输出（全部可选字段），含 `strategy_used`、`rag_confidence_score`、`context_relevance`、`faithfulness`、`claims_analysis[]`、`suggested_action`、token 用量与 `estimated_cost_usd`。

**PreventionRule**：CLAUDE.md 中的预防规则条目（`rule_number`、`error_category`、`preventive_rule`、`reflection_text`、`created_at`）。

### 5.2 LanceDB：双表 + 鉴别器

Bug 与 Convention **共用同一套表结构**，靠 `record_type` 区分（避免双份检索代码，迁移成本低，未来可加第三种类型）：

| 表 | 角色 | 内容 |
|---|---|---|
| `bug_records`（父表） | 完整文档 | 全字段 + `search_text` + 512 维向量 + `record_type` |
| `bugvault_chunks`（子表） | 检索前门 | `chunk_id` / `parent_id` / `chunk_type` / `search_text` / `vector` + 冗余 `tech_stack`/`project_name`/`record_type` 支持过滤下推 |

父记录由子块命中后批量回捞（Small-to-Big RAG）。历史上导入的父记录可写零向量 `[0.0]*512`（不参与距离计算，只为满足 schema）。

### 5.3 分块策略

- **Bug**：1 个 `error_log` 块（标题+报错，精确匹配）+ 1 个以上 `semantic` 块（标题+尝试+方案+根因，语义匹配）。
- **Convention**：1 个 `context` 块（规则名+触发场景）+ 1 个以上 `correct_behavior` 块（规则名+错误行为+正确行为）。
- 单块上限 800 字符；超限按「段落 → 行 → 字符」递归切分，保证总能切成功。

### 5.4 本地数据布局

```text
~/.bugvault/
├── lancedb/                     # LanceDB 双表
├── archive/                     # Bug 经验 Markdown（Obsidian 兼容 YAML frontmatter）
│   └── conventions/             # 规约 Markdown（v2.0）
├── CLAUDE.md                    # 预防规则（## Bug Prevention Rules）
├── graph/                       # LadybugDB 图库
└── log/
    ├── bugvault.log             # 进程日志（stderr，含 trace_id）
    ├── ai_call.jsonl            # 工具调用 entry/exit 结构化日志
    └── rag_eval.jsonl           # 每次评估结果 + token + 成本
```

Markdown 归档设计为「人可读 + 可恢复」：任何时刻都有与向量库独立的明文副本，`rebuild_index.py` 可从归档重建索引。

### 5.5 去重、迁移与一致语义

- **去重/更新**：`record_id`（或 `chunk_id`）为主键，`merge_insert` + `when_matched_update_all` 实现 upsert。
- **v1 → v2 自动迁移**：启动时检查 `record_type` 列，缺失则 `add_columns` 回填 `'bug'`，幂等、无损；另有 `scripts/migrate_v2.py` 手动执行。
- **旧库兼容**：检索层捕获「No field named」自动去掉过滤器重试，旧数据不因新列缺失而中断。

---

## 6. 检索子系统 RetrievalModule

### 6.1 检索漏斗（当前代码）

```text
query + 可选过滤(target_tech_stack / target_project_name / record_type)
  │
  ├─ 1. 生成 query embedding（bge-small-zh-v1.5, 512d）
  ├─ 2. bugvault_chunks 向量 ANN      → top_k × 4
  ├─ 3. bugvault_chunks FTS(BM25)     → top_k × 4
  │        （FTS 失败/关闭 → 纯向量；chunks 无命中 → 父表 FTS 兜底）
  ├─ 4. 行级 RRF 融合（k=60）
  ├─ 5. 按 parent_id 取每父最佳块 → 去重
  ├─ 6. fetch_records_by_ids(IN ...) 批量回捞完整父记录（防 N+1）
  ├─ 7. rerank()：对向量命中行做语义底线过滤（1 − distance/2 ≥ 0.50），
  │         RRF / FTS-only 行保留融合分；可选时间衰减（默认关）
  ├─ 8. Cross-Encoder 二次精排（可选；失败 → 保留 RRF 顺序）
  └─ 9. 截断 top_k（默认 5）
```

### 6.2 为什么这么设计

| 设计 | 解决的问题 |
|---|---|
| 双路召回 | 语义相似（「连不上数据库」）与关键词精确（`ModuleNotFoundError`、变量名）互补 |
| RRF 而非分数融合 | 余弦距离与 BM25 分数量纲不同不可相加；RRF 只用排名，k=60 业界标准 |
| 子块为主检索入口 | 长文档单向量会把报错特征稀释；小块聚焦命中更准 |
| parent 归并 + IN 回捞 | 检索返回完整记录供 Agent 使用，同时避免逐条查询 N+1 |
| Cross-Encoder 精排 | 候选仅 5–20 条，O(n) 二次打分成本低，精度优于双编码器 |
| 元数据预过滤 | Python 的 `ModuleNotFoundError` 与 Java 的 `ClassNotFoundException` 语义接近，先按技术栈/项目缩小候选，杜绝跨语言污染 |
| 多级降级 | 任一环节（FTS/重排/评估）失败都不阻塞主检索 |

### 6.3 过滤与安全

- 过滤语法：`LOWER(tech_stack) LIKE '%python%' AND LOWER(project_name) LIKE '%order-svc%'`，大小写容错。
- 注入防护：`sanitise_filter_value` 只允许 `[a-zA-Z0-9_\-. ]`。
- 技术栈歧义排除：`target_tech_stack="Java"` 时附加 `NOT LIKE '%javascript%'`，避免 LIKE 误中。
- 双路透传：过滤条件同时作用于向量与 FTS，防止一路漏滤导致脏数据回流。
- `record_type` 过滤器由领域层自动追加（`'bug'` / `'convention'`）。

### 6.4 返回契约

文本块结构：

```text
--- Retrieval Info ---
Strategy: hybrid + Cross-Encoder reranking
Sources:  N vector + M FTS

--- Result 1 ---
Title / Scope / Time
Error(Context): …
Tried(Incorrect): …
Solution(Correct): …
Note(root_cause): …

--- RAG Evaluation ---   （仅 retrieve_bug_experience 且启用评估时）
```

单条记录字段按 `settings.max_record_chars`（4000）截断，防止长报错撑爆上下文。

---

## 7. 保存 / 持久化子系统 RecordPersistence

### 7.1 保存链路（当前代码）

```text
Agent 调用 save_bug_experience / save_convention
  │
  ├─ 同步：Pydantic 校验（必填 + 长度）
  │      ├─ 缺必填 → 返回 draft + 缺失字段清单（补问话术与「最多 3 轮」尚未接线，见 §14.3.1）
  │      ├─ 结构非法 → 返回 validation_error
  │      └─ 完整 → 写 Markdown 归档（可读副本先行）
  │
  └─ 异步（fire-and-forget task，线程池执行）：
       批量 embedding（父 search_text + 各 chunk）→ upsert 父记录
       → upsert chunks → 投影 LadybugDB 图边（可选、失败非致命）
```

### 7.2 一致性语义

- **先归档、后索引**：保证「人可读副本」立即可得；向量索引最终一致。
- **调用方不等待**：MCP 返回 `saved successfully` 后后台入库，避免 Agent 阻塞在 ONNX/LanceDB 上。
- **后台失败不反噬主链路**：`_persist_record_in_background` 捕获异常写日志，不向上抛。
- **批量嵌入**：`embedding_svc.generate_embeddings()` 一次提交多个文本，利用 ONNX 批处理。

### 7.3 明确边界（重要）

异步索引是进程内 `asyncio.create_task`，**没有任务队列与完成回执**：归档成功但进程恰好在向量写入前退出时，索引可能缺失。这是已知边界，不是已解决的特性。

---

## 8. RAG 评估子系统

### 8.1 定位

可选的**检索后质量评估钩子**，只给结果附加可信度信息，绝不修改检索结果本身。默认关闭（`BUGVAULT_ENABLE_RAG_EVAL=false`）；开启后调用外部裁判 LLM（兼容 OpenAI 协议），因此「默认本地检索」与「启用评估时依赖外部 API」必须分开表述。

### 8.2 策略（策略模式 + 门面）

| `eval_depth` | 策略 | 消耗 | 输出 |
|---|---|---|---|
| `none` | 跳过 | 0 | 无评估块 |
| `simple` | 整体打分 | ~300 tokens | relevance + faithfulness + justification |
| `claim_level` | 三步 CoT：提取原子声明 → 逐条验证 supported/unsupported/partial → 打分 | ~1500 tokens | 同上 + `claims_analysis[]` |

评分口径：

```text
faithfulness (claim_level) = supported_claims / total_claims
rag_confidence_score       = faithfulness × 5 + context_relevance   （0–10）
```

### 8.3 双重降级

| 层级 | 触发 | 结果 | 标记 |
|---|---|---|---|
| 第 1 重 | claim-level 会话配额（10 次）耗尽 | 降级 simple | `strategy_used="simple"` |
| 第 2 重 | 任意异常（JSON 残缺/超时/API 错） | 降级 simple | `strategy_used="simple (fallback_from_error)"` |

> 边界：claim 计数器是**类变量（进程全局）**，不会按用户/会话自动重置；准确说法是「进程生命周期内的全局配额」。

### 8.4 输出建议与成本

- `suggested_action`：`CONFIDENT`（≥7.0 且 faithfulness ≥0.8）/ `PARTIAL` / `CAUTION`（faithfulness <0.5，防幻觉）/ `INSUFFICIENT`（context_relevance <2.0，检索方向偏）。
- 每次评估返回 prompt/completion/total tokens，并按内置模型价格表估算 `estimated_cost_usd`（未知模型走保守默认价）。
- 评估结果落 `rag_eval.jsonl`，可离线复盘 bad case。

---

## 9. 反思与预防规则

`reflect_and_prevent_error`（可选工具，默认开启）：

- 输入：`reflection_text`（根因分析）+ `error_category`（`understanding_bias` / `code_logic_error` / `api_misuse` / `environment_issue` / `other`）+ `preventive_rule`（可执行预防规则）。
- 输出：追加到 `CLAUDE.md` 的 `## Bug Prevention Rules` 章节，自动编号、带时间戳与分类。
- 机制：CLAUDE.md 作为客户端启动时自动加载的项目级文件，实现「规则常驻上下文」，与检索库互补（规则常驻，经验按需检索）。

---

## 10. 可观测性与上线护栏

按「AI 上线最小护栏清单」实现并覆盖的 4 项：

| 护栏 | 实现 |
|---|---|
| traceId 贯穿 | `contextvars.ContextVar` + 日志 Filter，一次调用所有日志共享 trace_id |
| 结构化错误码 | `ErrorCode` 枚举：`ok` / `rate_limited` / `timeout` / `auth_fail` / `content_safety` / `parse_error` / `validation_error` / `internal` / `not_found` / `quota_exceeded`；`_classify_error` 按异常启发式映射 |
| 统一 AI 调用日志 | `handle_call_tool` 每次 entry/exit 两条 JSONL（可区分「卡住未返回」与「正常返回」），记录耗时/状态/错误码 |
| Token 成本估算 | 内置模型价格表 + 默认兜底价，评估结果带 `estimated_cost_usd`；成本计算失败不影响主流程 |

> **口径校正（2026-10-09 show-me 复核）**：上表代码落点存在两条需要打折的表述。其一，`ErrorCode` 枚举虽列出 `validation_error` / `not_found` / `quota_exceeded`，但 `_classify_error` 只映射 rate_limit / timeout / auth / content / parse → internal，这三个值在 MCP 链路不可达。其二，exit 日志的正常 `return` 分支硬编码 `status="ok", error_code="ok"`，非法参数、draft、空结果都被记成成功，因此「可区分卡住与正常返回」只对抛异常路径成立。详见 §14.3.6、§14.3.7。

配套防线：stdout 纯净守卫、FTS/重排/评估多级降级、路径 `expanduser().resolve()` + `mkdir` 前置、LLM 响应强制 `response_format=json_object` + fence 剥离。

---

## 11. 版本演进

| 版本 | 核心内容 | 主要证据 |
|---|---|---|
| v1.0.0（MVP） | 三工具骨架、DAO 分层、线程池异步化、stdout 守护、MD5 去重、43 测试 | `RELEASE_NOTES.md` |
| v1.1 | 双路召回 + RRF、Cross-Encoder 精排、Claim-level 评估、双重降级、元数据过滤、路径安全 | [v1.1 架构](refer/设计/04.v1.1-architecture.md) |
| v1.1.1 | Small-to-Big：父子分块双表、父表零向量、FTS 双表索引、chunk 主检索入口 | [技术决策](refer/设计/v1.1.1-technical-decisions.md)、测试报告 |
| v2.0.0 | 规约记忆（save/retrieve_convention）、共享表 + `record_type` 鉴别器、自动 schema 迁移、规约归档 | [v2.0 发布说明](v2.0/v2.0.0-release-notes.md) |
| v2.0 之后的增量（已提交） | LadybugDB 图叠加层（写侧投影）、批量 embedding API、4 项上线护栏（traceId/错误码/AI 调用日志/Token 成本）、工具 description 决策树、离线检索 benchmark、检索模块化（`RetrievalModule`） | 提交历史（`7d77441`/`582a874`/`5ec701f`/`f957d6c`/`d62b482` 等） |
| 工作区未提交增量 | `RecordPersistence` 持久化模块重构（新增 `persistence_svc.py`，`tools.py` 与测试同步调整） | 2026-09-03 工作区状态 |

仓库共 **84 个 commit**（2026-05 → 2026-07，HEAD `d62b482` 2026-07-28），另有未提交的持久化重构（`persistence_svc.py` 等）。存在标签 `v1.1.0`、`v1.1.1`、`v2.0.0-beta`。

> 版本元数据欠维护：`config.server_version="2.0.0"`，但 `pyproject.toml` 仍写 `version="1.0.0"`；README「137+ 测试」等口径早于当前 190 项测试。

---

## 12. 关键技术决策与已否决方案

| 决策点 | 选择 | 核心理由 |
|---|---|---|
| 集成协议 | MCP stdio | 一次编写处处运行；纯本地、不暴露端口 |
| 向量库 | LanceDB | 嵌入式零运维（向量版 SQLite）、列式元数据过滤 + FTS、MVCC |
| 框架 | 原生 SDK，不用 LangChain/LangGraph | 线性 CRUD + 检索，框架只加抽象；BugVault 是工具端点不是推理引擎 |
| 嵌入 | fastembed ONNX 本地推理 | 零 API 费用、离线可用、CPU 可跑 |
| 重排 | Cross-Encoder（弃 ColBERT） | 5–20 候选场景 O(n) 够快；ColBERT 需 ~1.5GB 独立索引 |
| 融合 | RRF（弃 Score Fusion） | 量纲无关、对异常值鲁棒 |
| 分块 | 父子 Small-to-Big | 短块聚焦召回 + 父文档完整回捞 |
| 父表向量 | 零向量 | 唯一前门是 chunks，省 5000× embedding 成本 |
| 去重 | MD5 主键 + merge_insert | 天然 upsert，防知识库膨胀 |
| 异步写入 | 同步归档 + 后台异步向量化 | 不阻塞 Agent，可读副本先行 |
| 时间衰减 | 默认关闭 | 旧排障方案保质期长，不该被压低排名 |
| 评测 | 策略模式 + 双重降级 | 评估是增值，绝不阻塞检索 |
| 数据归档 | Markdown 双写 | 人可读、可 git 管理、可重建索引 |

已否决路径：LangChain/LangGraph、Chroma/FAISS、ColBERT、Score Fusion、Sentence Window Retrieval（当前数据量收益有限）、智能去重（parent 回捞天然去重）。完整论证见 [RFC/ADR 系列](refer/设计/)。

---

## 13. 质量验证与数据资产

### 13.1 测试资产（当前）

- `src/`：约 **5,252 行** Python；`tests/`：约 **3,939 行**；scripts + experiments：约 **3,347 行**。
- `pytest --collect-only`：**190 项测试**（2026-09-03 实测收集）。
- 测试文件覆盖：模型校验、检索模块（RRF/过滤/降级/阈值）、持久化模块、v2 规约服务、P0 关键路径、P1/P2 扩展、MCP 协议 e2e（标记 `e2e`）。
- 历史验证报告（口径标注）：2026-06-04 报告为「137 项 pytest + 76 项管道断言」，其中 e2e 因预存 Stack Overflow 样本干扰曾标记 1 项失败（非代码缺陷）；README 与文档中「137+」「96% 特性覆盖」均为**历史口径**，当前不要直接引用。

### 13.2 验证脚本

| 脚本 | 作用 |
|---|---|
| `scripts/test_chunk_pipeline.py` | 父子分块检索管道端到端断言（35 项，历史口径） |
| `scripts/test_full_pipeline.py` | 直连服务的全场景仿真（41 项，历史口径） |
| `experiments/benchmark_retrieval.py` | 离线检索三管线对比：纯向量 / Hybrid / Full Pipeline |
| `experiments/generate_test_data.py` | 构造离线评测数据 |
| `scripts/rebuild_index.py` | 从 Markdown 归档重建 LanceDB 索引（并发 batch） |
| `scripts/import_external.py` | 从 Parquet/CSV 等批量导入外部数据（如 Stack Overflow） |
| `scripts/migrate_v2.py` | 手动 v1→v2 schema 迁移 |

### 13.3 数据资产

- 仓库内有 `stackoverflow_posts.parquet`（约 38 MB）作为外部语料示例。
- v1.1.1 时期文档记录导入后 ~2100+ 父记录 / ~4200+ 子块（历史口径，实际数据以本地 `~/.bugvault` 为准）。

### 13.4 验证状态红线（口述与文档通用）

- 本文写作环境实测：核心逻辑套件（`test_retrieval_module.py` / `test_persistence_module.py` / `test_core.py`）49 项通过、1 项因沙箱对 `~/.bugvault` 只读而失败（原因是被测函数写默认数据目录，属测试隔离问题，非代码缺陷）；完整全量运行未在本文写作环境跑完。
- 只报有当天证据的数字；190 项是「收集数」，全绿需重跑确认。
- 涉及模型下载的测试（embedding/reranker）依赖本地模型缓存或网络，报告时应说明环境。
- 任何「降低 70%」「零事故」「96% 覆盖」等历史主张，必须带上分子、分母、样本、对照组与时间范围；说不清就不说。

---

## 14. 边界、风险与工程债

### 14.1 系统边界（当前如实状态）

1. **异步入库无完成回执**：进程退出可能丢后台任务；可后续加持久化队列 + 回执。
2. **RAG 评估默认关闭**：打开后调用外部 Judge LLM，非全链路零外部依赖。
3. **claim-level 配额是全局类变量**：不是按会话/用户隔离；准确表述为进程内全局配额。
4. **Cross-Encoder 是可选精排**：加载/推理失败自动降级为 RRF，不能承诺每次请求都经过精排。
5. **单用户本地 stdio**：无多租户、鉴权、分布式可靠性；团队共享需自行挂载数据目录。
6. **图叠加层目前是写侧投影**：写入时会建 Bug/Convention/TechStack/Project 节点与边，但检索链路尚未消费图遍历（ADR-002 的 Phase 3+ 未落地）。

### 14.2 工程债与观察项

- 无 CI 配置、无 lint/format 配置（仓库内未定义 ruff/black）。
- `tests/test_core.py::TestWriteMarkdownArchive` 写真实默认数据目录而非 tmp_path：测试隔离不彻底（沙箱只读环境会失败，本机可过）。
- 文档口径漂移：README 测试数（137+）、`pyproject` 版本（1.0.0 vs config 2.0.0）、`.env.example` 注释默认值、README 中 reranker 模型（旧默认 80MB vs 当前 1.1GB 多语言模型）均需统一。
- 历史分析文档个别措辞过时（例如把交付描述成 Web/FastAPI），引用时以代码为准。
- 部分特性文档分散在 `codex-docs/refer/` 与 `reasonix-doc/`，版本驱动演进，缺少「当前态」单一事实源——本文档即为该问题的第一步收敛。

### 14.3 show-me 图纸（链路 07–12）复核发现的文档—代码落差

2026-10-09 绘制 `docs/show-me-07..12-*.html` 时，以代码为准逐条复核出下列「文档说已做、代码没做」或口径不符项。图纸已在对应位置红标；此处回写为当前事实源。行号基于当前工作区，未运行测试 / 服务 / 模型。

1. **draft「补问话术 + 最多 3 轮」未接线**（曾写在 §7.1）。draft 实际只返回缺失字段清单（`mcp_tools/tools.py:484–493`）；`suggest_probe_questions` / `suggest_convention_probe_questions`（`services/ingestion_svc.py:21`、`:67`）与 `MAX_PROBE_ROUNDS` / `probe_round_exhausted` / `increment_probe`（`models/bug_record.py:77`、`:102`、`:105`）除定义处外无调用，`_probe_rounds` 随实例重置且不落库，Convention 无轮次概念。
2. **Archive 失败仍继续建立记忆**（与 `CONTEXT.md` «Record establishment» 不一致）。`_prepare` 把归档异常记为 non-fatal（`services/persistence_svc.py:152–156`）后照常返回完整记录，后台继续写向量；域模型要求「校验通过且 Archive 成功后才成为正式记忆」。
3. **Markdown 归档不幂等**。归档文件名带时间戳（`services/archive_svc.py:138`、`:225`），重复保存同一记录会在归档目录累积重复文件；与 §5.5 及事实卡「去重 / 防知识库膨胀」表述不符（upsert 只作用于 LanceDB 主键）。
4. **关闭异步开关时无同步兜底**。`enable_async_embedding=false` 时既不调度后台任务也不同步写 LanceDB，结果是「只归档、不索引」（`mcp_tools/tools.py:442–447`；默认 `True`，`config.py:47`）。
5. **MCP `inputSchema` 不参与服务端校验**。仓库仅 5 处 `inputSchema=` 赋值（`mcp_tools/tools.py:252`、`:264`、`:275`、`:284`、`:299`），无任何 JSON Schema 校验调用；实际拦截全在 Pydantic 层，报错文案是 Python 校验信息而非 schema 违规说明。
6. **exit 日志把失败、草稿、空结果记成成功**。`handle_call_tool` 正常 `return` 分支硬编码 `status="ok", error_code="ok"`（`mcp_tools/tools.py:378–382`），非法参数、draft、空检索都走该分支。
7. **`ErrorCode` 枚举值不可达**。`validation_error` / `not_found` / `quota_exceeded`（`models/error_code.py:26`、`:30`、`:31`）在 MCP 链路不会被 `_classify_error` 产出（`observability.py:217–236`）；claim_level 配额耗尽在评测层降级为 `simple (fallback_from_error)`（`services/rag_evaluator_svc.py:593–616`），不走错误码。
8. **traceId 不回传客户端**。`trace_id` 只进服务端日志与 `ai_call.jsonl`（`mcp_tools/tools.py:310`、`:322`；`observability.py:103`），MCP 返回内容不含 traceId，客户端无法凭返回关联日志。
9. **`retrieve_convention` 空结果复用 bug 文案**。返回 `"No matching bug experiences found in the knowledge base."`（`mcp_tools/tools.py:614`，bug 版见 `:548`）。
10. **反思工具未走模型校验、`PreventionRule` 未实例化**。`reflect_and_prevent_error` 手工判空（`mcp_tools/tools.py:792–800`）；`PreventionRule` 模型仅在 `models/reflection_rule.py:8` 定义，全仓库无实例化引用。
11. **`_classify_error` 为子串匹配**，`auth` / `content` 等关键词命中即归类（`observability.py:228–231`），普通报错含这些词会被误分类。
12. **线程池并发上限硬编码**。`thread_pool_workers: int = 2`（`config.py:40`），executor 固定 2 线程，高并发排队、不可水平扩展。
13. **`experiments/report.md` 与实测/自身上下文矛盾**。核心结论第 4 条「Full Pipeline 能有效返回空结果」与 No-Answer 表 0% 拒答率冲突（§13.4 已记 0%）；Full 管线在 `benchmark_retrieval.py:136` 有定义但报告结果表缺失；核心结论编号 1 / 3 / 4 缺 2。
14. **调研结论未收敛**。`docs/research/mem0-source-reading.md`、`zvec-openviking-reading-and-direction.md` 的结论已进 `README.md`，但 §12「已否决方案」未提 mem0 / zvec；按「已调研，未决策」处理。

---

## 15. 后续路线

按「先夯实闭环证据、再扩场景」排序：

1. 固定离线评测集与基准线，让检索改进可量化（已有 benchmark 骨架，补齐运行/报告自动化）。
2. 异步任务队列 + 完成回执，解决「返回成功 ≠ 已可检索」。
3. CI + lint + 测试隔离修复，把 190 项测试变成可重复的绿色信号。
4. 图检索消费（ADR-002 Phase 3）：同根因 Bug 关联、Bug→规约追溯。
5. 多会话/多用户与防投毒：规约版本化、来源溯源、过期清理。
6. 文档统一：README / docs / 本文件单向同步，消除口径漂移。

---

## 附录 A：面试口径速查

### 30 秒版

> 我给 AI 编程助手做了一个「项目记忆」：它把解决过的 Bug 经验和项目规约结构化存到本地，让 AI 每次开工前先查一遍。价值是：同样的错误只犯一次、项目规矩教一遍就永远遵守、数据全在本地不泄露代码。技术上我用语义检索 + 关键词检索双路召回、分块 + 重排序提高命中，写入先 Markdown 归档再异步建索引；核心取舍是只做记忆和检索这一件事，不重复造 Agent 推理引擎。

### 3 分钟骨架

1. **问题与边界**：跨会话经验断层；BugVault 是 MCP 工具端点，不替客户端规划。
2. **主链路**：检索六步（分块双路召回 → RRF → parent 归并 → IN 回捞 → 精排 → top-k）+ 保存四步（校验 → 归档同步 → 异步向量化 → 图投影）。
3. **难点与取舍**：单向量稀释报错 → 父子分块；语义/关键词互补 → RRF；精度与延迟 → Top-K 后 Cross-Encoder + 降级；评估 → 策略模式 + 双重降级。
4. **验证与边界**：190 项测试（收集口径）、离线 benchmark、管线脚本；主动说明异步无回执、评估默认关、全局配额、图只写未查。

### 追问防御要点

- 为什么不做 Skill/插件？→ MCP 是标准协议，一次编写处处运行。
- 为什么不做 Agent 框架？→ 客户端负责推理与决策，BugVault 做「记忆端点」，职责单一可降级。
- 检索为什么不直接整条记录一个向量？→ 长文档稀释报错特征；子块聚焦命中，父文档回捞保证完整。
- 为什么 RRF 不用分数相加？→ 余弦距离与 BM25 量纲不同；RRF 只用排名。
- 异步入库立即检索不到是不是 Bug？→ 是已知取舍：可读副本先行、索引最终一致；改进方向是任务队列与回执。
- 指标口径：只说有证据、有定义的数字（详见事实卡 `../resume/active/bugvault-project-fact-card.md`）。

---

## 附录 B：文档与源码地图

| 资料 | 内容 | 状态 |
|---|---|---|
| 本文件 | 当前态总纲 | 现行 |
| [README.zh.md](../README.zh.md) | 产品使用手册（面向用户） | 有少量过时口径，需随本文档校正 |
| [CONTEXT.md](../CONTEXT.md) | 领域模型定义（Bug/Convention/Retrieval/Persistence） | 现行 |
| [设计文档](refer/设计/) | v1.0→v1.1.1 架构、ADR、RFC | 历史决策依据，细节以代码为准 |
| [v2.0 文档](v2.0/) | 规约记忆规范与发布说明 | 现行（v2.0） |
| [测试报告](tests/) | v1.1.1 全链路验证 | 历史口径（2026-06） |
| [评审报告](judge/v1.1.1-review.md) | 技术评审（B+，4 项 P1，无 P0） | 历史 |
| [事实卡](../resume/active/bugvault-project-fact-card.md) | 面试可追溯事实与红线 | 现行草稿 |
| 源码 `src/bugvault/` | 唯一事实源 | 现行 |
