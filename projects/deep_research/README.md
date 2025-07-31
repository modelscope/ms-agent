
# Agentic Insight

### Lightweight, Efficient, and Extensible Multi-modal Deep Research Framework

&nbsp;
&nbsp;

This project provides a framework for deep research, enabling agents to autonomously explore and execute complex tasks.

### 🌟 Features

- **Autonomous Exploration** - Autonomous exploration for various complex tasks

- **Multimodal** - Capable of processing diverse data modalities and generating research reports rich in both text and images.

- **Lightweight & Efficient** - Support "search-then-execute" mode, completing complex research tasks within few minutes, significantly reducing token consumption.



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

* Install from source code
```bash
git clone https://github.com/modelscope/ms-agent.git

pip install -r requirements/research.txt
```

### 🚀 Quickstart

#### Environment Setting

1. If you're using Exa or SerpApi, make sure your .env file includes the following configuration settings:
```bash
cp .env.example ../../.env

# Then, edit the `.env` file to include your API keys:
EXA_API_KEY=xxx
SERPAPI_API_KEY=xxx
```

2. Configure the search engine in conf.yaml, using free arxiv search by default:
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
from ms_agent.workflow.principle import MECEPrinciple
from ms_agent.workflow.research_workflow import ResearchWorkflow


def run_workflow(user_prompt: str, task_dir: str, reuse: bool,
                 chat_client: OpenAIChat, search_engine: SearchEngine):

    research_workflow = ResearchWorkflow(
        client=chat_client,
        principle=MECEPrinciple(),
        search_engine=search_engine,
        workdir=task_dir,
        reuse=reuse,
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
    # For the ExaSearch, you can get your API key from https://exa.ai
    # Please specify your config file path, the default is `conf.yaml` in the current directory.
    search_engine = get_web_search_tool(config_file='conf.yaml')

    run_workflow(
        user_prompt=query,
        task_dir=task_workdir,
        reuse=reuse,
        chat_client=chat_client,
        search_engine=search_engine,
    )

```
