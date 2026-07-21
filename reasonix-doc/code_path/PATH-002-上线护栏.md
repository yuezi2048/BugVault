# PATH-002: 上线护栏 — ErrorCode / traceId / AI 调用日志 / Token 成本

> 日期: 2026-07-21
> Commit: `0080b35`

## S — Situation（背景）

导师要求 AI 上线必须满足 15 条最小护栏清单。BugVault 是单用户本地 MCP 服务（stdio 传输），
其中 4 条架构级不适用（多租户限流、缓存、扣点、PDF 队列），3 条已满足（幂等、JSON 兜底、双熔断器），
**4 条需要补**：
1. traceId 贯穿 — 每条日志可追溯至同一请求
2. 结构化错误码 — 区分限流/超时/鉴权/内容安全等
3. 统一 AI 调用日志 — entry/exit 结构化 JSONL
4. Token 成本估算 — 按模型单价计算每次 LLM 调用的预估费用

## T — Task（任务）

在不破坏现有 108 个测试、不影响现有 MCP 工具接口、不改动数据模型的前提上，增加这 4 项能力。

## A — Action（执行过程）

### Step 1: ErrorCode 枚举（`src/bugvault/models/error_code.py`）

定义 `ErrorCode(str, Enum)`，10 个语义值覆盖所有输出场景：
- success: `ok`
- client errors: `rate_limited`, `timeout`, `auth_fail`, `content_safety`
- processing: `parse_error`, `validation_error`, `internal`
- resources: `not_found`, `quota_exceeded`

同时实现 `_classify_error(exc)` 函数，按异常消息启发式映射到 ErrorCode，
作为 `@log_tool_call` 装饰器和 `handle_call_tool` 的共享分类逻辑。

**关键决策**：用 `str, Enum` 而非 `IntEnum`，JSON 序列化时直接输出 `"rate_limited"` 而非 `3`。

### Step 2: traceId 贯穿（`src/bugvault/utils/logger.py`）

核心改动：
- `contextvars.ContextVar("trace_id")` 持有当前请求的 trace ID
- `set_trace_id()` 生成 12 位 hex UUID 并设置到 context var
- `get_trace_id()` 供下游服务读取（返回值默认为 `""`）
- `TraceIdFilter(logging.Filter)` 将 trace_id 注入每条 log record 的 `%(trace_id)s` 字段
- 日志格式从 `[asctime] name level: msg` 改为 `[asctime] name level [trace_id] msg`

trace_id 在 `handle_call_tool` 入口生成，下游服务的 `logger.info(...)` 自动携带同一 trace_id，
无需逐层传递参数。

### Step 3: 统一 AI 调用日志（`src/bugvault/observability.py` + `tools.py`）

- `AiCallLogEntry` 数据类：13 个字段（timestamp, trace_id, event_type, tool_name, duration_ms, status, error_code, error_message, model, prompt_tokens, completion_tokens, total_tokens, estimated_cost_usd）
- `append_ai_call_log()` 追加到 `{data_root}/log/ai_call.jsonl`
- 在 `handle_call_tool` 中每次工具调用写 2 条（entry + exit），包含耗时和错误码

**关键决策**：entry/exit 双条设计，而非单条。需要能区分「调用卡住未返回」和「正常返回」。
如果只有 exit 日志，不知道工具是否被调用过。

### Step 4: Token 成本估算（`observability.py` + `rag_eval_result.py` + `rag_evaluator_svc.py`）

- `_MODEL_PRICING` 字典：11 个已知模型 + 1 个默认兜底
- `estimate_cost(model, prompt_tokens, completion_tokens)` → `float` USD
- `RAGEvalResult.estimated_cost_usd` 新字段
- `_attach_usage()` 中调用 `estimate_cost()` 填充该字段
- `_persist_eval()` JSONL 记录中增加 `estimated_cost_usd`

**关键决策**：best-effort 估算（try/except 包裹），不因成本计算失败阻塞主流程。
定价表写在代码中而非配置文件，因为更新频率低（数月一次），减少运维负担。

## R — Result（结果）

- 新增 2 个文件，修改 4 个文件
- **108 现有测试通过**，未引入回归
- 新模块全部通过语法检查和导入冒烟测试

### 运行时产出

`~/.bugvault/log/ai_call.jsonl`：
```jsonl
{"timestamp":"2026-07-21T10:30:00","trace_id":"a1b2c3d4e5f6","event_type":"entry","tool_name":"retrieve_bug_experience",...}
{"timestamp":"2026-07-21T10:30:01","trace_id":"a1b2c3d4e5f6","event_type":"exit","tool_name":"retrieve_bug_experience","duration_ms":1250.34,"status":"ok","error_code":"ok",...}
```

`~/.bugvault/log/rag_eval.jsonl`（追加字段）：
```jsonl
{"estimated_cost_usd":0.00021,...}
```

日志格式升级（stderr）：
```
[10:30:00] bugvault INFO [a1b2c3d4e5f6] Tool start: retrieve_bug_experience
```

### 护栏清单覆盖

| # | 护栏 | 状态 | 实现位置 |
|---|------|------|---------|
| 5 | traceId 贯穿 | ✅ | `utils/logger.py` ContextVar + Filter |
| 6 | AI 调用日志 | ✅ | `observability.py` JSONL + `tools.py` entry/exit |
| 7 | 错误码分类 | ✅ | `models/error_code.py` 10 种枚举 |
| 12 | Token 成本 | ✅ | `observability.py` 定价表 + `rag_eval_result.py` 字段 |

## 相关记录

- BugVault: `save_convention` — observability 日志规范
- BugVault: `save_bug_experience` — 护栏清单检查（本次 session 记录）
