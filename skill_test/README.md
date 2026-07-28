# Decompose Skill — 模拟测试目录

参考 [shifu README](../参考/skills/shifu/README.md) 的使用模式和命令体系，编写了 5 个测试用例，覆盖 decompose skill 的所有主要路径。

## 测试覆盖矩阵

| 用例 | 覆盖阶段 | 覆盖路径 | 参考场景 |
|------|---------|---------|---------|
| **TC-01** 完整流水线 | §0→§1→§2→§3→§4→§5→postflight | 复杂任务全流程 | shifu 自动模式 |
| **TC-02** 简单任务跳过 | §0→直接 execute→postflight | 简单任务跳过 decompose | shifu quick 模式 |
| **TC-03** Reconcile 跨 session | §0→§6→§4 | 遗留 plans 恢复执行 | shifu reconcile 命令 |
| **TC-04** Review 循环 | §5（REVISE→重执行→APPROVE）| Review verdict 回路 | shifu review 命令 |
| **TC-05** 混合策略编排 | §4（parallel + direct 混合）| 依赖图解析与调度 | shifu execute all 命令 |

## 各阶段覆盖统计

| decompose 阶段 | 覆盖用例 | 是否覆盖 |
|---------------|---------|---------|
| §0 门槛判断 | TC-01（复杂）、TC-02（简单）、TC-03（plans 存在）| ✅ 全覆盖 |
| §1 Recon | TC-01 | ✅ |
| §2 Decompose（Findings + 用户确认）| TC-01、TC-05 | ✅ |
| §3 Spec（写 spec + 自包含检查）| TC-01 | ✅ |
| §4 Execute（依赖解析 + 派发）| TC-01、TC-03、TC-05 | ✅ 三种策略都覆盖 |
| §5 Review（Before/After + Verdict）| TC-01（APPROVE）、TC-04（REVISE→APPROVE）、TC-05（BLOCK）| ✅ 三态全覆盖 |
| §6 Reconcile | TC-03 | ✅ |
| 拒绝记录 | TC-01 | ✅ |
| Drift check | TC-03 | ✅ |

## 测试方式

这些测试为**模拟测试**（dry-run），通过以下方式验证：

1. **静态验证**：阅读测试场景，检查各阶段行为是否符合 decompose SKILL.md 的定义
2. **行为验证**：在真实 session 中遇到类似场景时，观察 agent 是否按 decompose 流程执行
3. **边界情况**：TC-04 验证 REVISE 回路（≤2 轮）、TC-05 验证 BLOCK→重写 spec 的恢复路径
