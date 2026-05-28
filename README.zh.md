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

BugVault 是一个 **本地优先的 MCP（Model Context Protocol）服务器**，为 Claude 及其他兼容 MCP 的 LLM 客户端提供持久的、跨会话的 Bug 排障记忆。

**痛点：** 每次用 LLM 排查 Bug 都是从零开始。同一个问题几天后再次出现，LLM 完全不记得之前的修复方案。你辛苦调试积累的经验白白流失。

**BugVault 的解决方案：** 作为 LLM 的专属"Bug 大脑"，通过 `save_bug_experience` 自动保存已解决的 Bug，通过 `retrieve_bug_experience` 检索相关的历史解决方案。所有数据 **100% 本地存储** — 无云端、无 API 费用、无数据泄露。

### 核心功能

- **语义检索** — 用自然语言描述 Bug，而非关键词匹配
- **自动持久化** — 仅需 4 个必填字段，零手工操作保存排障记录
- **智能截断** — 堆栈追踪自动裁剪，保留关键信息的同时节省 Token
- **时间衰减重排** — 近期解决方案权重更高，过时方案自动降权
- **纯本地运行** — 数据存储在 `~/.bugvault/`，无需网络和服务端
- **MCP 原生** — 兼容所有 MCP 客户端：Claude Desktop、Claude Code、Cursor、Cline、Windsurf 等

---

## 快速开始

### 前置条件

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)（包管理器）

### 安装

```bash
# 克隆仓库
git clone https://github.com/yourusername/bugvault.git
cd bugvault

# 安装依赖（无需 GPU）
uv sync

# 运行单元测试验证安装
uv run pytest tests/test_core.py -v
```

### 暴露的 MCP 工具

配置完成后，Claude 将获得两个额外工具：

| 工具 | 描述 | 必填字段 |
|------|------|----------|
| `retrieve_bug_experience` | 通过错误描述搜索历史 Bug 解决方案 | `query` |
| `save_bug_experience` | 将已解决的 Bug 存入知识库 | `bug_title`, `error_log_snippet`, `tried_methods`, `final_solution` |

---

## 系统架构

```
┌──────────────────────────────────────────────────────┐
│            MCP 客户端 (Claude Code / Desktop)          │
└───────────────────────┬──────────────────────────────┘
                        │ JSON-RPC via stdio
┌───────────────────────▼──────────────────────────────┐
│                  BugVault MCP 服务器                    │
│                                                       │
│  ┌─────────────────────────────────────────────────┐  │
│  │  mcp_tools/  (门面层)                            │  │
│  │  ┌───────────────────┐ ┌───────────────────┐   │  │
│  │  │  retrieve_bug_    │ │  save_bug_        │   │  │
│  │  │  experience       │ │  experience       │   │  │
│  │  └────────┬──────────┘ └────────┬──────────┘   │  │
│  └───────────┼──────────────────────┼──────────────┘  │
│              │                      │                 │
│  ┌───────────▼──────────────────────▼──────────────┐  │
│  │  services/  (业务逻辑层)                         │  │
│  │  ┌──────────────────────┐ ┌──────────────────┐  │  │
│  │  │  RetrievalService    │ │ IngestionService │  │  │
│  │  │  · ANN 向量搜索      │ │ · 字段校验       │  │  │
│  │  │  · 时间衰减重排      │ │ · 追问机制       │  │  │
│  │  │  · 堆栈截断          │ │ · Markdown 归档  │  │  │
│  │  └──────────┬───────────┘ └────────┬─────────┘  │  │
│  └─────────────┼──────────────────────┼────────────┘  │
│                │                      │               │
│  ┌─────────────▼──────────────────────▼────────────┐  │
│  │  database/  (持久层)                             │  │
│  │  ┌──────────────────┐  ┌────────────────────┐   │  │
│  │  │ LanceDB          │  │ Markdown 归档      │   │  │
│  │  │ (向量 + 元数据)   │  │ (人类可读备份)     │   │  │
│  │  └──────────────────┘  └────────────────────┘   │  │
│  └─────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────┘
```

### 技术栈

