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
│  │  │ LanceDBClient    │  │ Markdown 归档      │   │  │
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

### 部署为 MCP 服务器

BugVault 通过 MCP 的 **stdio 传输** 工作——它是作为 MCP 客户端的子进程运行的。无需启动 HTTP 服务器，无需配置端口。

### 配置文件

#### 文件位置

MCP 服务器配置是一个 JSON 文件，位置取决于客户端：

| 客户端 | 配置文件路径 |
|--------|-------------|
| **Claude Code（CLI）** | `~/.claude/settings.json` |
| **Claude Desktop** | **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`<br>**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`<br>**Linux:** `~/.config/Claude/claude_desktop_config.json` |

#### 配置内容

将 BugVault 添加到 `mcpServers`：

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

> **重要：** 必须使用 **绝对路径** 配置 `uv` 路径和项目目录。不要使用 `~` 或相对路径。
>
> 💡 运行 `which uv`（macOS/Linux）或 `where uv`（Windows）查找 `uv` 的完整路径。

### 使用 `/mcp` 命令（Claude Code）

编辑 `~/.claude/settings.json` 后，**完全重启** Claude Code（不只是 `/mcp` — 关闭并重新打开终端即可）。然后输入：

```
/mcp
```

该命令列出所有配置的 MCP 服务器，每个有以下三种状态之一：

| 状态 | 含义 |
|------|------|
| **running** ✅ | 服务器已激活并就绪 |
| **not running** ⏸️ | 正常 — BugVault 使用**懒加载**（见下文） |
| **error** ❌ | 服务器启动失败 — 路径可能配置有误 |

> **懒加载：** BugVault 仅在你首次调用其工具（`save_bug_experience` 或 `retrieve_bug_experience`）时才会启动。显示 "not running" 是预期行为。首次工具调用后，`/mcp` 会显示 "running"。
>
> **首次调用别慌：** 首次冷启动需要 **3~5 秒**（下载/加载 Embedding 模型 + 连接 LanceDB）。这完全正常——后续调用是瞬时的。

如果状态显示 **"error"**，最常见的原因是路径有误。请逐一检查：
- `which uv` 给出的路径是否绝对路径
- `--directory` 参数是否指向 BugVault 项目根目录（包含 `pyproject.toml` 的目录）
- 是否使用了 `~` 或 `$HOME` — 请展开为完整路径

> **注意：** `/mcp stop`、`/mcp restart` 等子命令并非在所有版本的 Claude Code 中都可用。如果它们不起作用，只需重启终端或 Claude Desktop 即可。

### 首次使用注意事项

1. **必须重启** — Claude Code 和 Claude Desktop 仅在启动时读取配置文件。编辑 `settings.json` 后，需要关闭并重新打开。
2. **首次工具调用较慢（约 3~5 秒）** — Embedding 模型（90 MB）在首次使用时下载（如果未缓存）。服务器将日志输出到 stderr，在 Claude Code 中不可见，但手动运行时可见。
3. **代理用户：** 如果处于企业 VPN/代理环境下，首次调用可能失败：
   ```bash
   # 先取消代理下载模型
   unset all_proxy ALL_PROXY
   uv run python -m bugvault.main  # 触发下载
   ```
   模型缓存到 `~/.cache/fastembed/` 后，重新启用代理即可。
4. **语言不影响使用：** 即使你使用英文版 Claude，存储中文 Bug 记录也完全 OK——Embedding 模型（`BAAI/bge-small-zh-v1.5`）是中英双语的。直接用自然语言描述即可。

### 验证部署

重启 MCP 客户端后，逐步尝试以下操作来确认一切正常：

**1. 保存一条测试记录：**
> "帮我保存一条测试 Bug 记录：标题是 'test deployment'，报错是 'ConnectionError: timeout'，尝试过重启服务，最终方案是增加超时时间"

**2. 检索它：**
> "我遇到过 connection timeout 的问题，帮我查一下 BugVault 里的历史记录"

如果部署成功，Claude 会调用 MCP 工具并返回结果。

**如果 Claude 说"我没有这个工具"**：
- 先用 `/mcp` 检查状态（Claude Code）
- 重新检查配置文件中的路径
- 试试下面的手动测试

### 手动测试

```bash
# 直接启动服务器（合并 stdout/stderr 以便调试）
uv run python -m bugvault.main 2>&1

# 运行单元测试
uv run pytest tests/test_core.py -v

# 运行集成测试（自动启动子进程）
uv run pytest tests/test_integration.py -v -m e2e
```

---

## 部署排错指南

### 常见错误及解决方案

#### 1. 连接断开/进程崩溃

```
[MCP 错误] CONNECTION_CLOSED 或 Connection closed
```

**原因：** 服务端进程启动时崩溃——通常是 Embedding 模型加载或 LanceDB 初始化期间出错。

**诊断：**
```bash
# 手动启动服务器，观察错误
uv run python -m bugvault.main 2>&1
```

**解决方案：**
- 确保 `uv sync` 执行成功
- 检查 Python 版本：`python --version`（需要 3.13+）
- 首次运行需联网下载模型（fastembed 下载 `BAAI/bge-small-zh-v1.5`）
- 如果在代理后面：`unset all_proxy ALL_PROXY`

#### 2. 表 / 数据库已存在

