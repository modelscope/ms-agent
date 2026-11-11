# Agentic Insight

### 轻量、高效、可扩展的多模态深度研究框架

&nbsp;
&nbsp;

本项目提供一个用于深度研究（deep research）任务的框架，使智能体能够自主探索并执行复杂任务。

### 🌟 功能特性

- **自主探索（Autonomous Exploration）** - 面向各类复杂任务的自主探索能力

- **多模态（Multimodal）** - 能处理多种数据模态，并生成包含文本与图片的研究报告。

- **轻量与高效（Lightweight & Efficient）** - 支持 “search-then-execute” 模式，可在数分钟内完成复杂研究任务，显著降低 token 消耗。

- **可扩展深度搜索架构（Expandable Deep Search Architecture）** — 可从轻量检索扩展为递归式深度检索：自动生成追问；可配置 breadth/depth 参数控制搜索预算；通过稠密的总结信息做清晰的上下文交接；支持使用 docling 进行多模态集成并尽量保留图表标题与顺序。

### 🆕 Agentic Insight v2（推荐）

本目录同时包含旧版实现（下方的 Python API 示例）以及更新的 **Agentic Insight v2**。v2 重点强调：

- **可扩展的主 agent + 子 agent 架构**：Researcher 负责编排 Searcher/Reporter，并可扩展新的子 agent 与工具。

- **基于文件系统的上下文管理**：通过在磁盘上存储结构化中间产物来管理上下文，更加灵活、易调试，且支持断点续跑。

- **面向 deep research 优化的工具链**：围绕迭代式研究循环提供专用的 todo、evidence、search、report 工具。

- **基于证据绑定的报告生成**：报告从原始证据出发并进行显式证据绑定，从而提升可信度与可追溯性。

v2 的使用方式与详细说明见：

- 英文： [Agentic Insight v2 Guide](v2/README.md)
- 中文： [Agentic Insight v2 使用说明](v2/README_zh.md)

### 📺 演示

下面展示 Agentic Insight 框架的一个演示案例，用于体现其在高效处理复杂研究任务方面的能力。

#### 用户问题

* 中文:
```text
在计算化学这个领域，我们通常使用Gaussian软件模拟各种情况下分子的结构和性质计算，比如在关键词中加入'field=x+100'代表了在x方向增加了电场。但是，当体系是经典的单原子催化剂时，它属于分子催化剂，在反应环境中分子的朝向是不确定的，那么理论模拟的x方向电场和实际电场是不一致的。

请问：通常情况下，理论计算是如何模拟外加电场存在的情况？
```

* 英文:
```text
In the field of computational chemistry, we often use Gaussian software to simulate the structure and properties of molecules under various conditions. For instance, adding 'field=x+100' to the keywords signifies an electric field applied along the x-direction. However, when dealing with a classical single-atom catalyst, which falls under molecular catalysis, the orientation of the molecule in the reaction environment is uncertain. This means the x-directional electric field in the theoretical simulation might not align with the actual electric field.

So, how are external electric fields typically simulated in theoretical calculations?
```

#### 报告
<https://github.com/user-attachments/assets/b1091dfc-9429-46ad-b7f8-7cbd1cf3209b>



### 🛠️ 安装

按以下步骤安装 Agentic Insight 框架：

* 安装
```bash
# From source code
git clone https://github.com/modelscope/ms-agent.git
pip install -r requirements/research.txt
pip install -e .

# From PyPI (>=v1.1.0)
pip install 'ms-agent[research]'
```

### 🚀 快速开始

#### 环境配置

默认情况下，系统使用免费的 **arXiv search**（不需要 API key）。你也可以选择 **Exa** 或 **SerpApi** 来进行更广泛的网络搜索。

