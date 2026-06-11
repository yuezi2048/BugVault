# PATH-001: MCP 工具 Description 优化

## 背景
所有 5 个 BugVault MCP 工具的 description 都以 `"CRITICAL: You MUST..."` 开头，导致：
- 每个工具都号称自己「第一优先」，等于没有优先级
- 决策逻辑分散在 5 段长文本里，Agent 难以快速扫描
- 缺少「什么场景用哪个」的选择逻辑

## 执行路径

### 参考来源
参照 `/home/ljy/Documents/nwu/project/invoice-mangager/doc/BugVault-MCP-描述优化参考.md` 给出的建议。

### 改动文件
`src/bugvault/mcp_tools/tools.py` — `handle_list_tools()` 中的 5 个 `description=` 字段。

### 具体改动

| 工具 | 旧风格 | 新风格 |
|------|--------|--------|
| `retrieve_bug_experience` | CRITICAL 开场 + 6 行强制语气 | 嵌入式决策树，一目了然何时用什么工具 |
| `save_bug_experience` | CRITICAL 开场 + 6 行强制语气 | 场景描述 + 与 `save_convention` 的选择逻辑 |
| `save_convention` | CRITICAL 开场 + 3 段长文本 | 判断标准示例（"下次换个地方也可能踩"） |
| `retrieve_convention` | CRITICAL 开场 + 技术描述 | 明确互补角色 + 可跳过条件 |
| `reflect_and_prevent_error` | CRITICAL 开场 + 6 行强制语气 | 3 条触发条件 + 排除条件 |

### 三条底线原则
1. **只有一个入口工具带决策树** — `retrieve_bug_experience` 嵌入完整决策树
2. **去掉 "CRITICAL: You MUST"** — 每个工具都 CRITICAL = 没有 CRITICAL
3. **第一句话回答「我做什么」** — 而不是「我有多重要」

## 验证
- 通过 `read_file` 逐段确认 5 个 description 已按预期更新
- 无语法错误（缩进保持一致）
- 工具 name、inputSchema、handler 逻辑均未改动

## 后续注意事项
- 新增 MCP 工具时遵循上述三条原则
- 入口工具（retrieve_bug_experience）的决策树可随工具集扩展而更新
