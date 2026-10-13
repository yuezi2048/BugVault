# 编码 Agent 记忆方案横向调研 — nova / claude-mem / ECC / mem0

> 目的：为 BugVault 的产品定位与"下一步"提供外部证据。围绕六个问题逐项核对：
> 记录如何产生 / 字段是否有约束 / 什么证据能证明问题已解决 / 何时召回 /
> 如何让助手执行规约 / 如何发现同一错误再次发生。
>
> 证据基线：`nova` @ `78aa398`、`claude-mem` @ `a2150b2c0`（v13.37.0）、
> `ECC`（everything-claude-code）@ `b92f181b`、`mem0` @ `b7ad69a`；阅读日期 2026-10-13。
>
> 规则：能指到文件/行的写「事实」，推断写「判断」。范围是**文档 + 针对性源码定位**，
> 不是逐路径审计（claude-mem 与 ECC 体量很大，见 §8 边界）。

---

## 0. 结论先行

- 四家都已覆盖"捕获 + 跨会话回忆"这一层（事实）。
- **没有一家做「验证门禁 / status 生命周期 / 同项目复发检测」**（事实，见 §7 证据索引）。
  这三样才是尚未被占据的位置。
- "结构化记录"本身**不再是差异点**：nova、claude-mem 都有类型化记录，ECC 有带校验的
  instinct schema，mem0 虽是自由文本但有作用域与元数据过滤（事实）。
- ECC 已占据两个相邻位：`hookify-rules`（工具层强制 warn/block）与 `skill-comply`
  （测量 agent 是否真的遵守规约）（事实）。
- **判断**：BugVault 可辩护的差异应收敛到"验证门禁 + status 生命周期 + 复发检测"，
  而不是"我给记忆加了必填字段 / 结构化记录"。
- **决策**：针对这一未被占据的切面，BugVault 已由 [ADR-0003](../adr/0003-reopen-verification-gate.md)
  重开为**探索性下一阶段**（仅限该切面，不重开通用记忆 / 检索内核 / provider 抽象）。

---

## 1. nova — Markdown + grep，纯 skill 驱动

- **记录如何产生**：由 agent 按 skill 决策触发，非自动捕获。三个入口：`remember`
  （用户显式"记住"）、`update`（git-commit 时评估项目记忆）、`reflect`（被动抽取）；
  实际落盘交给纯 writer 子技能 `adr-creator` / `devlog-creator`
  （`skills/memory/SKILL.md`、`skills/devlog-creator/SKILL.md`）。
- **字段是否有约束**：DevLog/ADR 要求 YAML frontmatter `tags/modules/summary/tag`，
  正文为 Context/Insight/Implications（DevLog）、Background/Decision/Consequences（ADR）
  （`skills/devlog-creator/references/devlog-format.md`、`examples/devlog-example.md`）。
  但这是**提示词层面的约定，没有代码级校验**——agent 不填也没东西拦截（判断）。
- **什么证据能证明已解决**：无。只有 Insight + Implications，没有测试命令、验证结果或
  证据引用字段（事实）。
- **何时召回**：会话开始时"判断任务是否需要记忆"，简单自足任务直接跳过；需要时加载
  `user.md`/`memory.md`/`arch.md` 并跑 `recall`。`recall` 默认只搜**近 7 天** notes +
  ADR/DevLog；snapshot 历史仅在用户显式要求时检索（`skills/memory/SKILL.md`、`README.md`）。
- **如何让助手执行规约**：无强制。靠模板把触发规则注入 `CLAUDE.md`/`AGENTS.md`/cursor rule，
  等 agent 自觉遵守（`templates/*-snippet.*`）。
- **如何发现同一错误再次发生**：无。可能因召回命中相似 DevLog 而被提及，但没有自动复发检测。

---

## 2. claude-mem — SQLite + FTS5 + Chroma，hook 自动捕获

- **记录如何产生**：全自动。5 个生命周期 hook（SessionStart / UserPromptSubmit /
  PostToolUse / Stop / SessionEnd）捕获工具使用，后台 agent 生成 observation 与会话摘要
  （`README.md` "How It Works"、`src/storage/sqlite/schema.ts`）。
