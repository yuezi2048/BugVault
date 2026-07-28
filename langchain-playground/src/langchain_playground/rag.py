"""
RAG 全链路 — 文档加载 → 分块 → 向量存储 → 检索 → 生成。

与 BugVault 自研 RAG 的对比要点：
┌──────────────────┬────────────────────────┬──────────────────────┐
│      环节         │  LangChain (本练习)     │  BugVault (自研)      │
├──────────────────┼────────────────────────┼──────────────────────┤
│ 文档加载           │  TextLoader / PyMuPDF   │  Markdown archive     │
│ 分块策略           │  RecursiveCharacter     │  父子分块(error_log+  │
│                  │  TextSplitter           │  semantic)            │
│ 向量库            │  Chroma (内存)          │  LanceDB (嵌入列式)   │
│ 嵌入模型          │  OpenAI API (远程)      │  fastembed (本地 ONNX) │
│ 检索方式          │  向量 ANN (默认)        │  向量 ANN + BM25 双路 │
│ 融合策略          │  无默认融合             │  RRF (k=60)           │
│ 重排序            │  无                    │  Cross-Encoder ONNX   │
│ 评估              │  无                    │  LLM-as-Judge 两阶段  │
└──────────────────┴────────────────────────┴──────────────────────┘

运行： uv run python -m langchain_playground.rag
"""

from pathlib import Path

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter

MODEL = "gpt-4o-mini"
EMBEDDING_MODEL = "text-embedding-3-small"


def format_docs(docs):
    """将检索结果格式化为上下文文本。"""
    return "\n\n---\n\n".join(d.docstring for d in docs)


def build_sample_docs():
    """用程序的 docstring 做示例文档，模拟文档加载。"""
    # 在实践中这里会用 TextLoader / DirectoryLoader 加载文件
    return [
        SimpleDoc(
            id="lcel",
            content="""
LangChain 的 LCEL（LangChain Expression Language）是一种声明式管道语法，
使用 | 运算符将组件串联为链。LCEL 支持 RunnableParallel 实现并行分支，
支持 RunnableBranch 实现条件路由。LCEL 的流式、异步、重试是内置的，
不需要额外编写胶水代码。
            """,
        ),
        SimpleDoc(
            id="rag",
            content="""
RAG（Retrieval-Augmented Generation）分三步走：
1. 文档加载与分块：将长文档切为合适大小的片段
2. 向量化与索引：用 embedding 模型将每个片段转为向量，存入向量库
3. 检索与生成：查询时用语义搜索找到最相关片段，注入 LLM 上下文生成回答
LangChain 通过 LCEL 将这四步串联为一条 chain，调用 .invoke() 即可执行。
            """,
        ),
        SimpleDoc(
            id="agent",
            content="""
LangChain Agent 的核心是 ReAct 循环：Thought（思考）→ Action（工具调用）
→ Observation（观察结果）→ 循环直到给出 Final Answer。
AgentExecutor 负责循环控制（最大迭代次数、错误处理），
Tool 是 Agent 调用外部能力的接口，需提供 name、description 和 func。
            """,
        ),
    ]


# ── 简单的文档容器 ──────────────────────────────────────────────
class SimpleDoc:
    def __init__(self, id: str, content: str):
        self.id = id
        self.page_content = content
        self.docstring = content.strip()[:100] + "…" if len(content) > 100 else content.strip()


# ── 1. 分块 ──────────────────────────────────────────────────────
def chunk_docs(raw_docs, chunk_size=200, chunk_overlap=20):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", "。", "，", " ", ""],
    )
    texts = [d.page_content for d in raw_docs]
    metadatas = [{"source": d.id} for d in raw_docs]
    chunks = splitter.create_documents(texts, metadatas)
    print(f"    分块: {len(raw_docs)} 篇 → {len(chunks)} 块")
    return chunks


# ── 2. 建索引 ────────────────────────────────────────────────────
def build_vectorstore(chunks):
    embeddings = OpenAIEmbeddings(model=EMBEDDING_MODEL)
    vectorstore = InMemoryVectorStore.from_documents(chunks, embeddings)
    print(f"    向量库: InMemoryVectorStore, {len(chunks)} 条索引")
    return vectorstore


# ── 3. RAG 链 ────────────────────────────────────────────────────
def build_rag_chain(vectorstore):
    prompt = ChatPromptTemplate.from_template(
        "基于以下上下文回答问题。如果上下文不足以回答，说「信息不足」。\n\n"
        "上下文：\n{context}\n\n"
        "问题：{question}"
    )
    model = ChatOpenAI(model=MODEL, temperature=0.1)

    # 检索器：top_k=2
    retriever = vectorstore.as_retriever(search_kwargs={"k": 2})

    # LCEL 链：隐式传入 question → 检索 → format → prompt → model → parser
    chain = (
        {"context": retriever | format_docs, "question": RunnablePassthrough()}
        | prompt
        | model
        | StrOutputParser()
    )
    return chain


# ── 主入口 ───────────────────────────────────────────────────────
if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    print("=" * 50)
    print("RAG 全链路演示")
    print("=" * 50)

    # Step 1: 加载
    print("\n[1/3] 加载示例文档…")
    docs = build_sample_docs()

    # Step 2: 分块 + 索引
    print("\n[2/3] 分块与向量化…")
    chunks = chunk_docs(docs)
    vectorstore = build_vectorstore(chunks)

    # Step 3: 检索与生成
    print("\n[3/3] 构建 RAG 链并提问…\n")
    chain = build_rag_chain(vectorstore)

    questions = [
        "LCEL 的 | 运算符是做什么的？",
        "RAG 的流程是什么样的？",
        "Agent 的 ReAct 循环是什么？",
    ]
    for q in questions:
        answer = chain.invoke(q)
        print(f"  Q: {q}")
        print(f"  A: {answer}\n")

    print("=" * 50)
    print("注意：BugVault 的 RAG 不仅做了这些，还加了")
    print("  - BM25 全文检索兜底（向量搜不到时走关键词）")
    print("  - RRF 融合排序（应对向量和关键词分数不可比的问题）")
    print("  - Cross-Encoder 重排序（在 top-20 候选上精排）")
    print("  - LLM-as-Judge 两阶段评测（量化检索质量）")
    print("  - 全本地 CPU 运行（不依赖外部 API）")
    print("=" * 50)
