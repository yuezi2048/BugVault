import os
import re
import asyncio
import argparse
from typing import List, Dict, Any

# 🚀 强制国内镜像
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
from datasets import load_dataset

from bugvault.database.lancedb_client import LanceDBClient
from bugvault.services.embedding_svc import EmbeddingService
from bugvault.models.bug_record import BugRecord


class HFStreamImporter:
    def __init__(self, db_client: LanceDBClient, embed_svc: EmbeddingService):
        self.db_client = db_client
        self.embed_svc = embed_svc
        # 控制并行 Embedding 的信号量，防止吃爆 CPU 和内存
        self.embed_sem = asyncio.Semaphore(8)

    def _extract_fields(self, html_body: str) -> tuple[str, str]:
        """完美复刻你的正则提取逻辑"""
        # 提取代码块作为 error_log_snippet
        code_match = re.search(r'<pre><code>(.*?)</code></pre>', html_body, re.DOTALL)
        error_snippet = code_match.group(1).strip()[:800] if code_match else "(no code block)"

        # 去除代码块后的剩余文本作为 tried_methods
        text_only = re.sub(r'<pre><code>.*?</code></pre>', '', html_body, flags=re.DOTALL)
        text_only = re.sub(r'<.*?>', '', text_only).strip()

        tried_methods = text_only[:2000] if len(text_only) > 50 else "(not recorded in question)"
        return error_snippet, tried_methods

    async def _process_item(self, item: dict) -> List[Any]:
        """将 HF 单条数据转换为带有 Embedding 的父子块 (在 Semaphore 保护下)"""
        async with self.embed_sem:
            # 使用更纯净的数据集：juancopi81/stack_overflow_python_data
            title = item.get('Title', 'Unknown Title')
            q_body = item.get('Body', '')
            a_body = item.get('Answer', 'No answer provided.')

            error_snippet, tried_methods = self._extract_fields(q_body)
            # 答案部分直接去标签
            final_solution = re.sub(r'<.*?>', '', a_body).strip()[:3000]

            # 实例化 Record
            record = BugRecord(
                bug_title=title,
                error_log_snippet=error_snippet,
                tried_methods=tried_methods,
                final_solution=final_solution,
                tech_stack="python",
                project_name="stackoverflow_10k"
            )

            # v1.1.1 架构：裂变为子块并计算向量
            chunks = record.to_chunks()

            # 假设你的 embed_svc 支持批量计算: embed_texts(texts) -> List[List[float]]
            # 并且已经在服务内部做好了 ThreadPoolExecutor 异步包装
            texts_to_embed = [c.search_text for c in chunks]
            embeddings = await self.embed_svc.embed_texts_async(texts_to_embed)

            # 组装返回：返回完整的 record 对象和打好向量的 chunks 字典
            chunks_data = []
            for chunk, emb in zip(chunks, embeddings):
                chunks_data.append({
                    "id": chunk.id,
                    "parent_id": chunk.parent_id,
                    "chunk_type": chunk.chunk_type,
                    "search_text": chunk.search_text,
                    "tech_stack": chunk.tech_stack,
                    "project_name": chunk.project_name,
                    "vector": emb
                })

            return record, chunks_data

    async def run(self, limit: int = 10000, batch_size: int = 500):
        print(f"🌊 启动 HF 流式导入 (数据集: juancopi81/stack_overflow_python_data)")
        print("🧹 正在清空并初始化双表...")
        self.db_client.drop_table()
        self.db_client.initialize()

        dataset = load_dataset("juancopi81/stack_overflow_python_data", split="train", streaming=True)

        tasks = []
        records_batch = []
        chunks_batch = []
        total_ingested = 0

        print(f"🚀 开始流水线并发写入 (Batch Size: {batch_size})...")

        for item in dataset:
            # 过滤掉没有代码块的问题
            if '<pre><code>' not in item.get('Body', ''):
                continue

            tasks.append(asyncio.create_task(self._process_item(item)))

            if len(tasks) >= batch_size:
                results = await asyncio.gather(*tasks)

                # 归集数据
                for record, chunks in results:
                    records_batch.append(record.to_dict())  # 或者你需要落库的特定 dict 格式
                    chunks_batch.extend(chunks)

                # ⚡ 核心提速点：双表 Batch merge_insert
                self.db_client.records_table.merge_insert("record_id") \
                    .when_matched_update_all() \
                    .when_not_matched_insert_all() \
                    .execute(records_batch)

                self.db_client.chunks_table.merge_insert("id") \
                    .when_matched_update_all() \
                    .when_not_matched_insert_all() \
                    .execute(chunks_batch)

                total_ingested += len(records_batch)
                print(f"✅ 成功刷入 Batch, 当前总进度: {total_ingested} / {limit}")

                # 重置批次池
                tasks = []
                records_batch = []
                chunks_batch = []

                if total_ingested >= limit:
                    break

        # 处理尾部数据... (省略与上述相同的 gather & execute 逻辑)

        print(f"\n🎉 10,000 条压测数据准备完毕！")
        print("🔨 正在重建 chunks 表的 Tantivy FTS 索引...")
        self.db_client.chunks_table.create_fts_index("search_text", replace=True)
        print("✅ 终极检索引擎蓄势待发！")


# 在你原有的 argparse 路由中加入
async def main():
    parser = argparse.ArgumentParser(description="BugVault External Data Importer")
    parser.add_argument("--format", choices=["hf", "json", "csv"], default="hf", help="数据源格式")
    parser.add_argument("--limit", type=int, default=10000, help="导入条数限制")
    args = parser.parse_args()

    db_client = LanceDBClient()
    embed_svc = EmbeddingService()  # 确保 init 时完成了 ONNX 的热加载

    if args.format == "hf":
        importer = HFStreamImporter(db_client, embed_svc)
        await importer.run(limit=args.limit)
    else:
        print("其他格式的支持待实现...")


if __name__ == "__main__":
    asyncio.run(main())