<div align="center">

# BugVault

**Bug Experience Vault & Intelligent Retrieval System**

*为 LLM 提供持久的跨会话排障记忆的本地优先 MCP 服务器。*

[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-2024--11--05-purple.svg)](https://modelcontextprotocol.io)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

[English](README.md) | [中文](README.zh.md) | [日本語](README.ja.md)

</div>

---

## 项目介绍

BugVault 是一个 **本地优先的 MCP 服务器** —— 作为 LLM（决策 Agent）的专属"记忆 Agent"，两者协同构成 **双 Agent 排障系统**。

- **决策 Agent**（Claude / 任何 LLM）：诊断 Bug、制定修复方案、决定保存和复盘的内容。
- **记忆 Agent**（BugVault）：提供语义检索、持久化解方案、评估 RAG 质量、写入预防规则。

所有数据 **100% 本地存储** — 无云端、无 API 费用、无数据泄露。

### Agent 自进化飞轮

```
 排障中 ──→ 解决后 ──→ 复盘反思 ──→ 永不再犯
  (检索)      (保存)      (复盘)
     ↑                            │
     └────── 知识库 ──────────────┘
            (LanceDB + .md + CLAUDE.md)
```

每一次闭环都让 Agent 变得更聪明——过去的解决方案可以被检索，预防规则防止同样的错误犯两次。

### v1.1.1 新增特性 — 父子文本块检索

- **🧩 分块向量索引** — 每条 Bug 记录不再生成 1 条长向量，而是生成 **2 条聚焦短向量**：
  `error_log` 块（精确报错匹配）+ `semantic` 块（标题 + 尝试方法 + 解决方案），存储在独立的 `bugvault_chunks` 表
- **🎯 精准召回** — 搜索具体堆栈时直接命中 `error_log` 块，不再被冗长的 `final_solution` 稀释
- **🔄 父文档映射** — Chunk 级 RRF 融合 → 按 `parent_id` 去重 → `fetch_records_by_ids()` 回查完整文档 → Cross-Encoder 精排
- **📦 双表架构** — `bug_records`（父元数据 + FTS） + `bugvault_chunks`（子向量 + 冗余 `tech_stack`/`project_name` 支持过滤下推）
- **🏗️ `rebuild_index.py`** — 每条源记录生成 1 条父记录 + 2 条子块
- **🔤 智能技术栈过滤** — `target_tech_stack="Java"` 不会误匹配 `"JavaScript"`，
  通过排除字典在保留 `LIKE` 版本后缀弹性（如 `"Python"` 仍匹配 `"Python 3.13"`）的同时
  消除跨技术栈误中。详情见 [P1 闭环证明](docs/tests/v1.1.1-test-report.md#8-v111-p1-问题闭环证明)。

### 三大核心工具

BugVault 暴露三个 MCP 工具，覆盖排障的完整生命周期，**每个工具职责专一**：

| 工具 | 职责 | 可选 |
|------|------|------|
| `retrieve_bug_experience` | 🛠️ 排障中 — 语义检索 + 精细重排 + RAG 质量评估 | 评估可选 |
| `save_bug_experience` | 💾 排障后 — Markdown 立即可读 + 后台异步向量入库 | 异步可选 |
| `reflect_and_prevent_error` | 🧠 复盘后 — 分类根因 + 写入 CLAUDE.md 预防规则 | ✅ 可选 |

### v1.1 新增特性

- **🎯 混合检索** — 密集向量 + FTS 全文搜索双路召回，RRF(k=60)融合，参见 [v1.1 架构文档](docs/refer/设计/04.v1.1-architecture.md)
- **⚡ Cross-Encoder 精排** — 轻量 ONNX 交叉编码器二次打分，参见 [ADR 选型记录](docs/refer/设计/adr-cross-encoder-vs-colbert.md)
- **🧪 Claim-Level 评估** — CoT 思维链提取声明 → 逐条验证，输出 `claims_analysis[]`，参见 [评估策略](docs/refer/设计/evaluation-strategy.md) 全文和 [架构文档](docs/refer/设计/04.v1.1-architecture.md#二评估链路策略模式--双重降级)
- **🛡️ 双重降级** — 配额熔断 + 异常捕获双重保护，LLM 解析崩溃不阻塞检索链
- **🔍 元数据预过滤** — `target_tech_stack` + `target_project_name`，大小写容错 + SQL 注入防护，参见 [元数据过滤设计](docs/refer/设计/metadata-filtering.md) 和 [架构文档](docs/refer/设计/04.v1.1-architecture.md#三元数据预过滤)
- **📊 Token 统计** — 每次评估返回 `prompt_tokens` / `completion_tokens` / `total_tokens`
- **🧹 数据库维护** — `drop_table()` + 并发 batch rebuild，65 条记录 0.6 秒完成
- **🔒 路径安全** — 全局 `.expanduser().resolve()` + `mkdir()` 前置创建

### v1.0 保留特性

- **语义检索** — 自然语言搜索历史 Bug
- **去重与 Upsert** — MD5 主键 + `merge_insert`，零重复
- **并发安全** — `threading.Lock` 保护异步读写
- **Agent 自进化** — 复盘工具写入 CLAUDE.md
- **纯本地** — 数据在 `~/.bugvault/`，无需网络
- **MCP 原生** — 兼容所有 MCP 客户端

---

## 快速开始

### 前置条件

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)（包管理器）

### 安装

```bash
git clone https://github.com/yourusername/bugvault.git
cd bugvault
uv sync

#（可选）配置 RAG 裁判 LLM
cp .env.example .env
# 编辑 .env — 设置 BUGVAULT_ENABLE_RAG_EVAL=true 和 BUGVAULT_EVAL_LLM_API_KEY

# 验证（70+ 测试）
uv run pytest -v

#（可选）从存档重建索引
uv run python scripts/rebuild_index.py --skip-clear
```

### 启动 MCP 服务

在 MCP 客户端中配置以下启动项（Claude Desktop / Claude Code / Cursor 均支持）：

```json
{
  "mcpServers": {
    "bugvault": {
      "command": "uv",
      "args": [
        "run",
        "--directory", "/path/to/bugvault",
        "python", "-m", "bugvault.main"
      ]
    }
  }
}
```

参见 [交付形式文档](docs/refer/分析/05.交付形式.md) 了解详细部署说明。

---

## 架构：双 Agent 协同

```
┌─────────────────────────────────────────────────────────────────┐
│                    决策 Agent (Claude)                           │
│                                                                  │
│  1. 用户报告 Bug                                                  │
│  2. Agent 调用 retrieve_bug_experience ←───────────────────┐    │
│     → 获取历史方案 + RAG 可信度分数                          │    │
│  3. Agent 诊断 + 修复 Bug                                    │    │
│  4. Agent 调用 save_bug_experience ─────────────────────────┘    │
│     → MD 立即归档 + 异步向量索引                               │    │
│  5. Agent 调用 reflect_and_prevent_error                        │    │
│     → 预防规则写入 CLAUDE.md                                    │    │
│  6. 下次会话：CLAUDE.md 自动加载 → Agent 永不再犯              │    │
└──────────────────┬────────────────────────────────────────────┘
                   │ JSON-RPC via stdio (MCP)
                   ▼
┌─────────────────────────────────────────────────────────────────┐
│                    记忆 Agent (BugVault)                         │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  三大职责专一的工具                                      │    │
│  │                                                         │    │
│  │  🛠️ 检索 ────  🧠 保存 ────  📝 复盘                  │    │
│  │  (独立 ANN   (MD 同步 +    (分类根因 +                  │    │
│  │   + 重排    异步向量)     写入 CLAUDE.md)               │    │
│  │   + RAG 评估)                                           │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │ LanceDB  │  │fastembed │  │ RAG LLM │  │ Archive  │       │
│  │ (向量库)  │  │ (ONNX)   │  │ (裁判)   │  │ (.md)    │       │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘       │
└─────────────────────────────────────────────────────────────────┘
```

### 核心边界

| 层 | 职责 | 从不做的事 |
|----|------|-----------|
| **决策 Agent**（Claude） | 诊断、修复、决定保存/复盘 | ❌ 直接操作数据库 |
| **记忆 Agent**（BugVault） | 检索、持久化、评估、写规则 | ❌ 修复 Bug 或做决策 |
| **RAG 评估** | 仅返回可信度数据 | ❌ 修改 Claude 的回复 |

---

## 三工具详解

### 🛠️ `retrieve_bug_experience` — 离线检索 + 独立评估

Agent 遇到 Bug 时（或用户主动询问），调用此工具。**全程在 BugVault 侧独立完成**，不与 Claude 复杂通信：

```
1. 查询 Embedding → 2. ANN 搜索 → 3. 混合重排 + 语义阈值 → 4. [可选] RAG 评估
```

**RAG 评估** 作为独立钩子运行。评估结果仅作为额外元数据返回，让 Claude 明确知道每条结果的可信度：

```
--- Result 1 ---
Title: Connection timeout fix
Solution: timeout=120
...
--- RAG Evaluation ---
Confidence: 8.5/10
Assessment: context_relevance=3.5, faithfulness=5.0, ...
```

### 💾 `save_bug_experience` — 双路径零阻塞保存

Agent 修复 Bug 后，保存**尝试路径** (`tried_methods`) 和**最终结果** (`final_solution`)：

| 路径 | 速度 | 完成内容 |
|------|------|---------|
| **SYNC**（executor 线程） | **毫秒级** | Pydantic 校验 → MD5 record_id → 写入 .md 归档 → "saved successfully" |
| **ASYNC**（fire-and-forget） | ~100ms | ONNX Embedding → LanceDB `merge_insert`（`record_id` 自动去重） |

### 🧠 `reflect_and_prevent_error` — Agent 自进化

复盘工具是 BugVault **越用越聪明**的核心。Agent 主动反思根因，分为以下类别：

| 分类 | 含义 | 示例 |
|------|------|------|
| `understanding_bias` | 客户隐式需求理解偏差 | "客户没明说环境变量已配置" |
| `code_logic_error` | 代码逻辑处理不当 | "忘了检查 .get() 返回 None" |
| `api_misuse` | API 使用错误 | "异步函数忘了 await" |
| `environment_issue` | 环境/配置问题 | "缺少系统依赖" |

预防规则写入 `CLAUDE.md` 的 `## Bug Prevention Rules` 章节。下次会话时，CLAUDE.md 作为 system prompt 自动加载，Agent **永不再犯同一错误**。

---

## 部署

### MCP 配置

```json
{
  "mcpServers": {
    "bugvault": {
      "command": "/path/to/uv",
      "args": [
        "run",
        "--directory", "/绝对路径/bugvault",
        "python", "-m", "bugvault.main"
      ]
    }
  }
}
```

> Claude Code: `~/.claude/settings.json` | Claude Desktop: `~/Library/Application Support/Claude/claude_desktop_config.json`

---

## 数据模型

### 🐞 `BugRecord` — 保存/检索的排障记录

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `bug_title` | `str` (1-256) | ✅ | 短标题 |
| `error_log_snippet` | `str` (1-32768) | ✅ | 错误消息或堆栈 |
| `tried_methods` | `str` (1-8192) | ✅ | 已尝试的方法 |
| `final_solution` | `str` (1-16384) | ✅ | 最终修复方案 |
| `project_name` | `str \| None` | ❌ | 项目名称 |
| `tech_stack` | `str \| None` | ❌ | 技术栈标签（如 "Python 3.13, Django"） |
| `root_cause` | `str \| None` | ❌ | 根因分析（≤4096 字符） |
| `record_id` | `str \| None` | 🛠️ 自动 | MD5(`bug_title` + `error_log_snippet`) — 去重键 |
| `create_time` | `str` | 🛠️ 自动 | ISO-8601 UTC 时间戳 |

### 📊 `RAGEvalResult` — 评估输出（所有字段可选）

| 字段 | 类型 | 范围 | 说明 |
|------|------|------|------|
| `strategy_used` | `str` | `simple` / `claim_level` / `simple (fallback_from_error)` | 实际执行的评估策略 |
| `rag_confidence_score` | `float \| None` | 0-10 | 综合：`faithfulness×5 + context_relevance` |
| `context_relevance` | `float \| None` | 0.0-5.0 | 检索文档对查询的相关程度 |
| `faithfulness` | `float \| None` | 0.0-5.0 (simple) / 0.0-1.0 (claim_level) | 被源文档支持的声明比率 |
| `evaluation` | `str \| None` | — | `justification` 的别名 |
| `justification` | `str \| None` | — | 扣分理由的严苛解释 |
| `claims_analysis` | `list[dict] \| None` | — | Claim 级：`[{claim, supported, reason}]` |
| `suggested_action` | `str \| None` | `CONFIDENT` / `PARTIAL` / `CAUTION` / `INSUFFICIENT` | 给 Agent 的结构化建议 |
| `prompt_tokens` | `int \| None` | — | 送往裁判 LLM 的 prompt token 数 |
| `completion_tokens` | `int \| None` | — | 裁判 LLM 返回的 completion token 数 |
| `total_tokens` | `int \| None` | — | 评估消耗的总 token 数 |

### 🛠️ 工具：`retrieve_bug_experience` — 请求参数

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `query` | `string` | ✅ | — | 错误消息、堆栈或 bug 描述 |
| `eval_depth` | `enum` | ❌ | `"simple"` | `"none"` / `"simple"` / `"claim_level"` |
| `target_tech_stack` | `string` | ❌ | — | 技术栈过滤（如 `"Python"`），大小写不敏感 |
| `target_project_name` | `string` | ❌ | — | 项目名过滤（如 `"order-svc"`），大小写不敏感 |

**返回值：** 格式化的文本块，包含：
1. `--- Retrieval Info ---` — 使用策略（hybrid / vector-only）+ 来源统计
2. `--- Result N ---` — 每条检索到的排障记录（标题、项目、错误、尝试、方案、根因）
3. `--- RAG Evaluation ---` — 置信度分数、Token 用量、声明分析（当 `eval_depth != "none"` 时）

### 💾 工具：`save_bug_experience` — 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `bug_title` | `string` | ✅ | 短标题 |
| `error_log_snippet` | `string` | ✅ | 错误消息或堆栈 |
| `tried_methods` | `string` | ✅ | 已尝试的方法 |
| `final_solution` | `string` | ✅ | 最终修复方案 |
| `project_name` | `string` | ❌ | 项目名称（可选） |
| `tech_stack` | `string` | ❌ | 技术栈标签（可选） |
| `root_cause` | `string` | ❌ | 根因分析（可选） |

### 📝 工具：`reflect_and_prevent_error` — 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `reflection_text` | `string` | ✅ | Bug 原因详细分析 |
| `error_category` | `enum` | ✅ | `understanding_bias` / `code_logic_error` / `api_misuse` / `environment_issue` / `other` |
| `preventive_rule` | `string` | ✅ | 防止复发的可执行规则 |

---

### 关键配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `BUGVAULT_DATA_ROOT` | `~/.bugvault` | LanceDB + 归档根目录 |
| `BUGVAULT_ENABLE_RAG_EVAL` | `false` | 启用 LLM 裁判评估 |
| `BUGVAULT_EVAL_LLM_API_KEY` | `""` | 裁判 LLM API 密钥 |
| `BUGVAULT_EVAL_LLM_MODEL` | `gpt-4o-mini` | 裁判模型名 |
| `BUGVAULT_EVAL_LLM_BASE_URL` | `https://api.openai.com/v1` | 自定义 API 端点（兼容 OpenAI） |
| `BUGVAULT_TOP_K` | `5` | 最大检索结果数 |
| `BUGVAULT_ENABLE_FTS` | `true` | 启用全文搜索双路召回 |
| `BUGVAULT_ENABLE_RERANKER` | `true` | 启用 Cross-Encoder 精排 |
| `BUGVAULT_RERANKER_MODEL` | `Xenova/ms-marco-MiniLM-L-6-v2` | Cross-Encoder 模型名 |
| `BUGVAULT_ENABLE_RECENCY_DECAY` | `false` | 时间衰减（默认关闭，旧 bug 同样权重） |
| `BUGVAULT_MAX_CLAIM_EVALS_PER_SESSION` | `10` | Claim-level 熔断上限 |
| `BUGVAULT_ENABLE_REFLECTION_TOOL` | `true` | 启用复盘工具 |
| `BUGVAULT_THREAD_POOL_WORKERS` | `2` | 异步 I/O 线程数 |

完整列表参见 [.env.example](.env.example)（20+ 项）。

---

## 开发

```bash
uv run pytest -v                                    # 全部 137 个测试
uv run pytest tests/test_core.py -v                 # 单元测试
uv run pytest tests/test_v2_services.py -v          # 复盘 + RAG 评估
uv run pytest tests/test_integration.py -v          # 集成测试（~15s）
```

---

## 技术栈选型与设计决策

| 决策 | 理由 | 参考文档 |
|------|------|----------|
| **为什么用 MCP 而非 Skill/插件？** | "一次编写，处处运行"——所有 MCP 客户端开箱即用。纯本地 stdio 通信，不暴露端口，不依赖网络。 | [为什么不做 skill](docs/refer/分析/02.为什么不做成skill.md) |
| **为什么用 LanceDB 而非 Chroma/FAISS？** | 零运维嵌入式数据库（向量界的 SQLite），进程内嵌无需 Docker。MVCC 无锁并发读写。列式存储原生支持元数据过滤 + FTS。 | [为什么选择 LanceDB](docs/refer/分析/03.为什么选择LanceDB.md) |
| **为什么不用 LangChain/LangGraph？** | 线性 CRUD + 向量搜索——框架在这里只会增加抽象层。MCP 不是 Agent 框架；BugVault 是工具端点，不是推理引擎。 | [为什么选择 SDK](docs/refer/分析/04.为什么选择SDK.md) |
| **为什么用 fastembed ONNX 而非 OpenAI 嵌入？** | 本地推理，零 API 费用，离线可用。ONNX 纯 CPU 运行，无需 GPU。 | — |
| **为什么用 Cross-Encoder 而非 ColBERT？** | ColBERT 需要独立 PyTorch 索引(~1.5GB)。对于 20 条候选的重排场景，Cross-Encoder ONNX(80MB) 精度更高、依赖更少。 | [ADR 选型记录](docs/refer/设计/adr-cross-encoder-vs-colbert.md) |
| **为什么 claim_level 需要双重降级？** | 小模型（如 deepseek-v4-flash）在复杂 CoT 提示词下频繁产出残缺 JSON。配额 + 异常双重降级保证评估链路崩溃不影响检索主线程。 | [v1.1 架构](docs/refer/设计/04.v1.1-architecture.md#二评估链路策略模式--双重降级) |
| **为什么做元数据预过滤？** | 纯语义搜索会把 Python 的 ModuleNotFoundError 和 Java 的 ClassNotFoundException 混淆。列式过滤在向量计算前缩小候选集，成本可忽略。 | [v1.1 架构](docs/refer/设计/04.v1.1-architecture.md#三元数据预过滤) |
| **为什么 RRF 用排名而非分数？** | 向量距离和 BM25 分数的量纲不同，直接相加毫无意义。RRF 只依赖排名位置(k=60)，量纲无关。 | [v1.1 架构](docs/refer/设计/04.v1.1-architecture.md#1.2-rrf-融合) |
| **为什么做父子文本块切分（v1.1.1）？** | 单条长向量让 `error_log_snippet` 被 `final_solution` 稀释。切分为 2 条聚焦短向量—`error_log` 块精确匹配报错特征、`semantic` 块匹配问题语义—chunk 级 RRF 融合 + `parent_id` 归并成完整文档。 | [v1.1.1 设计文档](docs/refer/设计/) |
|------|------|
| **为什么用 `threading.Lock`？** | LanceDB 的 Python `_table` 在并发时不保证可见性，不加锁 `search()` 会读到旧版本 |
| **为什么用 `mode='overwrite'`？** | `drop_table + create_table` 残留旧版本引用导致 "file not found"，`overwrite` 原子替换 |
| **为什么强制 `response_format=json_object`？** | 不强制的话 LLM 用 markdown fence 包裹 JSON 导致解析崩溃 |
| **为什么语义阈值 0.55？** | 对应 ANN 距离 ~0.90，经验上低于此值 == 完全无关 |
| **为什么三轴 RAGAS？** | 单一分数把"检索不准"和"模型编造"混为一谈，三轴让 Claude 区别对待 |

---

## 常见问题

| 问题 | 解决方案 |
|------|----------|
| Embedding 模型在代理后下载失败 | `unset all_proxy ALL_PROXY`；缓存于 `~/.cache/fastembed/` |
| Claude Code 不显示工具 | 检查配置绝对路径；`uv run python -m bugvault.main` 可启动吗？ |
| LanceDB 报 "file not found" | `rm -rf ~/.bugvault/lancedb` 重启（v3 已用 `overwrite` 修复） |

---

## 许可证

MIT
