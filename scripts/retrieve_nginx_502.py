#!/usr/bin/env python3
"""Retrieve Nginx 502 Bug with full pipeline tracing."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ['BUGVAULT_ENABLE_RAG_EVAL'] = 'true'

from bugvault.database.lancedb_client import LanceDBClient
from bugvault.services.embedding_svc import EmbeddingService
from bugvault.services.retrieval_svc import rerank, MIN_SEMANTIC_SCORE
from bugvault.services.rag_evaluator_svc import RAGEvaluator
from bugvault.config import settings

query = 'Nginx 502 Bad Gateway on high traffic'
SEP = '=' * 70

print(SEP)
print('🔍 BugVault 检索流程全追踪')
print('   查询: "%s"' % query)
print(SEP)

db = LanceDBClient(); db.initialize()
print('\n📊 数据库状态: %d 条记录' % db._table.count_rows())
print('   配置: top_k=%d, semantic_threshold=%.2f' % (settings.top_k, MIN_SEMANTIC_SCORE))

emb = EmbeddingService()
q_vec = emb.generate_embedding(query)
print('✅ 查询向量已生成 (dim=%d)' % len(q_vec))

# ── Step 1: ANN search ──
print('\n--- Step 1: ANN 向量搜索 ---')
raw = db.search(q_vec)
print('   原始召回: %d 条' % len(raw))
for i, r in enumerate(raw, 1):
    d = r.get('_distance', 0.0)
    print('   #%d: %s  (dist=%.4f)' % (i, r.get('bug_title','?')[:65], d))

# ── Step 2: Rerank with threshold ──
print('\n--- Step 2: 混合重排 (语义×时间衰减) ---')
print('   语义阈值: MIN_SEMANTIC_SCORE = %.2f' % MIN_SEMANTIC_SCORE)

# Show pre-filter detail
for r in raw:
    d = r.get('_distance', 0.0)
    semantic = max(0.0, min(1.0, 1.0 - d / 2.0))
    status = '✅ PASS' if semantic >= MIN_SEMANTIC_SCORE else '❌ DROPPED'
    print('   %s  semantic=%.4f  title=%s' % (
        status, semantic, r.get('bug_title','?')[:50]))

reranked = rerank(raw)
print('\n   重排后: %d 条通过阈值' % len(reranked))
for i, r in enumerate(reranked, 1):
    print('   #%d: %s' % (i, r.get('bug_title','?')[:65]))

# ── Step 3: RAG evaluation ──
print('\n--- Step 3: RAG 三轴评估 ---')
rag = RAGEvaluator()
if rag.enabled and rag.api_key:
    eval_result = rag.evaluate_sync(query, reranked)
    ok = eval_result.rag_confidence_score is not None
    print('   评估状态: %s' % ('✅ 成功' if ok else '⚠️ 降级'))
    if ok:
        print('   context_relevance:     %.1f/5.0' % eval_result.context_relevance)
        print('   faithfulness:          %.1f/5.0' % eval_result.faithfulness)
        print('   rag_confidence_score:  %.1f/10' % eval_result.rag_confidence_score)
        print('   justification:')
        for line in (eval_result.evaluation or '').split('. '):
            print('     · %s.' % line.strip().rstrip('.'))
    else:
        print('   (评估降级: %s)' % eval_result.evaluation)
else:
    print('   (RAG 评估未启用或未配置 API Key)')
    print('   enable_rag_eval=%s  api_key=%s' % (rag.enabled, bool(rag.api_key)))

# ── Step 4: Display results ──
print('\n' + SEP)
print('📋 最终检索结果 (%d 条)' % len(reranked))
print(SEP)
for i, r in enumerate(reranked, 1):
    print('\n--- Result #%d ---' % i)
    print('  Title:      %s' % r.get('bug_title','?'))
    print('  Project:    %s' % r.get('project_name','?'))
    print('  Tech Stack: %s' % r.get('tech_stack','?'))
    print('  Error:')
    for line in (r.get('error_log_snippet','') or '').split('\n')[:3]:
        print('    %s' % line)
    print('  Tried:')
    for line in (r.get('tried_methods','') or '').split('\n')[:3]:
        print('    %s' % line)
    print('  Solution:')
    for line in (r.get('final_solution','') or '').split('\n')[:3]:
        print('    %s' % line)
    rc = r.get('root_cause','')
    if rc:
        print('  Root Cause: %s' % rc[:120])
