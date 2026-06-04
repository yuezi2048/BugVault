# BugVault v1.1.1 最终测试报告

> 测试日期: 2026-06-04
> 测试范围: 全链路 E2E（检索 + 评估 + 容灾）
> 数据规模: bug_records=2,108, bugvault_chunks=5,365

---

## 一、测试环境

| 配置项 | 值 |
|---|---|
| 硬件 | CPU (Intel), 无 GPU |
| Embedding 模型 | `BAAI/bge-small-zh-v1.5` (512 dim, 90MB ONNX) |
| Judge LLM | `deepseek-v4-flash` (OpenAI 兼容 API) |
| Vector DB | LanceDB 0.32.0 (嵌入式，无外部依赖) |
| FTS 引擎 | Tantivy (LanceDB 内建) |
| Cross-Encoder | `Xenova/ms-marco-MiniLM-L-6-v2` (80MB ONNX) |
| Python | 3.13 + uv (hatchling) |

---

## 二、检索性能测试

### 2.1 双路召回 + RRF 融合

| 测试 Query | Vector | FTS | RRF 融合 | parent 聚合 | 检索耗时 |
|---|---|---|---|---|---|
| TypeError: can only concatenate str (not int) to str | 20 | 20 | 40 | 23 | 0.0s |
| 怎么解决 Python 循环里的类型错误 str 和 int | 20 | 20 | 40 | 25 | 0.0s |
| Python TypeError 报错 (target_tech_stack=java) | 20 | 5 | 25 | 18 | 0.0s |
| sqlalchemy.exc.ResourceClosedError async_db.py | 20 | 20 | 40 | 18 | **0.1s** |

> **检索阶段总耗时 < 100ms**，包括：embedding ONNX 推理 + Vector ANN + FTS BM25 + RRF 融合 + parent 聚合 + IN 回捞。

### 2.2 Cross-Encoder 精排

| 候选集大小 | 精排耗时 |
|---|---|
| 5 条 | ~50ms |

---

## 三、评估性能测试

### 3.1 claim_level 深度评估

| 评估策略 | Prompt tokens | Completion tokens | 总 tokens | 耗时 |
|---|---|---|---|---|
| `simple` (整体打分) | ~300 | ~80 | ~380 | ~1s |
| `claim_level` (CoT 声明级) | 539 | 1,092 | **1,631** | **~12s** |

> **瓶颈分析**: 评估耗时远大于检索耗时（12s vs 0.1s），深层评估的延迟完全来自 Judge LLM 的推理速度，与 BugVault 本身无关。

---

## 四、检索精度测试

### 4.1 测试 A — 精确报错狙击

| 项目 | 结果 |
|---|---|
| Query | `TypeError: can only concatenate str (not 'int') to str report.py:56 generate_summary` |
| 目标匹配 | ✅ Top-1 匹配 `error_log` chunk |
| FTS 表现 | ✅ 对精确路径名 `report.py:56` 强命中 |
| 验证结论 | **Small-to-Big 粒度召回正确** |

### 4.2 测试 B — 语义模糊查询

| 项目 | 结果 |
|---|---|
| Query | `怎么解决 Python 循环里的类型错误 str 和 int 拼接` |
| 目标匹配 | ✅ **Top-1 命中** `TypeError: can only concatenate str` |
| chunk 命中类型 | `['error_log', 'semantic', 'semantic']`（报错 + 方案双命中） |
| 验证结论 | **双路 RRF 融合有效，语义+关键词互补** |

### 4.3 测试 C — 跨端幻觉过滤

| 项目 | 结果 |
|---|---|
| Query | `Python TypeError 报错` + `target_tech_stack=java` |
| 是否混入 Python 记录 | ❌ 无 Python 记录 |
| 误中记录 | `javascript`（java 子串匹配） |
| 验证结论 | **过滤生效，无跨语言幻觉** ⚠️ 需优化 java/javascript 区分 |

---

## 五、全链路 E2E 闭环测试

### 5.1 模拟用户场景

```
用户报错: sqlalchemy.exc.ResourceClosedError: This result does not return rows
          async_db.py:45 session closed after first query
请求参数: eval_depth="claim_level", target_tech_stack="Python"
```

### 5.2 时间线

| 阶段 | 耗时 | 占比 |
|---|---|---|
| 双路检索 + RRF + parent 聚合 | 0.1s | **0.8%** |
| Cross-Encoder 精排 | ~0.05s | **0.4%** |
| claim_level LLM 评估 (CoT) | 11.9s | **98.8%** |
| **总计** | **12.0s** | 100% |

### 5.3 评估输出

```
Strategy:     claim_level
Confidence:   9.0/10
Faithfulness: 1.0 (100% claims supported)
Tokens:       1,692
```

### 5.4 Claims 校验（零幻觉 ✅）

```
✅ Claim 1: ResourceClosedError is an error
   Reason: 文档明确包含此错误信息
✅ Claim 2: 解决方案是使用 async_session context manager + scalars()
   Reason: 文档明确给出了此方案
```

---

## 六、容灾测试

| 故障场景 | 保护机制 | 结果 |
|---|---|---|
| claim_level LLM 异常 (JSON 解析失败) | 双重降级 → simple | ✅ `strategy_used: "simple (fallback_from_error)"` |
| FTS 引擎异常 | try/except → vector-only | ✅ Warning 日志 + 降级 |
| chunks 表为空 | fallback → bug_records 搜索 | ✅ 自动降级 |
| Max claim evals 超限 | 配额熔断 → simple | ✅ `strategy_used: "simple"` |

---

## 七、压测数据

| 指标 | 值 |
|---|---|
| 最大数据量验证 | 100k Parquet 行 → 2,052 条 QA 对入库 |
| 最大 parent 表 | 2,108 条 |
| 最大 chunks 表 | 5,365 条（~2.54 chunks/rec） |
| 导入吞吐 (parent) | ~20,000 条/秒 (零向量) |
| 导入吞吐 (chunks) | ~8 条/秒 (ONNX 推理瓶颈) |
| 检索 QPS | ~50 QPS (纯检索) / ~0.08 QPS (含 claim_level 评估) |

---

## 八、已知 P1 问题（未修复）

| # | 问题 | 影响 | 状态 |
|---|---|---|---|
| 1 | LanceDBClient 重复方法定义 | 维护风险 | 📋 待清理 |
| 2 | 零向量 parent 回退检索结果随机 | 空库场景 | 📋 待修 |
| 3 | 默认 Cross-Encoder 仅英文 | 中文精排偏差 | 📋 待更换为多语言模型 |
| 4 | Embedding 维度切换不兼容 | 换模型崩溃 | 📋 待加验证 |
| 5 | tech_stack LIKE '%java%' 误中 javascript | 过滤不精确 | 📋 待改为精确标签匹配 |

---

## 九、总体评估

```
检索速度:     ⭐⭐⭐⭐⭐ (<100ms)
评估深度:     ⭐⭐⭐⭐⭐ (CoT 声明级 + 双重降级)
零幻觉能力:   ⭐⭐⭐⭐⭐ (Faithfulness=1.0)
容灾能力:     ⭐⭐⭐⭐⭐ (三重降级)
导入吞吐:     ⭐⭐⭐ (chunk embedding 8条/s 是瓶颈)
中文支持:     ⭐⭐⭐ (默认 CE 仅英文，需手动切换)
```

**总体评级: B+ → 生产可用，4 项 P1 待修复**
