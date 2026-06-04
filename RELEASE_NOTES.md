# 🎉 Release v1.0.0: The Foundation Update (MVP)

这是 BugVault 的首个正式生产可用版本（MVP）。在这个版本中，我们彻底完成了从"概念验证脚本"到"企业级本地 MCP 服务"的架构跃迁。核心链路已全面打通，系统解耦完成，并彻底消灭了底层通信协议的阻塞隐患。

BugVault 现在可以作为稳定、极速的本地外脑，无缝接入 Claude Desktop 及其他 MCP 兼容客户端。

---

## 🚀 核心特性

- **核心排障工具链**：正式对外暴露 `save_bug_experience`（知识沉淀）、`retrieve_bug_experience`（智能召回）、`reflect_and_prevent_error`（预防规则）三大 MCP 核心工具。
- **极速冷启动与响应**：Embedding 模型移至生命周期初始阶段完成单例模式热身，将工具调用的响应时间压缩至极致的毫秒级。
- **异步并发护城河**：引入全局 `ThreadPoolExecutor`，将沉重的 LanceDB 磁盘 I/O 与向量计算剥离至后台线程，确保 MCP 主事件循环 (Event Loop) 绝对不被阻塞。

## 🏛️ 架构重构

- **消灭"上帝文件"**：对臃肿的 `main.py` 进行了手术刀级别的拆分，主入口代码量由 331 行骤降至 **68 行**，职责收敛为纯粹的配置读取与依赖注入。
- **数据访问层解耦 (DAO)**：新增 `src/bugvault/database/lancedb_client.py`，将 LanceDB 的建表、连接、增删改查逻辑完全黑盒化，业务逻辑不再直接触碰全局数据库变量。
- **协议接入层抽离**：新增 `src/bugvault/mcp_tools/tools.py`，集中管理 MCP 工具的定义 (Schema)、注册与路由分发。
- **服务层独立**：拆分出 `services/` 目录，包括 Embedding 服务、归档服务、检索重排序、RAG 评估、反思预防规则等服务模块，各司其职、独立可测。

## 🐛 关键修复

- **彻底终结 LSP 通信死锁**：废弃了脆弱的 `subprocess.Popen` 裸管道读写方案，全面拥抱官方 `mcp.client.stdio.stdio_client`。
- **数据去重机制**：引入 `MD5(bug_title + error_log_snippet)` 作为全局 `record_id`，配合 LanceDB `merge_insert` 实现天然 upsert，杜绝知识库膨胀。
- **自动化测试链路修复**：重写了集成测试，使用 `@pytest.mark.anyio` 配合 `ClientSession` 完成标准的异步握手与全链路测试。
- **标准输出防污染**：完善了 `stdout_guard`，坚决拦截底层三方库（如 fastembed 进度条）对标准输出流的污染，保障 JSON-RPC 通信的绝对纯净。

## 📊 质量指标

- **测试覆盖率**：**43 个测试全绿通过**（41 个单元测试 + 2 个端到端集成测试），覆盖率 100%。
- **容错机制**：关键路由具备完善的 `try...except` 容错防崩机制，单工具调用失败不影响服务整体运行。
- **依赖最简**：仅依赖 `mcp`、`lancedb`、`fastembed`、`pydantic` 四个核心库，轻量无负担。

## 📋 路线图（v1.1+）

| 优先级 | 优化方向 | 描述 |
|--------|---------|------|
| P1 | 父子文本块策略 | 小块检索（提高命中率）+ 大块生成（上下文完整） |
| P1 | 元数据硬过滤 | 按项目/技术栈/时间范围预过滤，缩小搜索空间 |
| P1 | RRF 混合检索 | 语义向量 + BM25 关键字加权融合，提高召回鲁棒性 |
| P2 | 智能查询重写 | 对用户原始 query 进行改写/扩写，提升语义匹配精度 |

---

> **发布信息**  
> 版本：v1.0.0  
> 分支：`v1.0.0`  
> 协议：MIT  
> 兼容性：Claude Desktop / 任何 MCP stdio 客户端
