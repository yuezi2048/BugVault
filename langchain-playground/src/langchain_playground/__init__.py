"""LangChain 核心模块练习入口。

运行方式：
    uv run python -m langchain_playground.lcel          # LCEL 基础链
    uv run python -m langchain_playground.rag            # RAG 全链路
    uv run python -m langchain_playground.tool_agent     # Tool Calling + Agent
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
