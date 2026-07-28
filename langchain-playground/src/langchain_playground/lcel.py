"""
LCEL 基础链 — 掌握 LangChain 最核心的声明式管道语法。

知识点：
- ChatPromptTemplate: 消息模板占位
- ChatOpenAI: 模型调用封装
- StrOutputParser: 输出解析
- LCEL | 管道符串联
- RunnableParallel / RunnableBranch 分支

运行： uv run python -m langchain_playground.lcel
"""

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableParallel, RunnablePassthrough

MODEL = "gpt-4o-mini"

# ── 1. 基础链：Prompt → Model → Parser ──────────────────────────
def basic_chain():
    """最简单的 LCEL 链，理解 | 管道符的语义。"""
    prompt = ChatPromptTemplate.from_template("用{word}造一个句子，不超过15个字")
    model = ChatOpenAI(model=MODEL, temperature=0.7)
    chain = prompt | model | StrOutputParser()

    result = chain.invoke({"word": "递归"})
    print(f">>> basic_chain: {result}")
    return result


# ── 2. 多参数 + 结构化输出 ──────────────────────────────────────
def structured_chain():
    """带 system/user 双消息模板 + 多参数注入。"""
    prompt = ChatPromptTemplate.from_messages([
        ("system", "你是一个{role}。用专业但不晦涩的语言回答。"),
        ("human", "{question}"),
    ])
    model = ChatOpenAI(model=MODEL, temperature=0.3)
    chain = prompt | model | StrOutputParser()

    result = chain.invoke({
        "role": "后端架构师",
        "question": "解释 RRF（互惠排名融合）的原理，30 字内",
    })
    print(f">>> structured_chain: {result}")
    return result


# ── 3. 并行分支 + 合并 ──────────────────────────────────────────
def parallel_chain():
    """RunnableParallel 实现并行调用，模拟「多角度分析」场景。"""
    prompt_template = ChatPromptTemplate.from_template("{topic}的{aspect}是什么？用一句话回答")
    model = ChatOpenAI(model=MODEL, temperature=0.5)

    chain_a = prompt_template.partial(aspect="优点") | model | StrOutputParser()
    chain_b = prompt_template.partial(aspect="缺点") | model | StrOutputParser()

    parallel = RunnableParallel(
        pros=chain_a,
        cons=chain_b,
        topic=RunnablePassthrough(),  # 原样透传
    )

    result = parallel.invoke({"topic": "LangChain 框架"})
    print(f">>> parallel_chain:")
    print(f"    pros: {result['pros']}")
    print(f"    cons: {result['cons']}")
    return result


# ── 主入口 ───────────────────────────────────────────────────────
if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    print("=" * 50)
    print("1. Basic Chain — 单参数模板")
    basic_chain()
    print()

    print("2. Structured Chain — 多参数 + 角色注入")
    structured_chain()
    print()

    print("3. Parallel Chain — 并行分支")
    parallel_chain()
    print("=" * 50)