1. 复制并编辑你的 `.env` 文件：
```bash
# 在 projects/deep_research/ 目录执行
cp .env.example .env

# 然后，编辑 `.env`，填入你所选择的搜索引擎对应的 API key：
# 如果使用 Exa（可在 https://exa.ai 注册，提供免费额度）：
EXA_API_KEY=your_exa_api_key
# 如果使用 SerpApi（可在 https://serpapi.com 注册，提供免费额度）：
SERPAPI_API_KEY=your_serpapi_api_key

# 如果你使用的是 DeepResearch beta 版本（`ResearchWorkflowBeta`），为保证稳定性，**搜索查询改写（search-query rewriting）** 会固定使用一个稳定的模型（例如 **gemini-2.5-flash**）。
# 这需要提供一个 OpenAI 兼容的 Base URL（`OPENAI_BASE_URL`）以及 API key（`OPENAI_API_KEY`）。如需切换模型，请将 `ResearchWorkflowBeta.generate_search_queries` 中固定的模型名称替换为你配置的端点所提供的任意模型。
OPENAI_API_KEY=your_api_key
OPENAI_BASE_URL=https://your-openai-compatible-endpoint/v1
```

2. 在 conf.yaml 中配置搜索引擎：
```yaml
SEARCH_ENGINE:
    engine: exa
    exa_api_key: $EXA_API_KEY
```

#### Python 示例