```
ValueError: Table 'bug_records' already exists
```

**原因：** 多次运行未清理；LanceDB 表已经从前一次会话创建。

**解决方案：** 最新代码已修复此问题，会自动打开已有表。如需重置：
```bash
rm -rf ~/.bugvault/lancedb/bug_records*
```

#### 3. 服务器启动但工具不在 Claude Code 中显示

**原因：** Claude Code 只有在服务器成功响应 `initialize` 握手后才发现工具。如果握手前崩溃，则无工具注册。

**诊断：**
- 运行 `/mcp` 查看已注册的 MCP 服务器
- 如果 BugVault 显示 "error" 或 "not running"，检查日志：`cat ~/.claude/logs/*.log`
- 手动确认服务器能正常启动：`uv run python -m bugvault.main 2>&1 | head -20`

**常见原因：**
- **`uv` 路径错误：** 使用 `which uv` 找到绝对路径
- **项目路径是相对路径：** `--directory` 参数必须是绝对路径
- **工作目录不对：** 运行目录需要是 BugVault 项目根目录

#### 4. Embedding 模型下载失败

```
ConnectionError: HTTPSConnectionPool ... Name or service not known
```

**解决方案：**
- 首次下载需要联网（约 90 MB 模型文件）
- 可设置 `BUGVAULT_EMBEDDING_MODEL` 更换模型
- 缓存位置：`~/.cache/fastembed/` — 下载后离线可用
- 代理环境：首次下载时取消代理，下载后重新设置

#### 5. 导入错误

```
ImportError: cannot import name '...' from 'bugvault...'
```

**解决方案：** 确保正确设置了 Python 路径：
```bash
cd /绝对路径/bugvault
PYTHONPATH=src uv run python -m bugvault.main
```

#### 6. LanceDB / PyArrow 版本不兼容

```
ValueError: The LanceDB table has not been created with the same schema
```

**解决方案：** 开发过程中如果 schema 发生变化，删除旧数据重建：
```bash
rm -rf ~/.bugvault/lancedb
uv run pytest tests/test_integration.py -v -m e2e  # 重建表
```

### 排查清单

```
□ uv sync 无错误完成
□ Python 3.13+ 已激活 (python --version)
□ uv 路径为绝对路径 (which uv)
───
□ ~/.claude/settings.json 使用绝对路径
□ --directory 指向包含 pyproject.toml 的项目根目录
───
□ 首次下载模型时网络可访问
□ ~/.bugvault/lancedb 目录可写
───
□ uv run python -m bugvault.main  启动无错误
□ uv run pytest tests/ -v         所有测试通过
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
│       ├── main.py              # MCP 服务器入口（约 70 行）
│       ├── config.py            # Pydantic 配置（环境变量）
│       ├── models/
│       │   └── bug_record.py    # BugRecord 数据模型
│       ├── services/
│       │   ├── retrieval_svc.py # ANN 搜索 + 重排 + 截断
│       │   └── ingestion_svc.py # 校验 + 追问 + MD 归档
│       ├── database/
│       │   └── lancedb_client.py# LanceDBClient 面向对象数据访问层
│       ├── mcp_tools/
│       │   └── tools.py         # MCP 工具注册 + 处理器
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
uv run pytest tests/test_integration.py -v -m e2e

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

## MCP Stdio 传输原理

BugVault 使用 **stdio 传输**——最简单的 MCP 通信模式：

```
┌─────────────────────┐          JSON-RPC 2.0          ┌─────────────────────┐
│   MCP 客户端        │  ──────────────────────────►   │   BugVault 服务器   │
│  (Claude Code /     │  stdin（写入服务器）            │  (uv run python     │
│   Claude Desktop)   │  ◄──────────────────────────   │   -m bugvault.main) │
│                     │  stdout（读取服务器）            │                     │
└─────────────────────┘                                └─────────────────────┘
                                                              │ stderr（日志）
                                                              ▼
                                                        终端 / 日志文件
```

关键点：
- MCP 客户端通过 `uv run python -m bugvault.main` **启动** BugVault 作为子进程
- 客户端向服务器的 **stdin** 写入 JSON-RPC 请求
- 服务器向 **stdout**（客户端读取）写入 JSON-RPC 响应
- **stderr 用于日志** — 终端可见，但 MCP 协议忽略
- `_MCPStdoutProxy` 保护机制防止意外的 `print()` 调用污染协议流

这就是为什么 `uv run python -m bugvault.main 2>&1` 只显示日志输出而不显示 JSON-RPC 流量——JSON 发送到 stdout，但只有在客户端向 stdin 写入请求时才有意义。

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
| Claude Code 不显示工具 | 检查 `~/.claude/settings.json` 中的绝对路径配置 |
| "Connection closed" 错误 | 服务器初始化崩溃 — 手动 `2>&1` 查看完整报错 |
| 表结构更新后 schema 冲突 | `rm -rf ~/.bugvault/lancedb` 然后重启 |

---

## 路线图

- **v1.0（MVP）** — 核心 MCP 服务器 + save/retrieve + LanceDB + embedding
- **v1.1** — 时间衰减重排、字段级追问、.md 文件批量导入
- **v1.2** — 知识图谱可视化、VSCode/Cursor 扩展

---

## 许可证

MIT