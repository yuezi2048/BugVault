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

### 三大核心工具

BugVault 暴露三个 MCP 工具，覆盖排障的完整生命周期，**每个工具职责专一**：

| 工具 | 职责 | 可选 |
|------|------|------|
| `retrieve_bug_experience` | 🛠️ 排障中 — 语义检索 + 精细重排 + RAG 质量评估 | 评估可选 |
| `save_bug_experience` | 💾 排障后 — Markdown 立即可读 + 后台异步向量入库 | 异步可选 |
| `reflect_and_prevent_error` | 🧠 复盘后 — 分类根因 + 写入 CLAUDE.md 预防规则 | ✅ 可选 |

### 关键特性

- **语义检索** — 用自然语言而非关键词搜索历史 Bug
- **去重与 Upsert** — MD5 哈希主键 (`record_id`) + `merge_insert`，零重复记录
- **并发安全** — `threading.Lock` 保护异步读写竞争
- **相关性底线** — `MIN_SEMANTIC_SCORE=0.55` 丢弃无关文档（"宁缺毋滥"）
- **可选 RAG 评估** — 三轴 LLM 裁判：`context_relevance`(0–5) + `faithfulness`(0–5) + 严苛扣分理由
- **Agent 自进化** — 复盘工具写入 CLAUDE.md，下次会话自动加载，永不重复犯错
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
uv run pytest -v  # 全部 43 个测试通过
```

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

## 数据模型

```python
class BugRecord(BaseModel):
    # ── 必填字段 ──
    bug_title: str              # 简短描述
    error_log_snippet: str      # 错误信息 / 堆栈
    tried_methods: str          # 尝试路径（含失败）
    final_solution: str         # 最终修复方案

    # ── 可选字段 ──
    project_name: str | None
    tech_stack: str | None
    root_cause: str | None

    # ── 系统管理 ──
    record_id: str | None       # MD5(bug_title + error_log_snippet) — 自动计算
    create_time: str            # ISO-8601 UTC 时间戳（自动生成）
```

**record_id 自动计算**：
```python
@model_validator(mode="after")
def _compute_record_id(self) -> "BugRecord":
    import hashlib
    raw = (self.bug_title + self.error_log_snippet).encode("utf-8")
    self.record_id = hashlib.md5(raw).hexdigest()
    return self
```

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

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `BUGVAULT_EMBEDDING_MODEL` | `BAAI/bge-small-zh-v1.5` | Embedding 模型（中英双语） |
| `BUGVAULT_TOP_K` | `5` | 最大检索结果数 |
| `BUGVAULT_ENABLE_RAG_EVAL` | `false` | 启用 LLM 裁判评估 |
| `BUGVAULT_EVAL_LLM_API_KEY` | `""` | 裁判 LLM API 密钥 |
| `BUGVAULT_EVAL_LLM_MODEL` | `gpt-4o-mini` | 裁判模型名 |
| `BUGVAULT_ENABLE_REFLECTION_TOOL` | `true` | 启用复盘工具 |
| `BUGVAULT_THREAD_POOL_WORKERS` | `2` | 异步 I/O 线程数 |

---

## 开发

```bash
uv run pytest -v                                    # 全部 43 个测试
uv run pytest tests/test_core.py -v                 # 单元测试
uv run pytest tests/test_v2_services.py -v          # 复盘 + RAG 评估
uv run pytest tests/test_integration.py -v          # 集成测试（~15s）
```

---

## 设计决策

| 决策 | 理由 |
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
