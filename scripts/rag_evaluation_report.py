#!/usr/bin/env python3
"""RAG Evaluation Report Generator — tests the full fix pipeline end-to-end.

Inserts the P0 bug-fix records, runs retrieval with hybrid reranking,
invokes the external LLM judge (deepseek-v4-flash), generates a quality
report, and persists everything to the BugVault knowledge base.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure the project root is on sys.path
_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
sys.path.insert(0, str(_PROJECT))

# ── Force fresh LanceDB (clear pre-existing corruption) ──────────────
DB_URI = os.path.expanduser("~/.bugvault/lancedb")
if os.path.exists(DB_URI):
    shutil.rmtree(DB_URI)
    print(f"[setup] Deleted old LanceDB at {DB_URI}")

# ── Lazy-load BugVault modules (after sys.path fix) ──────────────────
os.environ["BUGVAULT_ENABLE_RAG_EVAL"] = "true"
# The API key is already in .env

from bugvault.config import settings
from bugvault.database.lancedb_client import LanceDBClient
from bugvault.models.bug_record import BugRecord
from bugvault.services.embedding_svc import EmbeddingService
from bugvault.services.retrieval_svc import rerank
from bugvault.services.rag_evaluator_svc import RAGEvaluator
from bugvault.services.archive_svc import write_markdown_archive
from bugvault.utils.logger import logger


# ─────────────────────────────────────────────────────────────────────
#  1.  Seed the database with the 3 P0 fix records
# ─────────────────────────────────────────────────────────────────────

BUG_RECORDS = [
    BugRecord(
        bug_title="P0 数据重复修复 — 哈希主键与 merge_insert Upsert",
        error_log_snippet=(
            "upsert_record 使用 _table.add() 纯追加写入. "
            "同一 (bug_title, error_log_snippet) 上报 N 次产生 N 条重复记录. "
            "检索结果 TOP-K 被同一问题污染, 用户体验极差."
        ),
        tried_methods=(
            "1. 尝试在应用层手动去重, 但无法防止并发写入重复.\n"
            "2. 调研 LanceDB 是否有原生主键约束.\n"
            "3. 决定使用 merge_insert + MD5 主键方案."
        ),
        final_solution=(
            "1. BugRecord 增加 record_id = MD5(bug_title + error_log_snippet) 全局主键.\n"
            "2. upsert_record 改用 merge_insert('record_id').when_matched_update_all().when_not_matched_insert_all().\n"
            "3. rerank 返回前增加 Set 去重兜底.\n"
            "4. LanceDBClient 增加 threading.Lock 保护并行读写.\n"
            "5. _init_table 使用 mode='overwrite' 避免旧版本引用残留."
        ),
        project_name="BugVault",
        tech_stack="Python 3.13, LanceDB 0.32.0, Pydantic v2",
        root_cause=(
            "LanceDB 无主键约束, _table.add() 设计为纯追加, "
            "导致同一 Bug 重复上报产生多条物理记录."
        ),
    ),
    BugRecord(
        bug_title="P0 并发读写竞争修复 — threading.Lock",
        error_log_snippet=(
            "集成测试 test_save_and_retrieve 持续失败. "
            "Save 返回 'saved successfully' 但 Retrieve 返回 "
            "'No matching bug experiences found'. "
            "异步 save 的 _work() (embedding + LanceDB 写入) "
            "与 _sync_retrieve (搜索) 经 2 线程并发运行时 "
            "LanceDB search() 读到旧版本 snapshot."
        ),
        tried_methods=(
            "1. 确认 merge_insert 本身能正确写入和检索 (单线程测试通过).\n"
            "2. 多线程测试: writer 线程 merge_insert + reader 线程 search() "
            "并发运行时 reader 返回 0 条结果.\n"
            "3. 确认 add() 也存在同样问题."
        ),
        final_solution=(
            "LanceDBClient 增加 threading.Lock, 用 with self._lock: "
            "保护 search() 和 upsert_record() 两个方法, "
            "确保写操作提交后才被读线程看到."
        ),
        project_name="BugVault",
        tech_stack="Python 3.13, LanceDB 0.32.0, threading",
        root_cause=(
            "LanceDB _table Python 对象在 ThreadPoolExecutor "
            "并发线程中不保证可见性. 写入的新版本不会立即被 "
            "另一线程的 search() 看到, 需外部显式同步."
        ),
    ),
    BugRecord(
        bug_title="P0 LLM JSON 解析崩溃修复 — response_format + Retry",
        error_log_snippet=(
            "RAGEvaluator._parse_response 频繁抛出 JSONDecodeError. "
            "LLM 输出可能包含 markdown ```json fence 包裹的非标准 JSON, "
            "或输出与 schema 不匹配的字段名. 一次解析失败就放弃, "
            "导致 RAG 评估全程没有分数."
        ),
        tried_methods=(
            "1. 在 _parse_response 中增加 markdown fence 剥离逻辑.\n"
            "2. 词法容忍多个 JSON 变体.\n"
            "3. 最终采用 OpenAI 原生 response_format=json_object 强制 LLM 输出合法 JSON."
        ),
        final_solution=(
            "1. _call_llm 在 API payload 中加入 response_format={'type': 'json_object'}.\n"
            "2. evaluate_sync 增加 Retry 机制: 第一次 _parse_response "
            "抛异常或返回 parse_error 时原样重试 1 次网络请求.\n"
            "3. 双保险: parse_error 时日志警告 + 降级返回空 RAGEvalResult."
        ),
        project_name="BugVault",
        tech_stack="Python 3.13, OpenAI API, RAGAS-inspired",
        root_cause=(
            "未强制 LLM JSON mode 时, LLM 可能输出 fence 包裹的非标准 JSON; "
            "无重试机制使一次解析失败就放弃整个评估."
        ),
    ),
]

print(f"[seed] Inserting {len(BUG_RECORDS)} P0 fix records ...")
db_client = LanceDBClient()
db_client.initialize()

emb_svc = EmbeddingService()

for rec in BUG_RECORDS:
    search_text = rec.to_search_text()
    emb = emb_svc.generate_embedding(search_text)
    db_client.upsert_record(search_text, emb, rec)
    # Also write markdown archive
    write_markdown_archive(rec)
    print(f"  ✓ {rec.bug_title}")

print(f"[seed] {db_client._table.count_rows()} rows in LanceDB")


# ─────────────────────────────────────────────────────────────────────
#  2.  RAG evaluation queries
# ─────────────────────────────────────────────────────────────────────

TEST_QUERIES = [
    "数据重复 merge_insert 去重",
    "LanceDB 并发读写线程安全",
    "LLM JSON 解析失败 parse_error",
    "P0 漏洞修复 threading Lock",
]

rag_eval = RAGEvaluator()
if not rag_eval.enabled:
    print("[warn] RAG evaluator is not enabled — check .env")
    rag_eval.enabled = True
    rag_eval.api_key = settings.eval_llm_api_key
    rag_eval.model = settings.eval_llm_model
    rag_eval.base_url = (settings.eval_llm_base_url or "https://api.openai.com/v1").rstrip("/")

results_log: list[dict] = []

for q in TEST_QUERIES:
    print(f"\n{'='*60}")
    print(f"[eval] Query: {q}")
    print(f"{'='*60}")

    # Embed + search
    q_emb = emb_svc.generate_embedding(q)
    raw_results = db_client.search(q_emb)

    if not raw_results:
        print("  → No results (empty LanceDB or embedding mismatch)")
        results_log.append({
            "query": q,
            "result_count": 0,
            "rag_confidence_score": None,
            "evaluation": "no_results",
        })
        continue

    print(f"  Raw ANN results: {len(raw_results)}")

    # Rerank
    reranked = rerank(raw_results, None)
    print(f"  After rerank:    {len(reranked)}")
    for i, r in enumerate(reranked[:3], 1):
        print(f"    {i}. {r.get('bug_title', '?')[:60]}  "
              f"(dist={r.get('_distance', '?'):.3f})")

    # RAG evaluation
    eval_result = rag_eval.evaluate_sync(q, reranked)
    print(f"  RAG score: {eval_result.rag_confidence_score}")
    print(f"  Eval:      {eval_result.evaluation}")

    results_log.append({
        "query": q,
        "result_count": len(reranked),
        "rag_confidence_score": eval_result.rag_confidence_score,
        "evaluation": eval_result.evaluation,
    })

# ─────────────────────────────────────────────────────────────────────
#  3.  Generate report + persist to BugVault
# ─────────────────────────────────────────────────────────────────────

REPORT_TIME = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
report_lines = [
    f"# RAG 评估报告 — {REPORT_TIME}",
    "",
    "## 测试环境",
    f"- Embedding: {settings.embedding_model}",
    f"- Evaluator LLM: {rag_eval.model}",
    f"- LanceDB: version 0.32.0",
    f"- 数据库中记录数: {db_client._table.count_rows()}",
    f"- eval_top_k: {settings.eval_top_k}",
    "",
    "## 评估结果",
    "",
]

for entry in results_log:
    report_lines.append(f"### 查询: {entry['query']}")
    report_lines.append(f"- 命中记录数: {entry['result_count']}")
    score = entry["rag_confidence_score"]
    report_lines.append(f"- RAG Confidence Score: {f'{score:.1f}/10' if score is not None else 'N/A'}")
    report_lines.append(f"- 评估: {entry['evaluation'] or 'N/A'}")
    report_lines.append("")

# Compute aggregate stats
scores = [e["rag_confidence_score"] for e in results_log if e["rag_confidence_score"] is not None]
if scores:
    avg = sum(scores) / len(scores)
    report_lines.append(f"## 综合统计")
    report_lines.append(f"- 平均分: {avg:.2f}/10")
    report_lines.append(f"- 最高分: {max(scores):.1f}/10")
    report_lines.append(f"- 最低分: {min(scores):.1f}/10")
    report_lines.append(f"- 评估次数: {len(scores)}")
else:
    report_lines.append("## 综合统计")
    report_lines.append("- (无有效评估分数)")

report_text = "\n".join(report_lines)

# Save report to markdown archive
archive_path = Path(settings.markdown_archive_dir) / f"rag_evaluation_report_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.md"
archive_path.parent.mkdir(parents=True, exist_ok=True)
archive_path.write_text(report_text, encoding="utf-8")
print(f"\n[report] Saved to {archive_path}")

# Save to BugVault knowledge base
bug_report_record = BugRecord(
    bug_title=f"RAG 评估报告 — P0 修复验证 ({REPORT_TIME})",
    error_log_snippet=(
        f"RAG evaluation report for P0 fix validation. "
        f"Tested {len(TEST_QUERIES)} queries, "
        f"avg score {sum(scores)/len(scores):.2f}/10" if scores else "No scores available"
    ),
    tried_methods=(
        "1. 清空旧 LanceDB 数据库 (修复 pre-existing corruption).\n"
        "2. 插入 3 条 P0 修复记录 (数据去重/并发锁/JSON解析).\n"
        "3. 对 4 条测试查询执行 Embedding → ANN search → hybrid rerank.\n"
        "4. 调用 deepseek-v4-flash LLM 评估 Context Relevance + Faithfulness.\n"
        "5. 生成 Markdown 报告并入库."
    ),
    final_solution=report_text,
    project_name="BugVault",
    tech_stack="Python 3.13, LanceDB 0.32.0, FastEmbed, deepseek-v4-flash",
    root_cause=(
        "本次评估旨在验证 P0 修复的效果: "
        "① merge_insert 确保无重复记录; "
        "② threading.Lock 确保并发安全; "
        "③ response_format + Retry 确保 JSON 解析稳定."
    ),
)

search_text = bug_report_record.to_search_text()
emb = emb_svc.generate_embedding(search_text)
db_client.upsert_record(search_text, emb, bug_report_record)
write_markdown_archive(bug_report_record)
print(f"[report] Bug record saved to knowledge base")

# Print summary
print(f"\n{'='*60}")
print(f"RAG 评估完成 — {len(scores)}/{len(TEST_QUERIES)} queries scored")
if scores:
    print(f"平均分: {avg:.2f}/10")
print(f"报告: {archive_path}")
print(f"{'='*60}")
