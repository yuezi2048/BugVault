# LangChain 动手练习 — 总结与简历话术

> 配套代码见 `src/langchain_playground/`
> 运行前配 `.env`，执行 `uv sync` 安装依赖

---

## 一、做了什么

| 模块 | 文件 | 核心内容 | 与自研方案的对比点 |
|------|------|---------|------------------|
| **LCEL 基础链** | `lcel.py` | 单参数链、多参数角色注入、并行分支 | BugVault 的 MCP 工具链是手动编排的，LCEL 的 `\|` 管道符是 LangChain 独有的声明式语法 |
| **RAG 全链路** | `rag.py` | 文档加载→RecursiveCharacter 分块→向量化→检索→生成 | LangChain 用 Chroma + OpenAI Embeddings（远程 API），BugVault 用 LanceDB + fastembed（本地 ONNX），且多了 BM25 + RRF + Cross-Encoder |
| **Tool Calling + Agent** | `tool_agent.py` | @tool 注册、create_tool_calling_agent、AgentExecutor 循环 | Invoice Agent 自研了 AgentLoop 状态机 + Token 透传解耦，LangChain 的 AgentExecutor 是黑盒但开箱即用 |

---

## 二、关键认知（面试会问）

### Q: LangChain 和自研方案各自的优缺点？

```
LangChain 的优点：
  - 开箱即用：5 行代码搭好 RAG chain，适合快速原型
  - 社区强大：LCEL / Agent / Tool Calling 都有成熟实现
  - 生态丰富：Chroma / Pinecone / HuggingFace 等 100+ 集成

LangChain 的缺点：
  - 抽象层太厚：debug 困难，不确定底层调了什么 API
  - 自定义不灵活：Cross-Encoder 重排序、时间衰减这些不好加
  - 依赖外部 API：默认 OpenAI Embeddings 是远程调用

自研方案（BugVault / Invoice）的优点：
  - 完全可控制：每步都自己写，知道每行代码在干什么
  - 深度优化：BM25 全文兜底、RRF 融合、时间衰减、技术栈过滤
  - 本地优先：零外部 API，数据不出本机

自研方案的缺点：
  - 开发周期长：BugVault 写了 178 个测试才稳定
  - 维护成本高：LangChain 社区帮你踩过的坑要自己再踩一遍
```

### Q: 什么场景用 LangChain，什么场景自研？

```
快速验证 / PoC / 非核心链路 → LangChain（1 天出活）
生产系统 / 核心链路 / 需要深度定制 → 自研（但要保证测试覆盖）
最佳实践：用 LangChain 做原型验证，效果确认后再决定是否自研
```

---

## 三、简历话术

### 在原有「核心技能」中新增/调整

```
旧：
  [了解] LangChain / Dify 等编排框架

新：
  AI Agent & RAG 架构：自研 MCP 服务端 + AgentLoop + 全链路混合检索……
  **同时具备 LangChain 框架应用能力：LCEL 声明式管道、Tool Calling Agent 编排、
  基于 LangChain 的 RAG 原型搭建，可在框架与自研方案之间根据场景灵活选型。**
```

### 面试中提及 LangChain 的最佳时机

不要主动说，等面试官问。3 种被问到的情况及回应方式：

**情况 1：「你的 RAG 为什么不用 LangChain 而是自己写？」**

> 我用过 LangChain 搭 RAG 原型（2 小时就能跑通），但在 BugVault 这个场景里我需要三个 LangChain 做不了的事情：① BM25 全文检索兜底（向量搜不到时走关键词）；② Cross-Encoder 重排序（LanceDB 的 ANN 只做召回，不做精排）；③ 全本地零外部 API 运行（LangChain 默认走 OpenAI Embeddings）。所以我选择在 LangChain 原型验证后自研核心链路，但工具定义和 Agent 循环这些有现成模式的部分参考了 LangChain 的设计。

**情况 2：「你对 LangChain 了解多少？」**

> 我最近专门搭了一个 LangChain 练习项目跑了三个模块：LCEL 声明式管道（含 RunnableParallel 并行分支）、RAG 全链路（Document Loader → Text Splitter → Chroma → RetrievalQA）、Tool Calling Agent（@tool 注册 + AgentExecutor 循环控制）。我的理解是 LangChain 强在开箱即用的生态，弱在深层定制的灵活性——所以面试不同公司的岗位时，我会根据 JD 侧重点灵活选择技术路线。

**情况 3：「你用过 LangChain 的哪个版本？有什么坑？」**

> 我用的是 0.3.x。一个坑是 create_tool_calling_agent 在 model 不支持 tool calling 时会静默失败（连警告都没有），加 handle_parsing_errors=True 也只能兜住部分情况。另一个是 AgentExecutor 的 verbose=True 打印的内容对 debug 很有用，但生产环境需要自己封装日志。这些都是小坑，不影响 LangChain 做原型验证的价值。

---

## 四、面试官可能的追问（准备好这些，LangChain 这块就不会穿帮）

| 追问 | 你该回答的关键词 |
|------|----------------|
| LCEL 的 `|` 和 `pipe()` 有什么区别？ | `|` 是运算符重载，`pipe()` 是方法调用，两者等价 |
| RunnableParallel 和 RunnableBranch 各用在什么场景？ | Parallel：多角度分析、多模型投票；Branch：条件路由 |
| RecursiveCharacterTextSplitter 的分隔符优先级？ | `["\n\n", "\n", " ", ""]` 从粗到细递归 |
| AgentExecutor 的 max_iterations 设多少合适？ | 5-10，具体取决于任务复杂度，过高会增加 Token 消耗和延迟 |
| 什么是 ReAct 循环？ | Thought → Action → Observation → 循环 → Final Answer |

---

## 五、后续扩展建议

如果面试准备时间充裕，可以补充：

1. **LangGraph**：单 Agent → 多 Agent 协作（审核 Agent + 处置 Agent），与风控场景直接对口
2. **LangSmith**：trace 调试和评测，和 BugVault 的 RAG 评估形成对比
3. **LlamaIndex**：和 LangChain 做对比，展示框架选型的视野
