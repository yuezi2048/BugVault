# Agent 记忆 / 检索方案调研与 BugVault 结论

> 面向关注 BugVault 的读者：本文说明项目为什么停在"产品验证完成"，以及后续该读什么、该用什么。
>
> 证据基线：`alibaba/zvec` @ `13fd088`、`volcengine/OpenViking` @ `7651155`、`mem0` @ `b7ad69a`，
> 阅读日期 2026-10。规则：能指到来源的写「事实」，推断写「判断」。

---

## 0. 结论（一句话）

**BugVault 作为独立 / 通用记忆产品不成立，产品化已冻结；它作为"如何验证并否证一个产品假设"的案例保留。**
决策与证据见 [ADR-0001](../adr/0001-stop-bugvault-product-validation.md)。

四条理由（判断）：

- 通用记忆组件（mem0 / Zep / Letta / LangMem）已覆盖持久化、检索、过滤与记忆生命周期。
- 上下文平台（OpenViking）已覆盖"文件系统式资产 + 目录范围检索 + 会话钩子"，并用
  **异步记忆抽取 + 预算化注入**化解了 ADR-0001 假设的"热路径成本"。
- 检索引擎（zvec 等）把 向量 / FTS / hybrid 做成进程内基础设施，检索内核不再构成壁垒。
- 真正的缺口不在"存记忆"，而在**度量记忆是否改变了行为**——那需要实验，不是一个新存储能证明的。

因此本仓库保留为工程与判断力案例，而不是一条产品路线图。以下为后续阅读。

---

## 1. zvec 能力速览（存储 / 检索引擎）

- **是什么**：阿里巴巴开源的**进程内（in-process）向量数据库**，纯本地、无服务端，已在阿里内部生产验证。
- **能力（事实）**：dense + sparse 向量、多向量查询；原生 FTS（含面向代码/短语的 N-gram 分词）；
  单查询内 hybrid（向量 + FTS + 标量过滤）；WAL 持久化；多进程并发读、单进程独占写；
  C / C++ / Python / Node / Go / Rust / Dart SDK。
- **生态**：`zvec-grep`（本地工作区搜索 CLI，统一 ripgrep + BM25 + 向量）、`Zvec Studio`；
  被 Agent 记忆套件 `ReMe` 用作 file store 后端。
