# PATH-003: Decompose Skill 落地 — 从三方对比到完整工作流

> 日期: 2026-07-21
> 对应: ADR-001 Decompose Skill 设计
> Commit: `582a874`

## S — Situation（背景）

BugVault 已有的工作流是 preflight（查坑）→ 干活 → postflight（归档），缺少「复杂任务拆解」环节。Agent 接到复杂需求直接写代码，缺乏系统性的分解→验证→审查机制。

## T — Task（任务）

调研 shifu / improve / emil-kowalski/skills 三个开源 skill 项目，分析各自优势，结合 BugVault 已有的知识闭环优势，设计并落地一个「任务分解与执行编排」工作流。

核心需求：
1. 复杂任务自动拆解为子任务，每步可验证
2. 写自包含 spec，可交给 subagent 或下次 session 继续
3. 标准化 review 流程（Before/After + Verdict 体系）
4. 跨 session 计划管理（reconcile）
5. 不增加小任务的认知负担（≤3 文件直接跳过）

## A — Action（执行过程）

### Step 1: 三方特性分析

| 来源 | 核心能力 | 我们借鉴了什么 |
|------|---------|-------------|
| **shifu** | 任务分解、execute all、plans 状态机、经济模型 | 三种执行策略、依赖图解析、状态机 |
| **improve** | Recon/Vet/Reconcile、Before-After Review、drift check | Recon 调研清单、Verdict 循环、reconcile 机制 |
| **emil skills** | domain-specific improve 适配、专家知识编码 | 单 SKILL.md 文件形态、精确值约束 |

### Step 2: 设计决策（详见 ADR-001）

- **文件形态**：单 SKILL.md（decompose），参考 improve 风格。preflight/postflight/doc-* 保持独立
- **调用方式**：agent 内部自动调用，用户不感知 skill 名
- **复杂度判定**：≤3文件/单模块 → 跳过；多模块/schema/API/安全变更 → 自动进入
- **三种 effort 级别**：quick / standard（默认）/ deep

### Step 3: 编写 decompose SKILL.md

文件位置：`.reasonix/skills/decompose.md`（331 行）

| 阶段 | 内容 |
|------|------|
| §0 门槛判断 | 复杂度判定 + plans 目录存在检查 |
| §1 Recon | 代码调研 + BugVault 查坑 + effort 三级 |
| §2 Decompose | Findings 表 + 4 策略标记 + 拒绝记录 + 用户确认 |
| §3 Spec | 写 spec 到 plans/ + 7 项自包含检查 |
| §4 Execute | 依赖解析 + subagent 派发 + 执行报告 + drift check |
| §5 Review | Before/After 表 + APPROVE/REVISE/BLOCK 三态 |
| §6 Reconcile | 跨 session 状态处理（6 种 plans 状态）|

含附录：plans 状态机（8 态）+ README 索引模板。

### Step 4: 编写测试用例

5 个测试场景覆盖所有路径：

| 用例 | 覆盖路径 |
|------|---------|
| TC-01 完整流水线 | 复杂任务全流程（§0→§5→postflight）|
| TC-02 简单任务跳过 | §0 正确跳过 |
| TC-03 Reconcile跨session | §6 遗留计划恢复 |
| TC-04 Review循环 | §5 REVISE→重执行→APPROVE |
| TC-05 混合策略编排 | §4 依赖图并行+串行调度 |

### Step 5: 实际演练（黑名单配置功能）

用「MCP tool 黑名单」功能做两次实际测试：

**第一次**（含 STOP 踩坑）：
- 001 config 的 `list[str]` 方案被 pydantic-settings 拒绝 → 触发 STOP 条件
- 按 spec 的预案正确处理：改为 `str` + 属性方法
- 总耗时 ~2min，token ~46K，费用 ¥0.08

**第二次**（干净跑）：
- 已知最佳路径，一次通过
- 总耗时 ~56s，token ~33K，费用 ¥0.05
- 验证了：scope 约束、拒绝记录、STOP 条件预判的实际价值

### Step 6: Token 成本分析

| 场景 | Token | 费用 | 说明 |
|------|-------|------|------|
| 直接写 | ~10K | ¥0.02 | 无 decompose |
| 走 decompose | ~33K | ¥0.05 | 含 spec/review/状态管理 |
| 额外成本 | +23K | **+¥0.03** | 买到了可回溯的工程资产 |

## R — Result（结果）

### 产出物

| 类型 | 文件 | 说明 |
|------|------|------|
| Skill | `.reasonix/skills/decompose.md` | decompose 主 skill（331 行）|
| 架构决策 | `reasonix-doc/review/ADR-001-decompose-skill设计.md` | 设计决策记录 |
| 测试用例 | `skill_test/TC-01~05` | 5 个场景覆盖所有路径 |
| 验证 | 实际演练 2 轮 | 确认流程可执行、STOP 条件有效、成本可控 |

### 验证矩阵

| 需求 | 验证方式 | 结果 |
|------|---------|------|
| 复杂任务自动分解 | Findings 表输出 + 用户确认 | ✅ |
| spec 自包含 | 7 项检查清单全过 | ✅ |
| 标准化 review | Before/After + Verdict | ✅ |
| STOP 条件生效 | list[str] 踩坑后正确规避 | ✅ |
| 小任务跳过 | ≤3 文件直接跳过 | ✅ |
| 跨 session 管理 | Reconcile 逻辑在 spec 中定义 | ✅ |

### 已知未完成

- 004（测试用例）在演练中未执行（pendings）
- git worktree 隔离暂不支持（通过 strict review 补偿）
- reconcile 的跨 session 自动检测尚未在线验证

## 相关记录

- ADR-001: decompose skill 设计决策
- BugVault: `save_bug_experience` — pydantic-settings list[str] 兼容问题
- BugVault: `save_convention` — 复杂类型字段使用 str + 属性方法