- **字段是否有约束**：有类型与结构，但无"缺项即拒绝"的准入。
  - Observation：`type` ∈ `decision | bugfix | feature | refactor | discovery | change`，
    另有 `title/concept/files_read/files_modified`
    （`src/types/database.ts`）。
  - SessionSummary：`request / investigated / learned / completed / next_steps`
    （`src/types/database.ts`）——这是**最接近"会话结束摘要"的开源实现**。
  - `memory_items` 表另有 `facts / concepts / files_read / files_modified` + FTS5 虚表
    （`src/storage/sqlite/schema.ts`）。
- **什么证据能证明已解决**：无验证字段。`completed` 是叙述，不是可执行的测试证据，也没有
  从"疑似解决"到"已验证"的状态迁移（事实）。
- **何时召回**：SessionStart 注入上下文；MCP 三层渐进
  `search → timeline → get_observations`（README 称 ~10x token 节省）。
- **如何让助手执行规约**：无强制；上下文注入 + skill 引导。另有 `<private>` 隐私过滤。
- **如何发现同一错误再次发生**：有**记录去重**（`tests/dedup`、
  `src/cli/handlers/file-context-dedupe.ts`），但不是"同一故障在时间轴上复发"的检测（事实）。

---

## 3. ECC（everything-claude-code）— 工程化最完整，最接近目标

- **记录如何产生**：多路。
  - `continuous-learning-v2`：PreToolUse/PostToolUse 的 `hooks/observe.sh` 写
    `observations.jsonl`，后台 Haiku `observer` 抽原子化"instinct"
    （`skills/continuous-learning-v2/SKILL.md`、`agents/observer.md`、`hooks/observe.sh`）。
  - `unified-memory`：`ecc.memory.v1` Markdown 文档，project/team/global 作用域，跨 harness 共享
    （`skills/unified-memory/SKILL.md`）。
  - `rules-distill`：把反复出现的跨 skill 原则提炼进 rule 文件（`skills/rules-distill/SKILL.md`）。
  - `brownfield-retrospective`：回溯既有项目、产出四轴 gap register（`skills/brownfield-retrospective/SKILL.md`）。
- **字段是否有约束**：instinct 有环境校验：frontmatter `id/trigger/confidence/domain/source/scope`
  + 正文 **Action / Evidence**；`confidence` 目标区间 0.3–0.9，解析到越界或畸形值时 clamp 到 0.5
  （`skills/continuous-learning-v2/scripts/instinct-cli.py`）。
- **什么证据能证明已解决**：instinct 有 **Evidence** 段（如"Observed 5 instances…"、
  "User corrected…"），属**行为证据**；仍没有"修复经测试验证"的证据或门禁（事实/判断）。
- **何时召回**：会话开始加载有界上下文（`scripts/hooks/session-start.js`，
  `ECC_SESSION_START_MAX_CHARS`）；observer 按观察量/间隔/信号触发模式检测。
- **如何让助手执行规约**：**四家里最强**。`hookify-rules` 支持
  `event: bash|file|stop|prompt|all` + `action: warn|block` 的正则/条件规则，
  **能在工具层真正拦截**（如挡危险命令、挡 .env 改动）（`skills/hookify-rules/SKILL.md`）。
  另有 `skill-comply` 专门测量 agent 是否真的遵守 skill/rule，产出合规率与工具调用时间线
  （`skills/skill-comply/SKILL.md`）。
- **如何发现同一错误再次发生**：**最接近的一个**。instinct 从 project 晋升到 global 的条件是
  `confidence ≥ 0.8` 且**在 ≥2 个项目出现**
  （`skills/continuous-learning-v2/scripts/instinct-cli.py`：`PROMOTE_CONFIDENCE_THRESHOLD = 0.8`、
  `PROMOTE_MIN_PROJECTS = 2`）。是"跨项目重复→提升"，不是"同项目复发"。

---

## 4. mem0 — 通用记忆层

- **记录如何产生**：`add(infer=True)` 单次 LLM 抽取事实，**ADD-only，不 UPDATE/DELETE**；
  也支持显式写入（`README.md`；`mem0/memory/main.py`）。
- **字段是否有约束**：自由文本 + metadata，无 schema。作用域 `user_id/agent_id/run_id`，
  检索支持任意元数据过滤（含 `AND/OR/NOT` 与 `eq/in/contains/icontains` 等）
  （`mem0/memory/main.py` `_build_filters_and_metadata`、search 过滤处理）。
- **什么证据能证明已解决 / 如何让助手执行规约 / 如何发现复发**：均无。唯一护栏是
  MD5 哈希去重 + 实体链接（事实）。详见既有文档 [mem0 源码阅读](mem0-source-reading.md)。

---

## 5. 横向对照

