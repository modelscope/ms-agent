# Deep Research 模块深度分析

## 1. 项目概览
**Deep Research** 是一个多模态深度研究框架，旨在模拟人类研究员的行为。它能够针对复杂问题自主进行网络搜索、阅读网页、提取关键信息（包含图片和文本），并生成图文并茂的专业研究报告。

## 2. 核心模式与工作流

该模块提供两种核心工作流，分别针对不同的时效性和深度需求：

### 1. 标准模式 (Standard / Lightweight)
*   **类**: `ResearchWorkflow`
*   **特点**: 快速、高效、低 Token 消耗。
*   **流程**:
    1.  **Search**: 基于用户 Query 生成搜索关键词并执行搜索。
    2.  **Execute**: 并行抓取和解析搜索结果页面。
    3.  **Report**: 提取核心观点，生成总结报告。
*   **适用场景**: 快速获取信息、简单的话题调研。

### 2. 递归深度模式 (Recursive / Beta)
*   **类**: `ResearchWorkflowBeta`
*   **特点**: 深度、全面、多轮迭代。
*   **流程**:
    1.  **Clarify**: 分析用户意图，提出 3-5 个追问以明确研究边界。
    2.  **Breadth (广度)**: 生成多个维度的搜索查询。
    3.  **Depth (深度)**:
        *   抓取网页并提取 "Learnings" (知识点) 和多模态资源。
        *   **递归**: 基于当前知识生成新的追问，进入下一层级搜索（由 `depth` 参数控制递归层数）。
    4.  **Report**: 聚合所有层级的知识，使用 Docling 等工具组装生成长篇深度报告。
*   **适用场景**: 行业综述、学术文献回顾、复杂技术分析。

## 3. 关键文件与类

| 文件路径 | 类/函数 | 职责 |
| :--- | :--- | :--- |
| `projects/deep_research/run.py` | `run_deep_workflow` | **脚本入口**。配置 LLM 和搜索引擎，启动异步事件循环。 |
| `ms_agent/workflow/deep_research/research_workflow.py` | `ResearchWorkflow` | **标准模式逻辑**。实现 "Search-then-Execute" 的线性流程。 |
| `ms_agent/workflow/deep_research/research_workflow_beta.py` | `ResearchWorkflowBeta` | **递归模式逻辑**。实现递归搜索、广度/深度控制以及知识库管理。 |
| `ms_agent/workflow/deep_research/principle.py` | `MECEPrinciple` | **原则控制**。确保生成的搜索问题符合 MECE (相互独立，完全穷尽) 原则。 |
| `ms_agent/tools/search_engine.py` | `SearchEngine` | **工具封装**。统一了不同搜索引擎 (Exa, SerpApi, Google) 的接口。 |

## 4. 配置与依赖

### 配置文件
1.  **`.env`**: 敏感信息配置。
    ```bash
    OPENAI_API_KEY=...
    EXA_API_KEY=...  # 推荐用于深度搜索
    SERPAPI_API_KEY=...
    ```
2.  **`conf.yaml`**: 搜索引擎选择。
    ```yaml
    SEARCH_ENGINE:
      engine: exa # 或 google, bing
      exa_api_key: $EXA_API_KEY
    ```

### 关键依赖
*   **Ray**: 用于并行加速网页内容的抓取和解析（CPU密集型任务）。
*   **Docling**: (推测/隐式) 用于高质量的文档解析和报告组装。
*   **Search Providers**: 强依赖 Exa.ai (语义搜索) 或 SerpApi。

## 5. 局限性与改进点
*   **上下文窗口**: 在递归模式下，随着深度增加，累积的 "Learnings" 可能非常长，需要更高效的 Context 压缩或 RAG 检索机制。
*   **执行时间**: 深度模式可能运行数分钟，建议配合 Web UI (`doc_research` 或 `app` 命令) 使用以获得更好的进度反馈。
