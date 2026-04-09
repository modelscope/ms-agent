# Agentic Insight

### Lightweight, Efficient, and Extensible Multi-modal Deep Research Framework

&nbsp;
&nbsp;

This project provides a framework for deep research, enabling agents to autonomously explore and execute complex tasks.

### 🌟 Features

- **Autonomous Exploration** - Autonomous exploration for various complex tasks

- **Multimodal** - Capable of processing diverse data modalities and generating research reports rich in both text and images.

- **Lightweight & Efficient** - Support "search-then-execute" mode, completing complex research tasks within few minutes, significantly reducing token consumption.

- **Expandable Deep Search Architecture** — Scales from lightweight search to recursive deep search with auto-generated follow-up questions; configurable breadth/depth; clean context handoff via dense *learnings*; multimodal report assembly (via docling) that preserves figure/table captions and ordering.

### 🆕 Agentic Insight v2 (Recommended)

This directory contains both the **legacy** implementation (Python API examples below) and the newer **Agentic Insight v2**. v2 emphasizes:

- **Extensible main-agent + sub-agent architecture**: a Researcher orchestrates Searcher/Reporter and can be extended with new sub agents and tools.

- **File-system based context management**: flexible, debuggable, and resume-friendly context via structured artifacts on disk.

- **Deep-research optimized toolchain**: dedicated todo, evidence, search, and report tools tuned for iterative research loops.

- **Evidence-bound report generation**: reports are generated from raw evidence with explicit bindings for higher trustworthiness.

For v2 usage and detailed instructions, see:

- English: [Agentic Insight v2 Guide](v2/README.md)
- Chinese: [Agentic Insight v2 使用说明](v2/README_zh.md)

### 📺 Demonstration

Here is a demonstration of the Agentic Insight framework in action, showcasing its capabilities in handling complex research tasks efficiently.

#### User query

* Chinese:
```text
在计算化学这个领域，我们通常使用Gaussian软件模拟各种情况下分子的结构和性质计算，比如在关键词中加入'field=x+100'代表了在x方向增加了电场。但是，当体系是经典的单原子催化剂时，它属于分子催化剂，在反应环境中分子的朝向是不确定的，那么理论模拟的x方向电场和实际电场是不一致的。

请问：通常情况下，理论计算是如何模拟外加电场存在的情况？
```

* English:
```text
In the field of computational chemistry, we often use Gaussian software to simulate the structure and properties of molecules under various conditions. For instance, adding 'field=x+100' to the keywords signifies an electric field applied along the x-direction. However, when dealing with a classical single-atom catalyst, which falls under molecular catalysis, the orientation of the molecule in the reaction environment is uncertain. This means the x-directional electric field in the theoretical simulation might not align with the actual electric field.

So, how are external electric fields typically simulated in theoretical calculations?
```

#### Report
<https://github.com/user-attachments/assets/b1091dfc-9429-46ad-b7f8-7cbd1cf3209b>



### 🛠️ Installation

To set up the Agentic Insight framework, follow these steps:

* Installation
```bash
# From source code
git clone https://github.com/modelscope/ms-agent.git
pip install -r requirements/research.txt
pip install -e .

# From PyPI (>=v1.1.0)
pip install 'ms-agent[research]'
```

### 🚀 Quickstart

#### Environment Setting

By default, the system uses free **arXiv search** (no API key required).  Optionally, you can switch to **Exa** or **SerpApi** for broader web search.

1. Copy and edit your `.env` file:
```bash
# From projects/deep_research/
cp .env.example .env

# Then, edit `.env` to include the API key for the search engine you choose:
# If using Exa (register at https://exa.ai, free quota available):
EXA_API_KEY=your_exa_api_key
# If using SerpApi (register at https://serpapi.com, free quota available):
SERPAPI_API_KEY=your_serpapi_api_key

# If you are using DeepResearch variant (ResearchWorkflowBeta), **search-query rewriting** is pinned to a stable model (e.g., **gemini-2.5-flash**) for reliability.
# An OpenAI-compatible base URL (`OPENAI_BASE_URL`) and API key (`OPENAI_API_KEY`) are required. To switch models, replace the pinned name in `ResearchWorkflowBeta.generate_search_queries` with any model served by your configured endpoint.
OPENAI_API_KEY=your_api_key
OPENAI_BASE_URL=https://your-openai-compatible-endpoint/v1
```

2. Configure the search engine in conf.yaml:
```yaml
SEARCH_ENGINE:
    engine: exa
    exa_api_key: $EXA_API_KEY
```

#### Python Example

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
    * `model`: (str), the model ID for inference, `Qwen/Qwen3-235B-A22B-Instruct-2507` can be recommended for document research tasks.
    """
    chat_client = OpenAIChat(
        api_key='xxx-xxx',
        base_url='https://api-inference.modelscope.cn/v1/',
        model='Qwen/Qwen3-235B-A22B-Instruct-2507',
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

#### Python Example (DeepResearch variant)

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
    * `model`: (str), the model ID for inference, `Qwen/Qwen3-235B-A22B-Instruct-2507` can be recommended for document research tasks.
    """
    chat_client = OpenAIChat(
        api_key='xxx-xxx',
        base_url='https://api-inference.modelscope.cn/v1/',
        model='Qwen/Qwen3-235B-A22B-Instruct-2507',
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