```python
from ms_agent.llm.openai import OpenAIChat
from ms_agent.tools.search.search_base import SearchEngine
from ms_agent.tools.search_engine import get_web_search_tool
from ms_agent.workflow.deep_research.principle import MECEPrinciple
from ms_agent.workflow.deep_research.research_workflow import ResearchWorkflow


def run_workflow(user_prompt: str,
                 task_dir: str,
                 chat_client: OpenAIChat,
                 search_engine: SearchEngine,
                 reuse: bool,
                 use_ray: bool = False):
    """
    Run the deep research workflow, which follows a lightweight and efficient pipeline:
    1. Receive a user prompt and generate search queries.
    2. Search the web, extract hierarchical key information, and preserve multimodal content.
    3. Generate a report summarizing the research results.

    Args:
        user_prompt: The user prompt.
        task_dir: The task directory where the research results will be saved.
        chat_client: The chat client.
        search_engine: The search engine.
        reuse: Whether to reuse the previous research results.
        use_ray: Whether to use Ray for document parsing/extraction.
    """

    research_workflow = ResearchWorkflow(
        client=chat_client,
        principle=MECEPrinciple(),
        search_engine=search_engine,
        workdir=task_dir,
        reuse=reuse,
        use_ray=use_ray,
    )

    research_workflow.run(user_prompt=user_prompt)


if __name__ == '__main__':

    query: str = 'Survey of the AI Agent within the recent 3 month, including the latest research papers, open-source projects, and industry applications.'  # noqa
    task_workdir: str = '/path/to/your_task_dir'
    reuse: bool = False

    # Get chat client OpenAI compatible api
    # Free API Inference Calls - Every registered ModelScope user receives a set number of free API inference calls daily, refer to https://modelscope.cn/docs/model-service/API-Inference/intro for details.  # noqa
    """
    * `api_key` (str), your API key, replace `xxx-xxx` with your actual key. Alternatively, you can use ModelScope API key, refer to https://modelscope.cn/my/myaccesstoken  # noqa
    * `base_url`: (str), the base URL for API requests, `https://api-inference.modelscope.cn/v1/` for ModelScope API-Inference
    * `model`: (str), the model ID for inference, `Qwen/Qwen3.8-Flash-Next` is a current chat model. If the service returns 400, choose another chat model it serves now.
    """
    chat_client = OpenAIChat(
        api_key='xxx-xxx',
        base_url='https://api-inference.modelscope.cn/v1/',
        model='Qwen/Qwen3.8-Flash-Next',
    )

    # Get web-search engine client
    # Please specify your config file path, the default is `conf.yaml` in the current directory.
    search_engine = get_web_search_tool(config_file='conf.yaml')

    # Enable Ray with `use_ray=True` to speed up document parsing.
    # It uses multiple CPU cores for faster processing,
    # but also increases CPU usage and may cause temporary stutter on your machine.
    run_workflow(
        user_prompt=query,
        task_dir=task_workdir,
        reuse=reuse,
        chat_client=chat_client,
        search_engine=search_engine,
        use_ray=False,
    )
```

#### Python 示例（DeepResearch 变体）

```python
import asyncio

from ms_agent.llm.openai import OpenAIChat
from ms_agent.tools.search.search_base import SearchEngine
from ms_agent.tools.search_engine import get_web_search_tool
from ms_agent.workflow.deep_research.research_workflow_beta import ResearchWorkflowBeta


def run_deep_workflow(user_prompt: str,
                      task_dir: str,
                      chat_client: OpenAIChat,
                      search_engine: SearchEngine,
                      breadth: int = 4,
                      depth: int = 2,
                      is_report: bool = True,
                      show_progress: bool = True,
                      use_ray: bool = False):
    """
    Run the expandable deep research workflow (beta version).
    This version is more flexible and scalable than the original deep research workflow.
    It follows a recursive pipeline:
    1. Receive a user prompt and generate questions to clarify the research direction.
    2. Generate search queries and research goals based on the questions and previous research results.
    3. Search the web, extract the information, and preserve multimodal content.
    4. Generate follow-up questions and dense learnings based on the extracted information.
    5. Repeat the process until the research depth is reached or the follow-up questions are empty.
    6. Generate a multimodal report or a summary of the research results.

    Args:
        user_prompt: The user prompt.
        task_dir: The task directory where the research results will be saved.
        chat_client: The chat client.
        search_engine: The search engine.
        breadth: The number of search queries to generate per depth level.
        In order to avoid the explosion of the search space,
        we divide the breadth by 2 for each depth level.
        depth: The maximum research depth.
        is_report: Whether to generate a report.
        show_progress: Whether to show the progress.
        use_ray: Whether to use Ray for document parsing/extraction.
    """

    research_workflow = ResearchWorkflowBeta(
        client=chat_client,
        search_engine=search_engine,
        workdir=task_dir,
        use_ray=use_ray,
        enable_multimodal=True)

    asyncio.run(
        research_workflow.run(
            user_prompt=user_prompt,
            breadth=breadth,
            depth=depth,
            is_report=is_report,
            show_progress=show_progress))


if __name__ == "__main__":

    query: str = 'Survey of the AI Agent within the recent 3 month, including the latest research papers, open-source projects, and industry applications.'  # noqa
    task_workdir: str = '/path/to/your_workdir'  # Specify your task work directory here

    # Get chat client OpenAI compatible api
    # Free API Inference Calls - Every registered ModelScope user receives a set number of free API inference calls daily, refer to https://modelscope.cn/docs/model-service/API-Inference/intro for details.  # noqa
    """
    * `api_key` (str), your API key, replace `xxx-xxx` with your actual key. Alternatively, you can use ModelScope API key, refer to https://modelscope.cn/my/myaccesstoken  # noqa
    * `base_url`: (str), the base URL for API requests, `https://api-inference.modelscope.cn/v1/` for ModelScope API-Inference
    * `model`: (str), the model ID for inference, `Qwen/Qwen3.8-Flash-Next` is a current chat model. If the service returns 400, choose another chat model it serves now.
    """
    chat_client = OpenAIChat(
        api_key='xxx-xxx',
        base_url='https://api-inference.modelscope.cn/v1/',
        model='Qwen/Qwen3.8-Flash-Next',
        generation_config={'extra_body': {
            'enable_thinking': False
        }})

    # Get web-search engine client
    # Please specify your config file path, the default is `conf.yaml` in the current directory.
    search_engine = get_web_search_tool(config_file='conf.yaml')

    # Enable Ray with `use_ray=True` to speed up document parsing.
    # It uses multiple CPU cores for faster processing,
    # but also increases CPU usage and may cause temporary stutter on your machine.
    # Tip: combine use_ray=True with show_progress=True for a better experience.
    run_deep_workflow(
        user_prompt=query,
        task_dir=task_workdir,
        chat_client=chat_client,
        search_engine=search_engine,
        show_progress=True,
        use_ray=False,
    )
```
