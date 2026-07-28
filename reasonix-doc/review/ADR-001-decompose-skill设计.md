# ADR-001: Decompose Skill 设计 — 任务分解与执行编排工作流

> 日期: 2026-07-21
> 状态: 已接受
> Commit: `582a874`

## 背景

BugVault 已有 preflight（开工查坑）→ postflight（完工归档）的闭环工作流，但在「干活中」阶段缺少系统性的任务分解与执行编排能力。之前的做法是：接任务直接写代码，写完后归档。对于复杂任务，缺少「先想清楚再动手」的环节。

调研了三个参考项目：
1. **shifu**（vikingmute）— 通用任务分解，贵模型拆任务+写spec，便宜模型执行
2. **improve**（shadcn）— 代码库审计→发现改进机会→写实现计划；含 Recon/Vet/Reconcile 等高级机制
3. **emil-kowalski/skills** — 展示了 domain-specific 的 improve 适配模式 + 专家知识编码为 skill

## 选项

### 方案 A：多个独立 skill（analyze + plan + review 各一个文件）

拆分多个独立 skill，由 postflight 编排器统一调度。

- 优点：职责单一，可单独复用
- 缺点：跨 skill 传 findings 表需额外机制；agent 需记多个名字；上下文切换开销

### 方案 B：单 SKILL.md + 保持现有独立小 skill（选中）

将 analyze+plan+execute+review+reconcile 合并为一个 `decompose` skill，单文件。已有的 preflight/postflight/doc-*/git-commit 保持独立。

- 优点：用户感知一个入口（或不感知，由 agent 自动调）；内部工作流连贯；借鉴 improve 风格
- 缺点：单文件体积较大（331 行，可控）

**选择理由：**
- decompose 的各个阶段是强时序依赖的（先 Recon 才能拆任务，拆完才能写 spec），拆开反而不自然
- preflight/postflight/doc-* 是嵌入日常工作流的基础设施，职责边界清晰，保留独立性
- 331 行的复杂度远低于 emil-design-eng 的 674 行，可控

### 方案 C：全自动隐式触发 vs 显式命令

选择 **agent 内部自动调用**，用户不感知 skill 名。参考 shifu 的「用户不指定命令时 infer 为 full workflow」。同时保留 `quick`/`deep` 级别控制。

## 决策

选择了 **单 SKILL.md + 全自动触发** 的方案：

```
preflight（已有，增强门槛判断）
  → 复杂度判定
    ├── 简单（≤3文件，单模块）→ 跳过，直接执行
    └── 复杂 → 自动调 decompose（§1→§6）
          → Recon → 拆任务 → 写 spec → 编排执行 → Review → 更新 plans 状态
  → postflight（已有，增强 plans 同步）
```

## 理由

| 需求 | 方案 A | 方案 B | 方案 C |
|------|--------|--------|--------|
| 用户零认知负担 | ❌ 需记多个名 | ✅ 自动调 | ✅ 自动调 |
| 工作流连贯性 | ❌ 跨 skill 切换 | ✅ 单文件流转 | ✅ |
| 模块可复用性 | ✅ 独立可拆 | ⚠️ 内部函数可拆 | ⚠️ |
| 借鉴 improve 模式 | ❌ 不同风格 | ✅ 一主多辅 | ✅ |
| 文件大小可控 | ✅ 小文件 | ⚠️ 331行 | ⚠️ |

decompose 的核心设计借鉴自：
- **shifu** 的经济模型（贵拆便宜执行）、三种执行策略、plans 状态机
- **improve** 的 Recon/Vet/Reconcile/Before-After Review/drift check
- **emil** 的 domain-specific 适配思路

BugVault 独有的差异化能力（shifu/improve 都没有）：
- 开工前查坑（BugVault retrieval）
- 完工后归档（postflight + BugVault save）
- git 深度集成（hook 保护 + hash 回填）

## 影响

- 正面：复杂任务有了系统性分解方法；plans 目录提供了可回溯的执行记录；STOP 条件提前规避了实现中的坑（实测验证）
- 负面：小任务多了约 25s/¥0.03 的 overhead（spec 写文件 + 状态管理）；需要维护 plans/ 目录的整洁
- 代价：对于 ≤3 文件的小修改，overhead 不成立；对于 4-8 文件的跨模块任务，合理

## 相关记录

- BugVault: `save_convention` — decompose 工作流规范
- PATH-003: decompose skill 实现路径