| 问题 | nova | claude-mem | ECC | mem0 |
|---|---|---|---|---|
| 记录如何产生 | skill 决策 | hook 自动 | hook + observer | LLM 抽取 |
| 字段是否有约束 | 约定（无校验） | 类型化（无准入） | 校验（instinct clamp） | 无 schema |
| 解决证据 | 无 | 无 | 行为 Evidence | 无 |
| 何时召回 | 会话判定 / 显式 | SessionStart + MCP | SessionStart + observer | 应用调用 |
| 强制执行规约 | 无 | 无 | **hookify warn/block** | 无 |
| 发现复发 | 无 | 记录去重 | **≥2 项目晋升** | 哈希去重 |

---

## 6. 对 BugVault 定位的含义

- **不能用的话术**："通用记忆组件只存对话式自由文本，缺少结构化记录"——mem0 可显式写入、
  nova/claude-mem 有类型化记录、ECC 有带校验 schema，这句站不住（判断）。
- **能站住的话术**：通用记忆层负责提取、持久化与检索，但**不强制每一次故障复盘补齐因果链、
  验证证据与适用条件**；这需要应用层额外设计（对四家均成立的判断）。
- **未被占据的楔子**：验证门禁（无测试证据不得晋升"已验证"）、`status` 生命周期
  （待验证/已验证/已失效）、同项目复发检测。ECC 的 `hookify`（执行）与 `skill-comply`（合规测量）
  是**相邻但不同**的位置：前者拦危险动作，后者测规则遵守，都不是"这条修复是否经验证"（判断）。

---

## 7. 证据索引

| 事实 | 位置 |
|---|---|
| nova skill 驱动 / recall 模式 / 7 天窗口 | `refer/nova/skills/memory/SKILL.md` |
| nova DevLog 格式（frontmatter + Context/Insight/Implications） | `refer/nova/skills/devlog-creator/references/devlog-format.md` |
| nova 示例 DevLog/ADR | `refer/nova/examples/devlog-example.md`、`examples/adr-example.md` |
| nova 触发规则模板（CLAUDE/AGENTS/cursor） | `refer/nova/templates/` |
| claude-mem 5 hook + SQLite + Chroma + MCP 三层 | `refer/claude-mem/README.md` |
| claude-mem observation 类型枚举 / 摘要字段 | `refer/claude-mem/src/types/database.ts` |
| claude-mem 存储 schema / FTS5 | `refer/claude-mem/src/storage/sqlite/schema.ts` |
| ECC 生命周期 hook 契约 | `refer/ECC/hooks/memory-persistence/README.md`、`hooks/hooks.json` |
| ECC instinct 模型（confidence/Evidence/scope） | `refer/ECC/skills/continuous-learning-v2/SKILL.md` |
| ECC observer 模式检测（纠错/错误解决/重复流程/工具偏好） | `refer/ECC/skills/continuous-learning-v2/agents/observer.md` |
| ECC 晋升阈值（0.8 / ≥2 项目） | `refer/ECC/skills/continuous-learning-v2/scripts/instinct-cli.py` |
| ECC hookify 强制 warn/block | `refer/ECC/skills/hookify-rules/SKILL.md` |
| ECC 合规测量 | `refer/ECC/skills/skill-comply/SKILL.md` |
| ECC 跨 harness 记忆 vault | `refer/ECC/skills/unified-memory/SKILL.md` |
| mem0 ADD-only / 过滤 / 去重 | `refer/mem0/README.md`、`refer/mem0/mem0/memory/main.py` |

---

## 8. 边界与未验证项

- 本次为**文档 + 针对性源码定位**，非逐路径审计。claude-mem（v13.37.0）与 ECC（313 个 skill）
  体量很大，结论限于上文点名的文件；未见得等于不存在，反向亦然。
- "无验证门禁"是对**已定位代码/文档**的判断；若要下更硬结论，需按模块继续深挖
  （claude-mem 的 observation 生成链、ECC 的 hookify 运行时）。
- `refer/` 按仓库惯例不提交，本文只保留结论与文件级指针。
- 下一步：ADR-0001 的"产品验证已停止"已由 [ADR-0003](../adr/0003-reopen-verification-gate.md)
  判定为**重开**——仅限"验证门禁 + status + 复发检测"这一探索性切面；接下来把该切面收敛为
  一个最小闭环 spec，并满足 [ADR-0002](../adr/0002-agent-memory-needs-effect-measurement.md)
  的前后测量条件。