- **何时选它**：需要本地嵌入式的向量 / 全文 / 混合检索，且不想维护独立服务。
- **链接**：[github.com/alibaba/zvec](https://github.com/alibaba/zvec) · [zvec.org](https://zvec.org/) ·
  [zvec-grep](https://github.com/zvec-ai/zvec-grep) · [Zvec Studio](https://github.com/zvec-ai/zvec-studio)
- **许可证**：Apache-2.0。

---

## 2. OpenViking 能力速览（Agent 上下文平台）

- **是什么**：火山引擎开源的 **Agent 上下文数据库**——用 `viking://` 虚拟文件系统统一
  knowledge（resource）/ memory / skill，Agent 像操作文件一样 `ls / tree / read / write / grep`。
- **关键设计（事实）**：
  - **目录即上下文 + L0/L1/L2 分层**：每个目录有 `.abstract.md`（摘要）与 `.overview.md`（概览），
    源文件为 L2；Agent 先扫摘要再决定读什么，检索可按 `level` 约束到某一层。
  - **三类上下文 + 记忆类型**：resource / memory / skill；memory 细分 `profile / preferences /
    entities / events / identity / soul / cases / trajectories / experiences`，
    其中 `experiences` 触发 **Agent Evolution** 管线（case → trajectory → 可复用经验）。
  - **生命周期钩子 + 异步抽取**：Claude Code / Codex / Cursor 等以 Hooks + MCP 接入；
    每次 prompt 前按 token 预算注入相关记忆，每次响应后**非阻塞**捕获，会话提交时后台抽取记忆。
  - **Context Gateway**：任何能改 base URL 的客户端都能获得记忆，无需安装插件或 MCP。
  - **内置评测**：LoCoMo（长会话用户记忆）与 tau2-bench（多轮 Agent 任务）。
- **何时选它**：需要"可浏览、可编辑、可范围检索"的 Agent 长期上下文，并愿意运行一个服务。
- **链接**：[github.com/volcengine/OpenViking](https://github.com/volcengine/OpenViking) ·
  [docs.openviking.ai](https://docs.openviking.ai/)
- **许可证**：主项目 AGPLv3（`crates/ov_cli` 与 `examples` 为 Apache-2.0）。

---

## 3. mem0（通用记忆组件，对照）

- 定位：配置驱动的通用记忆组件——多向量库 / 多 LLM / 多 embedding 可插拔，默认管线为
  "LLM 抽取事实 → 只增不改 → 哈希去重 → 批量落库"。
- 何时选它：需要跨会话的**通用** Agent 记忆，而非垂直领域记忆。
- 链接：[github.com/mem0ai/mem0](https://github.com/mem0ai/mem0)；
  设计对照见 [`mem0-source-reading.md`](./mem0-source-reading.md)。

---

## 4. 四方对照与 BugVault 的位置

| 层 | 项目 | 本质 | 结论 |
| --- | --- | --- | --- |
| 存储 / 检索引擎 | zvec | 进程内向量库（dense+sparse+FTS+hybrid+WAL） | 检索内核已商品化 |
| 通用记忆组件 | mem0 | 记忆生命周期组件 | 通用层已覆盖 |
| 上下文平台 | OpenViking | 上下文数据库 / 文件系统 | 垂直层价值被平台覆盖 |
| 垂直应用 | **BugVault** | bug / 规约记忆 MCP | **无独立产品空间，已冻结** |

BugVault 原以为差异化的两点——强制记录"失败尝试"、把复盘写回指令文件——在通用平台与
"文件夹 + grep"的简单方案面前不足以构成独立产品（详见 ADR-0001）。

---

## 5. 什么条件下才重开（判据）

沿用 ADR-0001 的 reconsideration trigger，并明确指出唯一还站得住的假设：

> **不存在一个"更好的记忆存储"能救这个产品；唯一值得验的是——度量一条记忆是否真正改变了 Agent 行为。**
> 重开判据：能在一个项目内、用 before/after 实验，证明某类结构化经验（尤其"失败尝试"）
> 显著降低了重复错误率。

在满足该判据之前，不增加检索、图谱或自动化功能。

---

## 6. 参考与证据索引

| 事实 | 来源 |
| --- | --- |
| zvec 能力 / 进程内 / dense+sparse / FTS / hybrid / WAL / 并发 | `alibaba/zvec` README |
| zvec v0.7.0、zvec-grep、ReMe 集成 | `alibaba/zvec` README（Important 段） |
| OpenViking 定位：context database / `viking://` 文件系统 | `volcengine/OpenViking` README |
| OpenViking 架构、模块、双存储层、数据流 | OpenViking `docs/en/concepts/01-architecture.md` |
| L0/L1/L2 分层与侧车文件 | OpenViking `docs/en/concepts/03-context-layers.md` |
| 三类上下文与记忆类型（含 experiences） | OpenViking `docs/en/concepts/02-context-types.md` |
| 记忆抽取 / 会话 commit 两阶段 | OpenViking `docs/en/concepts/06-extraction.md`、`08-session.md` |
| 检索：意图分析、`find` vs `search`、rerank | OpenViking `docs/en/concepts/07-retrieval.md` |
| 钩子生命周期（prompt 前 recall / 响应后 capture / 会话 commit） | OpenViking `docs/en/agent-integrations/02-claude-code.md` |
| Context Gateway | OpenViking `docs/en/guides/15-context-gateway.md` |
| 许可证（AGPLv3 主项目 / Apache ov_cli 与 examples） | OpenViking README（License 段） |
| BugVault 结论与否决理由 | [`docs/adr/0001`](../adr/0001-stop-bugvault-product-validation.md) |
| BugVault 现有 MCP 工具与 reflection 写回 | `src/bugvault/mcp_tools/tools.py`、`src/bugvault/services/reflection_svc.py` |
| mem0 设计对照（只增不改 / ID 防幻觉 / 实体层） | [`mem0-source-reading.md`](./mem0-source-reading.md) |
| LanceDB 选型理由 | [`codex-docs/refer/分析/03.为什么选择LanceDB.md`](../../codex-docs/refer/分析/03.为什么选择LanceDB.md) |
