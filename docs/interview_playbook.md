# 面试讲解手册

## 30 秒介绍

我做了一个面向企业研发提效的 RepoPilot 软件研发智能体。输入一个 bug 或需求 issue，系统会读取真实代码仓库，自动检索相关代码片段，定位疑似文件；在真实 LLM 模式下，RootCauseAgent、PatchPlannerAgent、PatchSuggestionAgent、RepairAdvisorAgent 和 RepoJudgeAgent 会分别调用 OpenAI-compatible 大模型完成根因分析、修改计划、patch 建议、测试失败归因和质量评估。它对应大厂非常关注的 Coding Agent、研发效能、DevOps Agent 和 Agent Evaluation 场景。

## 技术亮点

1. 真实应用场景：面向软件研发团队的 issue 诊断和修复规划。
2. 代码仓库检索：自动扫描仓库，按文件、行号和符号生成代码证据。
3. 多智能体架构：Indexer、Retriever、RootCauseAgent、PatchPlannerAgent、PatchSuggestionAgent、TestRunner、RepairAdvisorAgent、RepoJudgeAgent。
4. Patch 闭环：输出统一 diff 风格 patch 建议，并可执行本地 smoke check。
5. 自动评测：从代码证据、定位准确性、patch readiness、可测试性和风险控制评分。
6. 工程落地：提供 CLI 和 FastAPI 接口，便于接入前端、CI 或研发平台。
7. 可扩展性：后续可接入 git apply、真实测试执行器、PR 生成器和 SWE-bench 风格评测。

## 模型与架构

当前支持 OpenAI-compatible 模型网关，例如 DeepSeek、OpenAI、Qwen DashScope compatible mode 或企业内部网关。

运行真实 LLM 模式：

```powershell
$env:LLM_BASE_URL="https://api.deepseek.com/v1"
$env:LLM_API_KEY="your-api-key"
$env:LLM_MODEL="deepseek-chat"
python run_repo_pilot.py --repo . --issue "..." --run-tests --use-llm --require-llm
```

架构是：

```text
Multi-Agent Workflow + Code Retrieval + Tool Use + Test Feedback Loop
```

其中 LLM Agent 负责推理和生成，工具型 Agent 负责仓库扫描、代码检索和测试执行。

## 可被追问的问题

### 为什么不是简单 LangChain Demo？

因为项目不是问答，而是读取真实代码仓库，输出带文件路径和行号的代码证据、修改计划、测试计划和风险清单。真实 Coding Agent 系统必须能被评测、能复现、能回归，而不是只生成一段看似合理的文本。

### 如何进一步工程化？

我会引入 Redis 队列处理长任务，PostgreSQL 存储任务状态和 trace，Qdrant/Milvus 存储代码向量索引，接入 git apply、沙箱化测试执行器和 PR 生成器，最后用前端 dashboard 展示 issue -> evidence -> patch -> test -> repair 的完整链路。

### 如何评价 Agent 是否变好？

建立历史 issue/PR/测试失败日志作为评测集。每次修改检索策略或 Agent workflow 后，比较疑似文件命中率、patch 可应用率、测试通过率、平均耗时和回归风险评分。

### 为什么这是大厂认可的场景？

因为它直接服务研发效能，落点是企业普遍存在的 bug 定位、测试失败诊断、代码审查和 PR 辅助。大厂有大量内部代码、CI 日志、issue 和 PR 数据，非常适合构建 Coding Agent 和研发 Copilot。

### 如何减少幻觉？

通过 RAG 引用溯源、Critic Agent 事实审查、Judge Agent grounding 评分、低置信度拒答和人工抽检校准。

### 如何接入你的药材项目？

可以把药材文献、PubMed 摘要和结构化数据作为知识库，把 Analyst Agent 改成药材成分分析专家，把 Critic Agent 改成医学证据审查专家，整体架构保持不变。
