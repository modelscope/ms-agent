# Agentic Insight / DeepResearch

DeepResearch面向多轮检索、证据整理和报告写作。当前项目同时保留Agentic Insight v2与v1基础/扩展流程，二者的配置、工具和Python接口不能混用。

## 版本选择

| 路径 | 设计 | 适合 |
| --- | --- | --- |
| v2 | Researcher协调Searcher/Reporter，证据与中间结果落盘 | 可扩展的多轮研究任务 |
| v1基础 | search-then-execute，解析与关键信息提取后生成报告 | 理解旧研究管线或维护已有应用 |
| v1扩展 | 澄清、递归搜索、压缩与报告 | 已基于ResearchWorkflowBeta集成的项目 |

```{mermaid}
flowchart TD
 A[研究问题与预算] --> B[Researcher规划]
 B --> C[Searcher检索]
 C --> D[证据与中间产物]
 D --> B
 B --> E[Reporter写作]
 D --> E
 E --> F[检查引用和最终报告]
```

文件化证据便于检查和继续研究，但不会自动消除引用错误。历史评测应连同模型组合与提交版本阅读，排名对应当次提交的模型和评测配置。

## v2首次运行前

在源码根目录安装 `pip install -e '.[research]'`，准备本地 `.env` 中的 `OPENAI_API_KEY`、`OPENAI_BASE_URL`，检查以下配置：

- `researcher.yaml`：主研究模型和反思/质量检查。
- `searcher.yaml`：搜索模型、搜索引擎、网页摘要模型与预算。
- `reporter.yaml`：写作模型和质量检查。

它们位于 `projects/deep_research/v2/`。所有模型ID都必须能被所选端点访问，摘要和质量检查也会额外调用模型。**当前Searcher默认搜索配置使用Tavily，需 `TAVILY_API_KEY`**；如果改用其他搜索服务，请在 `searcher.yaml` 的 `tools.web_search` 中显式配置，并准备对应凭据。

```bash
ms-agent run --config projects/deep_research/v2/researcher.yaml \
  --query '比较两种公开的数据备份方案，给出引用和适用边界' \
  --output_dir ./research-output --trust_remote_code true
```

先选小范围主题，检查搜索结果和报告路径，再扩大预算。`run_benchmark.sh`是评测入口，需要数据、模型和凭据准备，不是无前提的单任务Quick Start。

## v1兼容路径

v1基础流程使用 `ResearchWorkflow`，扩展流程使用 `ResearchWorkflowBeta`，在 `ms_agent/workflow/deep_research/` 中维护。FinResearch 的舆情节点仍使用 v1 扩展；维护这些应用时请沿用 v1 对应的接口与配置。

旧搜索配置使用 `SEARCH_ENGINE` 等结构，和v2 `tools.web_search`不同。查询改写及其他步骤的实际模型见项目配置和相应 Workflow 初始化参数。维护已有 v1 应用时使用[项目说明](https://github.com/modelscope/ms-agent/tree/main/projects/deep_research)核对其接口。

## 查看结果与限制

查看指定输出目录里的计划、搜索证据、中间稿和最终报告；根据运行日志中的产物路径打开文件，不同工具会生成各自的文件名。检查引用是否支持结论、资料时间是否一致，以及未完成的搜索步骤。

来源可能变化或不可访问，文档解析和模型都有成本；报告并非自动事实核验。完成一次真实研究需要可用的模型、搜索及解析服务；先按上面的命令运行小主题，逐项检查证据和报告。复现评测时，再按 `run_benchmark.sh` 准备对应数据集、模型组合、服务凭据与预算。

后续：[v2详细配置](https://github.com/modelscope/ms-agent/blob/main/projects/deep_research/v2/README.md)、[检索](../core/retrieval.md)、[工作流](../core/workflows.md)。
