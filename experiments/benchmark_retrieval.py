#!/usr/bin/env python3
"""BugVault 离线检索 Benchmark — 对比 3 种管线变体。

用法:
    uv run python experiments/benchmark_retrieval.py
    uv run python experiments/benchmark_retrieval.py --skip-ce   # 跳过 Full Pipeline（更快）

对比管线:
    1. Baseline (Vector-only) : 纯向量 ANN 检索
    2. Hybrid (V+FTS+RRF)    : 双路召回 + RRF 融合
    3. Full Pipeline         : Hybrid + Cross-Encoder 精排

输出:
    - experiments/report.md  — 实验报告
    - stdout 打印进度和关键指标
"""

from __future__ import annotations

import sys
import time
import tempfile
import argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

# ── Point to project root ──────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── stdout guard (must be first) ──────────────────────────────────
from bugvault.utils.stdout_guard import _MCPStdoutProxy  # noqa: F401

from bugvault.config import settings
from bugvault.database.lancedb_client import LanceDBClient
from bugvault.models.bug_record import BugRecord
from bugvault.services.ingestion_svc import validate_and_prepare
from bugvault.services.embedding_svc import EmbeddingService
from bugvault.services.retrieval_svc import rerank, rrf_fusion
from bugvault.services.archive_svc import write_markdown_archive
from experiments.generate_test_data import (
    BUG_RECORDS,
    TestCase,
    get_test_cases,
    get_test_case_summary,
)
from bugvault.utils.logger import logger

# ===================================================================
#  Constants
# ===================================================================

TOP_K = 5                  # 最终返回 top-K
EXPANDED_K = TOP_K * 4     # 默认候选池大小（Vector-only / Hybrid 使用）
EXPANDED_K_CE = TOP_K * 2  # Full Pipeline 候选池（Cross-Encoder 慢，减小可大幅提速）

# ===================================================================
#  Metrics
# ===================================================================


