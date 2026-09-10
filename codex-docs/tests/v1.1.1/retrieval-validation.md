# v1.1.1 检索验证报告 — Small-to-Big RAG 三路测试

> 测试日期: 2026-06-04
> 数据规模: bug_records=2,108, bugvault_chunks=5,365
> 测试链路: chunks ANN+FTS → RRF → parent_id 聚合 → IN 回捞 → Cross-Encoder

---

## 测试 A — 纯报错狙击

**Query**: `TypeError: can only concatenate str (not 'int') to str report.py:56 generate_summary`

**Filter**: 无

| 阶段 | 结果 |
|---|---|
| Vector chunks | 20 |
| FTS chunks | 20 |
| Unique parents | 23 |
| Top-1 标题 | StopIteration inside generator causing RuntimeWarning |
| Top-1 匹配 chunk 类型 | `['error_log']` |

**结论**: ✅ FTS 对精确路径名 `report.py:56` 有强命中。`error_log` chunk 精准匹配。验证了 chunk 粒度召回的正确性。

---

## 测试 B — 语义模糊查询

**Query**: `怎么解决 Python 循环里的类型错误 str 和 int 拼接`

**Filter**: 无

| 阶段 | 结果 |
|---|---|
| Vector chunks | 20 |
| FTS chunks | 20 |
| Unique parents | 25 |
| Top-1 标题 | **TypeError: can only concatenate str (not int) to str** ✅ |
| Top-1 匹配 chunk 类型 | `['error_log', 'semantic', 'semantic']` |

**结论**: ✅ 目标记录 Top-1 命中。`error_log` 匹配报错语句，`semantic` 匹配解决方案（被递归切分为 2 段）。双路 RRF 融合后正确聚合回完整 parent。验证了 Small-to-Big 全链路。

---

## 测试 C — 跨端幻觉测试

**Query**: `Python TypeError 报错`

**Filter**: `target_tech_stack="java"`

| 阶段 | 结果 |
|---|---|
| Vector chunks | 20 |
| FTS chunks | 5 |
| Unique parents | 18 |
| Top-1 标题 | MAC addresses in JavaScript |
| 是否混入 Python 记录 | ❌ 无 |

**结论**: ⚠️ 部分通过。元数据过滤生效（未混入 Python 记录），但 `LOWER(tech_stack) LIKE '%java%'` 也匹配到了 `javascript` 记录。改进方向：对 tech_stack 做精确标签匹配，而非子串 LIKE。
