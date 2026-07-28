# TC-04: Review 循环 — REVISE → 重执行 → APPROVE

> 测试目标：验证 §5 Review 的 REVISE 回路能在 ≤2 轮内闭环。
> 参考：shifu 「Verdict: approve, revise (max 2 rounds), or block」

---

## 场景

子任务「为 BugVault 的 MCP tool 添加分页参数」。Spec 已写好，subagent 执行完毕。

## 预期工作流

### Round 1: Review → REVISE

**Subagent 执行报告：**

```
STATUS: COMPLETE
STEPS:
  Step 1: 添加 page_size / page_token 参数 → done
  Step 2: 修改查询逻辑支持分页 → done
  Step 3: 测试 → done，新增测试通过
FILES CHANGED: src/bugvault/mcp_tools/tools.py, src/bugvault/database/lancedb_client.py
NOTES: 无
```

**Review 发现：**

| Before | After | 说明 |
|--------|-------|------|
| `def search(query, limit=10)` | `def search(query, page_size=20, page_token=None)` | 添加分页参数 |

问题：**scope 合规检查发现一个越界文件**

```
$ git diff --stat
 src/bugvault/mcp_tools/tools.py               | 15 ++++++
 src/bugvault/database/lancedb_client.py       | 30 ++++++++++++
 src/bugvault/mcp_tools/__init__.py            |  1 +   ← OUT OF SCOPE
```

`__init__.py` 不在 spec 的 in-scope 列表中。

**Verdict: REVISE**

反馈：「`src/bugvault/mcp_tools/__init__.py` 的变更超出 scope。请撤销该文件修改，重新提交。」

### Round 2: Subagent 修正

Subagent 撤销越界修改，重新提交：

```
STATUS: COMPLETE（revised）
STEPS:
  - 撤销 __init__.py 修改 → done
  - 重新提交 → done
FILES CHANGED: src/bugvault/mcp_tools/tools.py, src/bugvault/database/lancedb_client.py
NOTES: 已撤销 __init__.py 的变更
```

**Review 再次检查：**

- ✅ criteria 全过
- ✅ scope 干净（无越界文件）
- ✅ 读 diff：逻辑正确，符合库约定

**Verdict: APPROVE**

### 结果

Plans 状态更新为 DONE。进入下一任务或 postflight。

---

## 验证标准

- [ ] Review 检查到 scope 越界
- [ ] REVISE 给出具体反馈（哪个文件越界、怎么修）
- [ ] Subagent 在 1 轮内修正了问题
- [ ] 第 2 轮 Review 验证通过，APPROVE
- [ ] 如果超 2 轮 → BLOCK（spec 本身有问题）

## 边界情况：2 轮仍不合格 → BLOCK

如果第 2 轮 REVISE 后问题仍在，第三次 → BLOCK：

```
Verdict: BLOCK
原因：subagent 连续 2 轮 revision 未解决 scope 越界问题 → spec 可能不清晰
行为：标记 BLOCKED，回到 §3 重写 spec
```
