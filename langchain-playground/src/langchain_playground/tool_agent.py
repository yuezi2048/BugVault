"""
Tool Calling + Agent — 自定义工具注册、AgentExecutor 循环、Human-in-the-Loop。

与 Invoice Manager 的 Agent 子系统对比：
┌──────────────────┬─────────────────────────┬──────────────────────┐
│      环节         │  LangChain (本练习)      │  Invoice (自研)       │
├──────────────────┼─────────────────────────┼──────────────────────┤
│ 工具定义           │  @tool 装饰器 + Schema   │  Pydantic + 注册表    │
│ 意图路由           │  LLM 自行选择            │  关键词路由 + Prompt  │
│ Agent 循环         │  AgentExecutor          │  AgentLoop (自研)     │
│ 循环上限           │  max_iterations 参数     │  max_iterations 硬限  │
│ 人工确认           │  需自行实现中断           │  HITL 中断-确认内置   │
│ 安全降级           │  无（框架层不提供）       │  Token 透传 + 降级    │
└──────────────────┴─────────────────────────┴──────────────────────┘

运行： uv run python -m langchain_playground.tool_agent
"""

from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain.agents import create_tool_calling_agent, AgentExecutor

MODEL = "gpt-4o-mini"

# ── 工具定义 ─────────────────────────────────────────────────────

@tool
def query_invoice(invoice_id: str) -> str:
    """根据发票号查询发票基本信息，返回 JSON 格式的发票数据。"""
    # 模拟数据库查询
    invoices = {
        "INV001": {"id": "INV001", "amount": 12800.00, "status": "已开票", "date": "2026-06-15"},
        "INV002": {"id": "INV002", "amount": 5600.00, "status": "待审核", "date": "2026-07-01"},
        "INV003": {"id": "INV003", "amount": 34200.00, "status": "已作废", "date": "2026-05-20"},
    }
    result = invoices.get(invoice_id)
    if result:
        return str(result)
    return f"未找到发票 {invoice_id}"


@tool
def check_risk_level(amount: float, industry: str = "") -> str:
    """根据金额和行业返回风险等级评估。高风险金额阈值：>=30000。"""
    if amount >= 30000:
        return f"高风险（金额 {amount} ≥ 30000，建议人工审核）"
    elif amount >= 10000:
        return f"中风险（金额 {amount} 在 10000-30000 之间，可自动通过但需抽查）"
    else:
        return f"低风险（金额 {amount} < 10000，自动通过）"


@tool
def approve_invoice(invoice_id: str, approver: str) -> str:
    """模拟执行发票审核通过操作。高风险发票需要人工确认。"""
    # 模拟：高风险场景需要人工确认
    risk_result = check_risk_level.invoke({"amount": 99999, "industry": ""})
    if "高风险" in risk_result:
        return (f"[需要人工确认] 发票 {invoice_id} 初步判断为高风险，"
                f"已提交 {approver} 人工审核队列。")
    return f"发票 {invoice_id} 已由 {approver} 审核通过。"


# ── Agent 构建 ───────────────────────────────────────────────────

def build_agent():
    """构建带工具调用能力的 Agent。"""
    tools = [query_invoice, check_risk_level, approve_invoice]

    prompt = ChatPromptTemplate.from_messages([
        ("system", "你是一个发票审核助手。使用工具查询信息，给出判断。高风险操作必须提示人工确认。"),
        ("human", "{input}"),
        ("placeholder", "{agent_scratchpad}"),
    ])

    model = ChatOpenAI(model=MODEL, temperature=0.1)
    agent = create_tool_calling_agent(model, tools, prompt)
    executor = AgentExecutor(
        agent=agent,
        tools=tools,
        max_iterations=5,           # 防死循环
        return_intermediate_steps=True,  # 记录决策链路
        handle_parsing_errors=True,      # 容错
        verbose=True,                    # 打印思考过程
    )
    return executor


# ── 加载 Prompt 模板 ─────────────────────────────────────────────
from langchain_core.prompts import ChatPromptTemplate


# ── 主入口 ───────────────────────────────────────────────────────
if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    print("=" * 50)
    print("Tool Calling + Agent 演示")
    print("=" * 50)

    agent = build_agent()

    scenarios = [
        "查询发票 INV001 的基本信息",
        "有一笔 45000 元的发票申请，评估风险等级",
        "查询发票 INV002，然后评估它的风险等级",
    ]

    for i, scenario in enumerate(scenarios, 1):
        print(f"\n[{i}] 场景：{scenario}")
        print("-" * 40)
        result = agent.invoke({"input": scenario})

        print(f"\n最终回答：{result['output']}")

        # 打印中间步骤（决策链路回溯）
        steps = result.get("intermediate_steps", [])
        if steps:
            print(f"\n决策链路 ({len(steps)} 步)：")
            for j, (action, observation) in enumerate(steps, 1):
                print(f"  Step {j}: {action.tool}({action.tool_input}) → {observation}")
            print()

    print("=" * 50)
    print("与 Invoice Manager 自研 Agent 的对比：")
    print("  LangChain 的优点：框架成熟、开箱即用、社区活跃")
    print("  自研方案的优点：HITL 内置、Token 透传解耦、降级策略灵活")
    print("  面试回答框架：两者都用过，根据场景选型——")
    print("  快速验证用 LangChain，生产级控制自研。")
    print("=" * 50)