| 组件 | 选型 | 理由 |
|------|------|------|
| **MCP 传输** | 官方 Python `mcp` SDK，`stdio` 模式 | 无 HTTP 服务、无端口、纯子进程 |
| **向量数据库** | [LanceDB](https://lancedb.github.io/lancedb/) | 零依赖嵌入式、MVCC 无锁并发、Arrow 原生 |
| **Embedding** | [fastembed](https://github.com/qdrant/fastembed) (`BAAI/bge-small-zh-v1.5`) | 轻量级 ONNX Runtime，无需 PyTorch/CUDA |
| **数据校验** | Pydantic v2 | 编译时类型安全、高性能验证器 |
| **配置** | Pydantic Settings | `.env` / 环境变量加载 |
| **运行环境** | Python 3.13+ | 现代异步支持、更好的错误信息 |

---

## 使用方式

### 配置 Claude Desktop

在 `claude_desktop_config.json` 中添加：

```json
{
  "mcpServers": {
    "bugvault": {
      "command": "/path/to/uv",
      "args": [
        "run",
        "--directory", "/path/to/bugvault",
        "python", "-m", "bugvault.main"
      ]
    }
  }
}
```

### 手动测试

```bash
# 直接启动服务器
uv run python -m bugvault.main

# 运行端到端协议测试（自动启动子进程）
uv run python tests/test_mcp_protocol.py
```

---

## 项目结构

```
bugvault/
├── pyproject.toml               # 项目配置与依赖
├── .env.example                 # 环境变量模板
├── README.md
├── src/
│   └── bugvault/
│       ├── main.py              # MCP 服务器入口
│       ├── config.py            # Pydantic 配置（环境变量）
│       ├── models/
│       │   └── bug_record.py    # BugRecord 数据模型
│       ├── services/
│       │   ├── retrieval_svc.py # ANN 搜索 + 重排 + 截断
│       │   └── ingestion_svc.py # 校验 + 追问 + MD 归档
│       ├── database/            # LanceDB 客户端
│       ├── mcp_tools/           # 工具定义（门面层）
│       └── utils/
│           ├── stdout_guard.py  # MCP stdout 防污染
│           ├── logger.py        # stderr 专用日志
│           └── text_utils.py    # 堆栈截断算法
└── tests/
    ├── test_core.py             # 15 个单元测试
    ├── test_mcp_protocol.py     # E2E 协议测试
    └── test_integration.py      # 保存→检索集成测试
```

---

## 数据模型

```python
class BugRecord(BaseModel):
    # ── 必填字段 ──
    bug_title: str              # 简短描述
    error_log_snippet: str      # 错误信息 / 堆栈
    tried_methods: str          # 已尝试的方法（包括失败的）
    final_solution: str         # 最终修复方案

    # ── 可选字段（支持异步补全）──
    project_name: str | None
    tech_stack: str | None
    root_cause: str | None

    # ── 系统管理 ──
    create_time: str            # ISO-8601 时间戳（自动生成）
```

---

## 开发指南

### 运行测试

```bash
# 单元测试（快速，无需外部依赖）
uv run pytest tests/test_core.py -v

# E2E 协议测试（启动真实子进程，约 15 秒）
uv run python tests/test_mcp_protocol.py

# 集成测试（保存→检索往返）
uv run pytest tests/test_integration.py -v -s

# 所有测试
uv run pytest tests/ -v
```

### 配置选项

通过环境变量（前缀 `BUGVAULT_`）或 `.env` 文件配置：

```bash
BUGVAULT_EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
BUGVAULT_TOP_K=5
BUGVAULT_RECENCY_WEIGHT=0.3
BUGVAULT_RECENCY_HALF_LIFE_DAYS=90
BUGVAULT_THREAD_POOL_WORKERS=2
```

完整配置项见 [.env.example](.env.example)。

---

## 设计决策

- **为什么不用 LangChain？** BugVault 的业务逻辑是线性 CRUD + 向量搜索，引入框架只会增加无谓的抽象层。原生 MCP SDK 保持堆栈浅且易于调试。
- **为什么不用 FastAPI？** MCP 的 `stdio` 模式通过 stdin/stdout 通信，而非 HTTP。FastAPI 只在 SSE（HTTP）传输下有意义，会引入端口管理和额外的依赖负担。
- **为什么用 fastembed 代替 sentence-transformers？** `pip install sentence-transformers` 会拉取 PyTorch + NVIDIA CUDA 库（约 2.5 GB），即使在纯 CPU 机器上也是如此。fastembed 只使用纯 ONNX Runtime（约 30 MB）——无需 GPU。
- **为什么不用 Content-Length 帧格式？** MCP Python SDK 的 `stdio_server()` 使用换行符分隔的 JSON（每行一个 JSON 对象），而非规范中描述的 Content-Length 帧格式。

---

## 常见问题

| 问题 | 解决方案 |
|------|----------|
| Embedding 模型在代理后下载失败 | `unset all_proxy ALL_PROXY`（fastembed 使用直连 HTTP） |
| E2E 测试超时 | 首次运行需下载模型（约 1 分钟）；后续运行约 15 秒 |
| 启动服务器无输出 | 日志输出到 stderr — 使用 `uv run python -m bugvault.main 2>&1` |

---

## 路线图

- **v1.0（MVP）** — 核心 MCP 服务器 + save/retrieve + LanceDB + embedding
- **v1.1** — 时间衰减重排、字段级追问、.md 文件批量导入
- **v1.2** — 知识图谱可视化、VSCode/Cursor 扩展

---

## 许可证

MIT