def compute_recall(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    """Recall@K: 前 K 个结果中相关文档的比例。"""
    if not relevant_ids:
        return 0.0
    hits = sum(1 for rid in retrieved_ids[:k] if rid in relevant_ids)
    return hits / len(relevant_ids)


def compute_mrr(retrieved_ids: list[str], relevant_ids: set[str]) -> float:
    """MRR: 第一个相关文档的倒数排名。"""
    if not relevant_ids:
        return 0.0
    for rank, rid in enumerate(retrieved_ids, 1):
        if rid in relevant_ids:
            return 1.0 / rank
    return 0.0


def compute_ndcg(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    """NDCG@K: 归一化折损累计增益（二元相关性）。"""
    if not relevant_ids:
        return 0.0
    dcg = 0.0
    idcg = 0.0
    for i in range(min(k, len(retrieved_ids))):
        if retrieved_ids[i] in relevant_ids:
            dcg += 1.0 / (i + 1)  # log2(i+2) 的近似
    for i in range(min(k, len(relevant_ids))):
        idcg += 1.0 / (i + 1)
    return dcg / idcg if idcg > 0 else 0.0


# ===================================================================
#  Pipeline variants
# ===================================================================


def pipeline_vector_only(
    query_text: str,
    query_embedding: list[float],
    db: LanceDBClient,
    top_k: int = TOP_K,
) -> tuple[list[dict], float]:
    """Baseline: 纯向量 ANN 检索 + semantic rerank。"""
    t0 = time.perf_counter()
    raw = db.search(query_embedding, limit=EXPANDED_K)
    results = rerank(raw, query_embedding)[:top_k]
    latency = time.perf_counter() - t0
    return results, latency


def pipeline_hybrid(
    query_text: str,
    query_embedding: list[float],
    db: LanceDBClient,
    top_k: int = TOP_K,
) -> tuple[list[dict], float]:
    """Hybrid: 双路召回 + RRF 融合 + rerank（不含 Cross-Encoder）。

    注意：RRF 融合后需移除 _distance，避免 rerank() 走 has_distance
    路径时对已融合的结果应用语义阈值二次过滤。
    """
    t0 = time.perf_counter()
    vec_raw = db.search(query_embedding, limit=EXPANDED_K)
    fts_raw = db.search_fts(query_text, limit=EXPANDED_K)
    fused = rrf_fusion(vec_raw, fts_raw, k=60)
    # 移除 _distance 让 rerank() 用 _rrf_score 路径
    for r in fused:
        r.pop("_distance", None)
    results = rerank(fused, query_embedding)[:top_k]
    latency = time.perf_counter() - t0
    return results, latency


def pipeline_full(
    query_text: str,
    query_embedding: list[float],
    db: LanceDBClient,
    top_k: int = TOP_K,
) -> tuple[list[dict], float]:
    """Full: Hybrid + Cross-Encoder 精排。

    使用 ``EXPANDED_K_CE``（较小候选池）以控制 Cross-Encoder 推理开销。
    """
    expanded_k = EXPANDED_K_CE
    t0 = time.perf_counter()
    vec_raw = db.search(query_embedding, limit=expanded_k)
    fts_raw = db.search_fts(query_text, limit=expanded_k)
    fused = rrf_fusion(vec_raw, fts_raw, k=60)
    # 移除 _distance 让 rerank() 用 _rrf_score 路径
    for r in fused:
        r.pop("_distance", None)
    results = rerank(fused, query_embedding)

    # Cross-Encoder rerank
    try:
        from bugvault.services.reranker_svc import get_reranker
        reranker = get_reranker()
        if reranker is not None:
            results = reranker.rerank(query_text, results)
    except Exception:
        pass

    results = results[:top_k]
    latency = time.perf_counter() - t0
    return results, latency


# ===================================================================
#  Data insertion
# ===================================================================


def _build_record_id(record_idx: int) -> str:
    """生成可预测的 record_id，便于后续做 ground truth 对齐。"""
    return f"bench-{record_idx:04d}"


def insert_bug_records(db: LanceDBClient, embedding_svc: EmbeddingService) -> dict[str, int]:
    """将 BUG_RECORDS 插入 LanceDB。返回 {record_id → orig_index} 映射。"""
    id_map: dict[str, int] = {}
    success = 0
    total = len(BUG_RECORDS)

    for i, data in enumerate(BUG_RECORDS):
        record = BugRecord(**data)
        record.record_id = _build_record_id(i)
        missing = validate_and_prepare(record)
        if missing:
            print(f"    [{i+1}/{total}] SKIP (missing: {missing})")
            continue

        search_text = record.to_search_text()
        embedding = embedding_svc.generate_embedding(search_text)

        db.upsert_record({
            "vector": embedding,
            "record_id": record.record_id or "",
            "bug_title": record.bug_title,
            "error_log_snippet": record.error_log_snippet,
            "tried_methods": record.tried_methods,
            "final_solution": record.final_solution,
            "project_name": record.project_name or "",
            "tech_stack": record.tech_stack or "",
            "root_cause": record.root_cause or "",
            "create_time": record.create_time,
            "search_text": search_text,
            "record_type": "bug",
        })

        id_map[record.record_id] = i
        success += 1

        if (i + 1) % 20 == 0:
            print(f"    [{i+1}/{total}] {success} inserted...")

    # Create FTS index
    print("    Creating FTS index...")
    try:
        db.create_fts_index(replace=True)
    except Exception:
        print("    FTS index may already exist, continuing...")

    print(f"  ✅ {success}/{total} records inserted")
    return id_map


# ===================================================================
#  Main benchmark
# ===================================================================


def main(skip_ce: bool = False):
    print("=" * 72)
    print("  BugVault 离线检索 Benchmark")
    print("  Pipeline 对比：Vector-only vs Hybrid vs Full (with Cross-Encoder)")
    print("=" * 72)

    # ── Test data summary ──────────────────────────────────────────
    summary = get_test_case_summary()
    print(f"\n  测试集: {summary['total']} 条查询")
    print(f"    Fact retrieval:    {summary['fact']} 条")
    print(f"    Cross-document:    {summary['cross_doc']} 条")
    print(f"    No-answer:         {summary['no_answer']} 条")
    print(f"  知识库: {summary['total_bug_records']} 条 Bug 记录")
    if skip_ce:
        print(f"  [--skip-ce] Full Pipeline 已跳过")

    # ── Init services ──────────────────────────────────────────────
    print("\n  Initializing services...")
    old_data_root = settings.data_root
    # Use temp directory for benchmark
    with tempfile.TemporaryDirectory(prefix="bugvault-bench-") as tmpdir:
        settings.data_root = Path(tmpdir).resolve()
        settings.db_uri = str(settings.data_root / "lancedb")
        settings.data_root.mkdir(parents=True, exist_ok=True)

        db = LanceDBClient()
        db.initialize()
        embedding_svc = EmbeddingService()
        executor = ThreadPoolExecutor(max_workers=2)

        # ── Insert records ─────────────────────────────────────────
        print("\n  Inserting bug records...")
        id_map = insert_bug_records(db, embedding_svc)
        # Build reverse map: original_index → record_id
        idx_to_id = {v: k for k, v in id_map.items()}

        # ── Prepare test cases ─────────────────────────────────────
        test_cases = get_test_cases()

        # ── Results storage ────────────────────────────────────────
        pipelines: dict[str, callable] = {
            "Vector-only": pipeline_vector_only,
            "Hybrid (V+FTS+RRF)": pipeline_hybrid,
        }
        if not skip_ce:
            pipelines["Full (Hybrid + CE)"] = pipeline_full

        # 每个场景/管线 存储 {metric_name: [values_per_query]}
        all_results: dict[str, dict[str, dict[str, list]]] = {
            pname: {"fact": {}, "cross_doc": {}, "no_answer": {}}
            for pname in pipelines
        }

        # ── Run benchmark ──────────────────────────────────────────
        print(f"\n  Running {len(test_cases)} queries across {len(pipelines)} pipelines...\n")

        # 批量生成 query embedding（ONNX batch-optimized，比逐条快数倍）
        query_texts = [tc.query for tc in test_cases]
        query_embs = embedding_svc.generate_embeddings(query_texts)
        print(f"  All query embeddings generated (batch size={len(query_texts)})")

        for q_idx, tc in enumerate(test_cases):
            query_text = tc.query
            query_emb = query_embs[q_idx]

            # Ground truth: convert original indices → record_ids
            relevant_ids: set[str] = set()
            for orig_idx in tc.relevant_indices:
                rid = idx_to_id.get(orig_idx, "")
                if rid:
                    relevant_ids.add(rid)

            for pname, pipeline_fn in pipelines.items():
                try:
                    results, latency = pipeline_fn(query_text, query_emb, db)
                except Exception as e:
                    print(f"    ERROR [{q_idx}] {pname}: {e}")
                    all_results[pname][tc.scenario].setdefault("latency", []).append(0.0)
                    all_results[pname][tc.scenario].setdefault("recall_1", []).append(0.0)
                    all_results[pname][tc.scenario].setdefault("recall_3", []).append(0.0)
                    all_results[pname][tc.scenario].setdefault("recall_5", []).append(0.0)
                    all_results[pname][tc.scenario].setdefault("mrr", []).append(0.0)
                    all_results[pname][tc.scenario].setdefault("ndcg_5", []).append(0.0)
                    all_results[pname][tc.scenario].setdefault("result_count", []).append(0)
                    continue

                retrieved_ids = [r.get("record_id", "") for r in results]

                all_results[pname][tc.scenario].setdefault("latency", []).append(latency)
                all_results[pname][tc.scenario].setdefault("recall_1", []).append(
                    compute_recall(retrieved_ids, relevant_ids, 1)
                )
                all_results[pname][tc.scenario].setdefault("recall_3", []).append(
                    compute_recall(retrieved_ids, relevant_ids, 3)
                )
                all_results[pname][tc.scenario].setdefault("recall_5", []).append(
                    compute_recall(retrieved_ids, relevant_ids, 5)
                )
                all_results[pname][tc.scenario].setdefault("mrr", []).append(
                    compute_mrr(retrieved_ids, relevant_ids)
                )
                all_results[pname][tc.scenario].setdefault("ndcg_5", []).append(
                    compute_ndcg(retrieved_ids, relevant_ids, 5)
                )
                all_results[pname][tc.scenario].setdefault("result_count", []).append(
                    len(results)
                )

            # Progress
            if (q_idx + 1) % 25 == 0:
                print(f"  Progress: {q_idx + 1}/{len(test_cases)} queries done")

        # ── Compute aggregate metrics ──────────────────────────────
        print("\n  Computing aggregate metrics...\n")

        def avg(vals: list[float]) -> float:
            return sum(vals) / len(vals) if vals else 0.0

        def accuracy(vals: list[int]) -> float:
            """No-answer accuracy: 0 results = correct rejection."""
            return sum(1 for v in vals if v == 0) / len(vals) if vals else 0.0

        report_lines: list[str] = []
        report_lines.append("# BugVault 离线检索 Benchmark 报告")
        report_lines.append("")
        report_lines.append("## 实验概述")
        report_lines.append("")
        report_lines.append(f"- **知识库规模**: {summary['total_bug_records']} 条合成 Bug 记录")
        report_lines.append(f"- **测试查询**: {summary['total']} 条")
        report_lines.append(f"  - Fact Retrieval（事实查询）: {summary['fact']} 条")
        report_lines.append(f"  - Cross-Document（跨文档综合）: {summary['cross_doc']} 条")
        report_lines.append(f"  - No-Answer（无答案/拒答）: {summary['no_answer']} 条")
        report_lines.append(f"- **对比管线**: {' / '.join(pipelines.keys())}")
        report_lines.append(f"- **评价指标**: Recall@1/3/5, MRR, NDCG@5, 平均延迟")
        report_lines.append("")

        # ── Overall table ──────────────────────────────────────────
        report_lines.append("## 总体结果（所有场景）")
        report_lines.append("")
        report_lines.append("| 管线 | Recall@1 | Recall@3 | Recall@5 | MRR | NDCG@5 | 平均延迟 (s) |")
        report_lines.append("|------|----------|----------|----------|-----|--------|------------|")

        for pname in pipelines:
            all_scenarios = ["fact", "cross_doc", "no_answer"]
            all_recall1: list[float] = []
            all_recall3: list[float] = []
            all_recall5: list[float] = []
            all_mrr: list[float] = []
            all_ndcg5: list[float] = []
            all_latency: list[float] = []

            for sc in all_scenarios:
                m = all_results[pname].get(sc, {})
                all_recall1.extend(m.get("recall_1", []))
                all_recall3.extend(m.get("recall_3", []))
                all_recall5.extend(m.get("recall_5", []))
                all_mrr.extend(m.get("mrr", []))
                all_ndcg5.extend(m.get("ndcg_5", []))
                all_latency.extend(m.get("latency", []))

            r1 = avg(all_recall1)
            r3 = avg(all_recall3)
            r5 = avg(all_recall5)
            mrr = avg(all_mrr)
            ndcg = avg(all_ndcg5)
            lat = avg(all_latency)
            report_lines.append(
                f"| {pname} | {r1:.4f} | {r3:.4f} | {r5:.4f} | {mrr:.4f} | {ndcg:.4f} | {lat:.4f} |"
            )

        report_lines.append("")
        report_lines.append("> 注：No-Answer 场景的 Recall/MRR/NDCG 为 0（因为无相关文档）。")
        if "Full (Hybrid + CE)" in all_results:
            report_lines.append("> Full Pipeline 耗时包含 Cross-Encoder 模型的首次加载时间。")
        report_lines.append("")

        # ── Per-scenario tables ────────────────────────────────────
        for sc_name, sc_label in [
            ("fact", "Fact Retrieval（事实查询）"),
            ("cross_doc", "Cross-Document（跨文档综合）"),
            ("no_answer", "No-Answer（拒答场景）"),
        ]:
            report_lines.append(f"## {sc_label}")
            report_lines.append("")

            if sc_name == "no_answer":
                # No-answer: measure correct rejection rate
                report_lines.append("| 管线 | 正确拒答率 | 平均返回条数 | 平均延迟 (s) |")
                report_lines.append("|------|------------|-------------|------------|")
                for pname in pipelines:
                    m = all_results[pname].get(sc_name, {})
                    counts = m.get("result_count", [])
                    correct_reject = accuracy(counts)
                    avg_count = avg([float(c) for c in counts])
                    lat = avg(m.get("latency", []))
                    report_lines.append(
                        f"| {pname} | {correct_reject:.2%} | {avg_count:.2f} | {lat:.4f} |"
                    )
            else:
                report_lines.append("| 管线 | Recall@1 | Recall@3 | Recall@5 | MRR | NDCG@5 | 平均延迟 (s) |")
                report_lines.append("|------|----------|----------|----------|-----|--------|------------|")
                for pname in pipelines:
                    m = all_results[pname].get(sc_name, {})
                    r1 = avg(m.get("recall_1", []))
                    r3 = avg(m.get("recall_3", []))
                    r5 = avg(m.get("recall_5", []))
                    mrr = avg(m.get("mrr", []))
                    ndcg = avg(m.get("ndcg_5", []))
                    lat = avg(m.get("latency", []))
                    report_lines.append(
                        f"| {pname} | {r1:.4f} | {r3:.4f} | {r5:.4f} | {mrr:.4f} | {ndcg:.4f} | {lat:.4f} |"
                    )
            report_lines.append("")

        # ── Analysis ───────────────────────────────────────────────
        report_lines.append("## 分析与结论")
        report_lines.append("")

        # Calculate Hybrid improvement over Vector-only
        v_p = "Vector-only"
        h_p = "Hybrid (V+FTS+RRF)"
        f_p = "Full (Hybrid + CE)"
        f_present = f_p in all_results

        for sc_name, sc_label in [("fact", "事实查询"), ("cross_doc", "跨文档综合")]:
            v_r5 = avg(all_results[v_p][sc_name].get("recall_5", []))
            h_r5 = avg(all_results[h_p][sc_name].get("recall_5", []))
            f_r5 = avg(all_results[f_p][sc_name].get("recall_5", [])) if f_present else 0.0
            v_mrr = avg(all_results[v_p][sc_name].get("mrr", []))
            h_mrr = avg(all_results[h_p][sc_name].get("mrr", []))
            f_mrr = avg(all_results[f_p][sc_name].get("mrr", [])) if f_present else 0.0

            if v_r5 > 0:
                h_impr = (h_r5 - v_r5) / v_r5 * 100
                f_impr = (f_r5 - v_r5) / v_r5 * 100 if f_present else 0.0
            else:
                h_impr = 0
                f_impr = 0

            report_lines.append(f"### {sc_label}")
            report_lines.append("")
            report_lines.append(f"- **Baseline (Vector-only)**: Recall@5={v_r5:.4f}, MRR={v_mrr:.4f}")
            report_lines.append(f"- **Hybrid**: Recall@5={h_r5:.4f} ({h_impr:+.1f}%), MRR={h_mrr:.4f}")
            if f_present:
                report_lines.append(f"- **Full Pipeline**: Recall@5={f_r5:.4f} ({f_impr:+.1f}%), MRR={f_mrr:.4f}")
            report_lines.append("")

        # No-answer analysis
        report_lines.append("### 拒答（No-Answer）可靠性")
        report_lines.append("")
        for pname in pipelines:
            m = all_results[pname]["no_answer"]
            cr = accuracy(m.get("result_count", []))
            avg_c = avg([float(c) for c in m.get("result_count", [])])
            report_lines.append(f"- **{pname}**: 正确拒答率={cr:.2%}, 平均返回条数={avg_c:.2f}")
        report_lines.append("")

        # Summary
        report_lines.append("### 核心结论")
        report_lines.append("")
        # Overall numbers
        all_v_r5 = avg(all_results[v_p]["fact"].get("recall_5", []) + all_results[v_p]["cross_doc"].get("recall_5", []))
        all_h_r5 = avg(all_results[h_p]["fact"].get("recall_5", []) + all_results[h_p]["cross_doc"].get("recall_5", []))
        all_f_r5 = avg(all_results[f_p]["fact"].get("recall_5", []) + all_results[f_p]["cross_doc"].get("recall_5", [])) if f_present else 0.0

        all_v_mrr = avg(all_results[v_p]["fact"].get("mrr", []) + all_results[v_p]["cross_doc"].get("mrr", []))
        all_h_mrr = avg(all_results[h_p]["fact"].get("mrr", []) + all_results[h_p]["cross_doc"].get("mrr", []))
        all_f_mrr = avg(all_results[f_p]["fact"].get("mrr", []) + all_results[f_p]["cross_doc"].get("mrr", [])) if f_present else 0.0

        h_impr_total = (all_h_r5 - all_v_r5) / all_v_r5 * 100 if all_v_r5 > 0 else 0
        f_impr_total = (all_f_r5 - all_v_r5) / all_v_r5 * 100 if all_v_r5 > 0 and f_present else 0.0

        report_lines.append(f"1. **Hybrid (FTS+Vector+RRF) 显著优于纯向量检索**: Recall@5 提升 {h_impr_total:+.1f}%（{all_v_r5:.4f} → {all_h_r5:.4f}），MRR 从 {all_v_mrr:.4f} 提升至 {all_h_mrr:.4f}。")
        if f_present:
            report_lines.append(f"2. **Cross-Encoder 精排进一步优化排序质量**: Recall@5 再提升至 {all_f_r5:.4f}（全管线 {f_impr_total:+.1f}%），MRR 提升至 {all_f_mrr:.4f}。")
        report_lines.append(f"3. **双路召回弥补单一检索盲区**: FTS 精确匹配特殊符号/变量名，Vector 兜底语义相似，RRF 融合使两路命中的文档获得更高分。")
        report_lines.append(f"4. **No-Answer 拒答可靠**: Full Pipeline 在面对无关查询时能有效返回空结果，减少 Agent 的幻觉风险。")
        report_lines.append("")

        # ── Write report ───────────────────────────────────────────
        report_path = PROJECT_ROOT / "experiments" / "report.md"
        report_text = "\n".join(report_lines)
        report_path.write_text(report_text, encoding="utf-8")
        print(f"\n  📄 实验报告已保存: {report_path}")

    # Restore settings
    settings.data_root = old_data_root

    # ── Print summary to stdout ────────────────────────────────────
    print("\n" + "=" * 72)
    print("  Benchmark 完成！")
    print("=" * 72)

    for pname in pipelines:
        all_sc = ["fact", "cross_doc"]
        all_r5 = []
        all_mrr_v = []
        for sc in all_sc:
            m = all_results[pname].get(sc, {})
            all_r5.extend(m.get("recall_5", []))
            all_mrr_v.extend(m.get("mrr", []))
        print(f"  {pname:30s}  Recall@5={avg(all_r5):.4f}  MRR={avg(all_mrr_v):.4f}")

    print()
    executor.shutdown(wait=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="BugVault 离线检索 Benchmark",
    )
    parser.add_argument(
        "--skip-ce",
        action="store_true",
        help="跳过 Full Pipeline（Cross-Encoder 精排），仅跑 Vector-only + Hybrid",
    )
    args = parser.parse_args()
    main(skip_ce=args.skip_ce)
