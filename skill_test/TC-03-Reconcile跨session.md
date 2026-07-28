# TC-03: Reconcile — 跨 session 恢复执行

> 测试目标：验证 §6 Reconcile 正确处理遗留 plans，以及 §0 的 plans 存在检查。
> 参考：shifu README 「Next session: `/shifu reconcile`」

---

## 前置状态

上一个 session 留下了如下 `plans/` 状态：

```markdown
# plans/README.md

| Plan | 标题 | 策略 | 代价 | 依赖 | 状态 |
|------|------|------|------|------|------|
| 001 | 重构 LanceDB 查询层 | direct | M | — | DONE |
| 002 | 添加查询缓存 | direct | S | 001 | BLOCKED |
| 003 | 优化查询测试 | parallel | S | 001 | TODO |

## 已拒绝的方案
- 方案「使用 Redis 做缓存」：当前体量不需要
```

`plans/002-query-cache.md` 的 BLOCKED 原因是：
```
STOPPED BECAUSE: Step 2 验证失败 — `pytest tests/test_cache.py` 中 mock 对象的接口与
lancedb 0.20 不一致，需要先调研 lancedb 0.20 的缓存 API 变化。
```

`plans/` 的 commit SHA 为 `a1b2c3d`，当前 HEAD 为 `e5f6g7h`（不一致）。

---

## 场景

用户在新的 session 中启动，说「继续上次的查询优化工作」

## 预期工作流

### Step 1: preflight（查坑）

```python
agent.run_skill("preflight")
```

（输出正常检查清单）

### Step 2: decompose §0 门槛判断

用户的需求是继续已有工作，不是新需求。但「查询优化」涉及多模块 → 复杂。
进入 decompose 时发现 `plans/` **已存在且包含非 DONE plans**：

| 检查项 | 结果 |
|--------|------|
| `plans/` 存在 | ✅ 是 |
| 存在非 DONE plans | ✅（002 BLOCKED，003 TODO）|
| commit SHA 与 HEAD 一致 | ❌ 不一致（`a1b2c3d` ≠ `e5f6g7h`）|
| **行为** | **先进入 §6 Reconcile** |

### Step 3: decompose §6 Reconcile

| Plan | 原状态 | 处理 | 处理后状态 |
|------|--------|------|-----------|
| 001 | DONE | drift check：scope 文件未变（`src/bugvault/database/`）→ 验证通过 | VERIFIED |
| 002 | BLOCKED | 读原因 + 调查 lancedb 0.20 API：发现确实有新缓存接口。重写 spec 绕过旧 mock | TODO（重写后） |
| 003 | TODO | drift check：发现 `001` 已完成，`src/bugvault/database/` 文件变更但相关测试文件未被变更 → 刷新 scope 路径和 SHA | TODO（已刷新） |

### Step 4: 输出 Reconcile 报告

```
## Reconcile 报告

- ✅ 001: DONE → VERIFIED（无 drift）
- 🔧 002: BLOCKED → TODO（重写了 spec，绕过 lancedb 0.20 的 mock 问题）
- 🔧 003: TODO（刷新了 scope 路径和 SHA）
- 当前可执行：002（重写后）、003
```

### Step 5: 回到 §4 Execute

按依赖序执行：003 依赖 001（已 DONE）→ 可直接执行

```
当前状态：
  002（TODO，重写后）→ 用户确认后执行
  003（TODO，刷新后）→ 依赖 001（VERIFIED），可并行执行
```

---

## 验证标准

- [ ] decompose 进入时检测到 `plans/` 存在，走 reconcile 路径
- [ ] SHA 不一致被正确检测
- [ ] Reconcile 对 DONE 做了 drift check 并标记 VERIFIED
- [ ] Reconcile 对 BLOCKED 做了调查并重写 spec
- [ ] Reconcile 对 TODO 做了 refresh
- [ ] 输出 reconcile 报告格式正确
- [ ] Reconcile 后正常进入执行阶段
