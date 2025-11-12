<h1> MS-Agent: Lightweight Framework for Empowering Agents with Autonomous Exploration</h1>

<p align="center">
    <br>
    <img src="https://modelscope.oss-cn-beijing.aliyuncs.com/modelscope.gif" width="400"/>
    <br>
<p>

<p align="center">
<a href="https://modelscope.cn/mcp/playground">MCP Playground</a> | <a href="https://arxiv.org/abs/2309.00986">Paper</a> | <a href="https://ms-agent-en.readthedocs.io">Documentation</a> | <a href="https://ms-agent.readthedocs.io/zh-cn">中文文档</a>
<br>
</p>

<p align="center">
<img src="https://img.shields.io/badge/python-%E2%89%A53.10-5be.svg">
<a href='https://ms-agent-en.readthedocs.io/en/latest/'>
    <img src='https://readthedocs.org/projects/ms-agent/badge/?version=latest' alt='Documentation Status' />
</a>
<a href="https://github.com/modelscope/ms-agent/actions?query=branch%3Amaster+workflow%3Acitest++"><img src="https://img.shields.io/github/actions/workflow/status/modelscope/ms-agent/citest.yaml?branch=master&logo=github&label=CI"></a>
<a href="https://github.com/modelscope/ms-agent/blob/main/LICENSE"><img src="https://img.shields.io/github/license/modelscope/ms-agent"></a>
<a href="https://github.com/modelscope/ms-agent/pulls"><img src="https://img.shields.io/badge/PR-welcome-55EB99.svg"></a>
<a href="https://pypi.org/project/ms-agent/"><img src="https://badge.fury.io/py/ms-agent.svg"></a>
<a href="https://pepy.tech/project/ms-agent"><img src="https://static.pepy.tech/badge/ms-agent"></a>
</p>

<p align="center">
<a href="https://trendshift.io/repositories/323" target="_blank"><img src="https://trendshift.io/api/badge/repositories/323" alt="modelscope%2Fms-agent | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>
</p>

## Introduction

MS-Agent is a lightweight framework designed to empower agents with autonomous exploration capabilities. It provides a flexible and extensible architecture that allows developers to create agents capable of performing complex tasks, such as code generation, data analysis, and tool calling for general purposes with MCP (Model Calling Protocol) support.

### Features

- **Multi-Agent for general purpose**: Chat with agent with tool-calling capabilities based on MCP.
- **Deep Research**: To enable advanced capabilities for autonomous exploration and complex task execution.
- **Code Generation**: Supports code generation tasks with artifacts.
- **Agent Skills**: Implementation of [Anthropic-Agent-Skills](https://docs.claude.com/en/docs/agents-and-tools/agent-skills) Protocol.
- **Lightweight and Extensible**: Easy to extend and customize for various applications.


> [WARNING] For historical archive versions, please refer to: https://github.com/modelscope/ms-agent/tree/0.8.0

|  WeChat Group
|:-------------------------:
|  <img src="asset/ms-agent.jpg" width="200" height="200">


## 🎉 News

* 🚀 Nov 12, 2025: Release MS-Agent v1.4.1, which includes the following updates:
  - 🔥 We present [FinResearch](projects/fin_research/README.md), a multi-agent workflow tailored for financial research
  - 🔥 Support financial data collection via Akshare and Baostock
  - 🔥 Support DagWorkflow for workflow orchestration
  - 🔥 Optimize the DeepResearch workflow for stability and efficiency

* 🚀 Nov 07, 2025: Release MS-Agent v1.4.0, which includes the following updates:
  - 🔥 We present [**MS-Agent Skills**](projects/agent_skills/README.md), an **Implementation** of [Anthropic-Agent-Skills](https://docs.claude.com/en/docs/agents-and-tools/agent-skills) Protocol.
  - 🔥 Add [Docs](https://ms-agent-en.readthedocs.io/en) and [中文文档](https://ms-agent.readthedocs.io/zh-cn)
  - 🔥 Support Sandbox Framework [ms-enclave](https://github.com/modelscope/ms-enclave)

* 🚀 Sep 22, 2025: Release MS-Agent v1.3.0, which includes the following updates:
  - 🔥 Support [Code Scratch](projects/code_scratch/README.md)
  - Support `Memory` for building agents with long-term and short-term memory
  - Enhance the DeepResearch workflow
  - Support RAY for accelerating document information extraction
  - Support Anthropic API format for LLMs

* 🚀 Aug 28, 2025: Release MS-Agent v1.2.0, which includes the following updates:
  - DocResearch now supports pushing to `ModelScope`、`HuggingFace`、`GitHub` for easy sharing of research reports. Refer to [Doc Research](projects/doc_research/README.md) for more details.
  - DocResearch now supports exporting the Markdown report to `HTML`、`PDF`、`PPTX` and `DOCX` formats, refer to [Doc Research](projects/doc_research/README.md) for more details.
  - DocResearch now supports `TXT` file processing and file preprocessing, refer to [Doc Research](projects/doc_research/README.md) for more details.

* 🚀 July 31, 2025: Release MS-Agent v1.1.0, which includes the following updates:
  - 🔥 Support [Doc Research](projects/doc_research/README.md), demo: [DocResearchStudio](https://modelscope.cn/studios/ms-agent/DocResearch)
  - Add `General Web Search Engine` for Agentic Insight (DeepResearch)
  - Add `Max Continuous Runs` for Agent chat with MCP.

* 🚀 July 18, 2025: Release MS-Agent v1.0.0, improve the experience of Agent chat with MCP, and update the readme for [Agentic Insight](projects/deep_research/README.md).

* 🚀 July 16, 2025: Release MS-Agent v1.0.0rc0, which includes the following updates:
  - Support for Agent chat with MCP (Model Context Protocol)
  - Support for Deep Research (Agentic Insight), refer to: [Report_Demo](projects/deep_research/examples/task_20250617a/report.md), [Script_Demo](projects/deep_research/run.py)
  - Support for [MCP-Playground](https://modelscope.cn/mcp/playground)
  - Add callback mechanism for Agent chat


<details><summary>Archive</summary>

* 🔥🔥🔥Aug 8, 2024: A new graph based code generation tool [CodexGraph](https://arxiv.org/abs/2408.03910) is released by Modelscope-Agent, it has been proved effective and versatile on various code related tasks, please check [example](https://github.com/modelscope/modelscope-agent/tree/master/apps/codexgraph_agent).
* 🔥🔥Aug 1, 2024: A high efficient and reliable Data Science Assistant is running on Modelscope-Agent, please find detail in [example](https://github.com/modelscope/modelscope-agent/tree/master/apps/datascience_assistant).
* 🔥July 17, 2024: Parallel tool calling on Modelscope-Agent-Server, please find detail in [doc](https://github.com/modelscope/modelscope-agent/blob/master/modelscope_agent_servers/README.md).
* 🔥June 17, 2024: Upgrading RAG flow based on LLama-index, allow user to hybrid search knowledge by different strategies and modalities, please find detail in [doc](https://github.com/modelscope/modelscope-agent/blob/master/modelscope_agent/rag/README_zh.md).
* 🔥June 6, 2024: With [Modelscope-Agent-Server](https://github.com/modelscope/modelscope-agent/blob/master/modelscope_agent_servers/README.md), **Qwen2** could be used by OpenAI SDK with tool calling ability, please find detail in [doc](https://github.com/modelscope/modelscope-agent/blob/master/docs/llms/qwen2_tool_calling.md).
* 🔥June 4, 2024: Modelscope-Agent supported Mobile-Agent-V2[arxiv](https://arxiv.org/abs/2406.01014)，based on Android Adb Env, please check in the [application](https://github.com/modelscope/modelscope-agent/tree/master/apps/mobile_agent).
* 🔥May 17, 2024: Modelscope-Agent supported multi-roles room chat in the [gradio](https://github.com/modelscope/modelscope-agent/tree/master/apps/multi_roles_chat_room).
* May 14, 2024: Modelscope-Agent supported image input in `RolePlay` agents with latest OpenAI model `GPT-4o`. Developers can experience this feature by specifying the `image_url` parameter.
* May 10, 2024: Modelscope-Agent launched a user-friendly `Assistant API`, and also provided a `Tools API` that executes utilities in isolated, secure containers, please find the [document](https://github.com/modelscope/modelscope-agent/blob/master/modelscope_agent_servers/)
* Apr 12, 2024: The [Ray](https://docs.ray.io/en/latest/) version of multi-agent solution is on modelscope-agent, please find the [document](https://github.com/modelscope/modelscope-agent/blob/master/modelscope_agent/multi_agents_utils/README.md)
* Mar 15, 2024: Modelscope-Agent and the [AgentFabric](https://github.com/modelscope/modelscope-agent/tree/master/apps/agentfabric) (opensource version for GPTs) is running on the production environment of [modelscope studio](https://modelscope.cn/studios/agent).
* Feb 10, 2024: In Chinese New year, we upgrade the modelscope agent to version v0.3 to facilitate developers to customize various types of agents more conveniently through coding and make it easier to make multi-agent demos. For more details, you can refer to [#267](https://github.com/modelscope/modelscope-agent/pull/267) and [#293](https://github.com/modelscope/modelscope-agent/pull/293) .
* Nov 26, 2023: [AgentFabric](https://github.com/modelscope/modelscope-agent/tree/master/apps/agentfabric) now supports collaborative use in ModelScope's [Creation Space](https://modelscope.cn/studios/modelscope/AgentFabric/summary), allowing for the sharing of custom applications in the Creation Space. The update also includes the latest [GTE](https://modelscope.cn/models/damo/nlp_gte_sentence-embedding_chinese-base/summary) text embedding integration.
* Nov 17, 2023: [AgentFabric](https://github.com/modelscope/modelscope-agent/tree/master/apps/agentfabric) released, which is an interactive framework to facilitate creation of agents tailored to various real-world applications.
* Oct 30, 2023: [Facechain Agent](https://modelscope.cn/studios/CVstudio/facechain_agent_studio/summary) released a local version of the Facechain Agent that can be run locally. For detailed usage instructions, please refer to [Facechain Agent](#facechain-agent).
* Oct 25, 2023: [Story Agent](https://modelscope.cn/studios/damo/story_agent/summary) released a local version of the Story Agent for generating storybook illustrations. It can be run locally. For detailed usage instructions, please refer to [Story Agent](#story-agent).
* Sep 20, 2023: [ModelScope GPT](https://modelscope.cn/studios/damo/ModelScopeGPT/summary) offers a local version through gradio that can be run locally. You can navigate to the demo/msgpt/ directory and execute `bash run_msgpt.sh`.
* Sep 4, 2023: Three demos, [demo_qwen](demo/demo_qwen_agent.ipynb), [demo_retrieval_agent](demo/demo_retrieval_agent.ipynb) and [demo_register_tool](demo/demo_register_new_tool.ipynb), have been added, along with detailed tutorials provided.
* Sep 2, 2023: The [preprint paper](https://arxiv.org/abs/2309.00986) associated with this project was published.
* Aug 22, 2023: Support accessing various AI model APIs using ModelScope tokens.
* Aug 7, 2023: The initial version of the modelscope-agent repository was released.

</details>



## Installation

### Install from PyPI

```shell
# For the basic functionalities
pip install ms-agent

# For the deep research functionalities
pip install 'ms-agent[research]'
```


### Install from source

```shell
git clone https://github.com/modelscope/ms-agent.git

cd ms-agent
pip install -e .
```



> [!WARNING]
> As the project has been renamed to `ms-agent`, for versions `v0.8.0` or earlier, you can install using the following command:
> ```shell
> pip install modelscope-agent<=0.8.0
> ```
> To import relevant dependencies using `modelscope_agent`:
> ``` python
> from modelscope_agent import ...
> ```


## Quickstart

### Agent Chat
This project supports interaction with models via the MCP (Model Context Protocol). Below is a complete example showing
how to configure and run an LLMAgent with MCP support.

✅ Chat with agents using the MCP protocol: [MCP Playground](https://modelscope.cn/mcp/playground)

By default, the agent uses ModelScope's API inference service. Before running the agent, make sure to set your
ModelScope API key.
```bash
export MODELSCOPE_API_KEY={your_modelscope_api_key}
```
You can find or generate your API key at https://modelscope.cn/my/myaccesstoken.

```python
import asyncio

from ms_agent import LLMAgent

# Configure MCP servers
mcp = {
  "mcpServers": {
    "fetch": {
      "type": "streamable_http",
      "url": "https://mcp.api-inference.modelscope.net/{your_mcp_uuid}/mcp"
    }
  }
}

async def main():
    # Use json to configure MCP
    llm_agent = LLMAgent(mcp_config=mcp)   # Run task
    await llm_agent.run('Introduce modelscope.cn')

if __name__ == '__main__':
    # Start
    asyncio.run(main())
```
----
💡 Tip: You can find available MCP server configurations at modelscope.cn/mcp.

For example: https://modelscope.cn/mcp/servers/@modelcontextprotocol/fetch.
Replace the url in `mcp["mcpServers"]["fetch"]` with your own MCP server endpoint.

<details><summary>Memory</summary>

We support memory by using [mem0](https://github.com/mem0ai/mem0) in version v1.3.0! 🎉

Below is a simple example to get you started. For more comprehensive test cases, please refer to the [test_case](tests/memory/test_default_memory.py).

Before running the agent, ensure that you have set your ModelScope API key for LLM.

⚠️ Note: As of now, ModelScope API-Inference does not yet provide an embedding interface (coming soon). Therefore, we rely on external API providers for embeddings. By default, this implementation uses DashScope. Make sure to set your DASHSCOPE_API_KEY before running the examples.

```bash
pip install mem0ai
export MODELSCOPE_API_KEY={your_modelscope_api_key}
export DASHSCOPE_API_KEY={your_dashscope_api_key}
```

You can obtain or generate your API keys at:

* [modelscope_api_key](https://modelscope.cn/my/myaccesstoken)
* [dashscope_api_key](https://bailian.console.aliyun.com/?spm=5176.29619931.J__Z58Z6CX7MY__Ll8p1ZOR.1.4bf0521cWpNGPY&tab=api#/api/?type=model&url=2712195).

**Example Usage**

This example demonstrates how the agent remembers user preferences across sessions using persistent memory:

```python
import uuid
import asyncio
from omegaconf import OmegaConf
from ms_agent.agent.loader import AgentLoader


async def main():
    random_id = str(uuid.uuid4())
    default_memory = OmegaConf.create({
        'memory': [{
            'path': f'output/{random_id}',
            'user_id': 'awesome_me'
        }]
    })
    agent1 = AgentLoader.build(config_dir_or_id='ms-agent/simple_agent', config=default_memory)
    agent1.config.callbacks.remove('input_callback')  # Disable interactive input for direct output

    await agent1.run('I am a vegetarian and I drink coffee every morning.')
    del agent1
    print('========== Data preparation completed, starting test ===========')
    agent2 = AgentLoader.build(config_dir_or_id='ms-agent/simple_agent', config=default_memory)
    agent2.config.callbacks.remove('input_callback')  # Disable interactive input for direct output

    res = await agent2.run('Please help me plan tomorrow’s three meals.')
    print(res)
    assert 'vegan' in res[-1].content.lower() and 'coffee' in res[-1].content.lower()

asyncio.run(main())
```

</details>


### Agent Skills

**MS-Agent Skills** is an **Implementation** of the [**Anthropic-Agent-Skills**](https://docs.claude.com/en/docs/agents-and-tools/agent-skills) protocol, enabling agents to autonomously explore and execute complex tasks by leveraging predefined or custom "skills".


#### Key Features

- 📜 **Standard Skill Protocol**: Fully compatible with the [Anthropic Skills](https://github.com/anthropics/skills) protocol
- 🧠 **Heuristic Context Loading**: Loads only necessary context—such as `References`, `Resources`, and `Scripts` on demand
- 🤖 **Autonomous Execution**: Agents autonomously analyze, plan, and decide which scripts and resources to execute based on skill definitions
- 🔍 **Skill Management**: Supports batch loading of skills and can automatically retrieve and discover relevant skills based on user input
- 🛡️ **Code Execution Environment**: Optional local direct code execution or secure sandboxed execution via [**ms-enclave**](https://github.com/modelscope/ms-enclave), with automatic dependency installation and environment isolation
- 📁 **Multi-file Type Support**: Supports documentation, scripts, and resource files
- 🧩 **Extensible Design**: The skill data structure is modularized, with implementations such as `SkillSchema` and `SkillContext` provided for easy extension and customization


#### Quick Start

> 💡 Note:
> 1. Before running the following examples, ensure that you have set the `OPENAI_API_KEY` and `OPENAI_BASE_URL` environment variables to access the required model APIs.
> 2. Agent Skills requires ms-agent >= 1.4.0


**Installation**:

```shell
pip install ms-agent
```

**Usage**:

> This example demonstrates how to configure and run an Agent Skill that generates generative art code based on p5.js flow fields.


Refer to: [Run Skills](projects/agent_skills/run.py)


**Result**:

<div align="center">
  <img src="https://github.com/user-attachments/assets/9d5d78bf-c2db-4280-b780-324eab74a41e" alt="FlowFieldParticles" width="750">
  <p><em>Agent-Skills: Flow Field Particles</em></p>
</div>


#### References
- **README**: [MS-Agent Skills](projects/agent_skills/README.md)
- **Anthropic Agent Skills Official Docs**: [Anthropic-Agent-Skills](https://docs.claude.com/en/docs/agents-and-tools/agent-skills)
- **Anthropic Skills GitHub Repo**: [Skills](https://github.com/anthropics/skills)



### Agentic Insight

#### - Lightweight, Efficient, and Extensible Multi-modal Deep Research Framework

This project provides a framework for **Deep Research**, enabling agents to autonomously explore and execute complex tasks.

#### 🌟 Features

- **Autonomous Exploration** - Autonomous exploration for various complex tasks

- **Multimodal** - Capable of processing diverse data modalities and generating research reports rich in both text and images.

- **Lightweight & Efficient** - Support "search-then-execute" mode, completing complex research tasks within few minutes, significantly reducing token consumption.


#### 📺 Demonstration

Here is a demonstration of the Agentic Insight framework in action, showcasing its capabilities in handling complex research tasks efficiently.

- **User query**

- - Chinese:

```text
在计算化学这个领域，我们通常使用Gaussian软件模拟各种情况下分子的结构和性质计算，比如在关键词中加入'field=x+100'代表了在x方向增加了电场。但是，当体系是经典的单原子催化剂时，它属于分子催化剂，在反应环境中分子的朝向是不确定的，那么理论模拟的x方向电场和实际电场是不一致的。

请问：通常情况下，理论计算是如何模拟外加电场存在的情况？
```

- - English:
```text
In the field of computational chemistry, we often use Gaussian software to simulate the structure and properties of molecules under various conditions. For instance, adding 'field=x+100' to the keywords signifies an electric field applied along the x-direction. However, when dealing with a classical single-atom catalyst, which falls under molecular catalysis, the orientation of the molecule in the reaction environment is uncertain. This means the x-directional electric field in the theoretical simulation might not align with the actual electric field.

So, how are external electric fields typically simulated in theoretical calculations?
```

#### Report

<https://github.com/user-attachments/assets/b1091dfc-9429-46ad-b7f8-7cbd1cf3209b>



For more details, please refer to [Deep Research](projects/deep_research/README.md).

<br>

### Doc Research

This project provides a framework for **Doc Research**, enabling agents to autonomously explore and execute complex tasks related to document analysis and research.

#### Features

  - 🔍 **Deep Document Research** - Support deep analysis and summarization of documents
  - 📝 **Multiple Input Types** - Support multi-file uploads and URL inputs
  - 📊 **Multimodal Reports** - Support text and image reports in Markdown format
  - 🚀 **High Efficiency** - Leverage powerful LLMs for fast and accurate research, leveraging key information extraction techniques to further optimize token usage
  - ⚙️ **Flexible Deployment** - Support local run and [ModelScope Studio](https://modelscope.cn/studios)
  - 💰 **Free Model Inference** - Free LLM API inference calls for ModelScope users, refer to [ModelScope API-Inference](https://modelscope.cn/docs/model-service/API-Inference/intro)


#### Demo

**1. ModelScope Studio**
[DocResearchStudio](https://modelscope.cn/studios/ms-agent/DocResearch)

**2. Local Gradio Application**

* Research Report for [UniME: Breaking the Modality Barrier: Universal Embedding Learning with Multimodal LLMs](https://arxiv.org/pdf/2504.17432)
<div align="center">
  <img src="https://github.com/user-attachments/assets/3f85ba08-6366-49b7-b551-cbe50edf6218" alt="LocalGradioApplication" width="750">
  <p><em>Demo：UniME Research Report</em></p>
</div>


For more details, refer to [Doc Research](projects/doc_research/README.md)

<br>

### Code Scratch

This project provides a framework for **Code Scratch**, enabling agents to autonomously generate code projects.

#### Features

  - 🎯 **Complex Code Generation** - Support for complex code generation tasks, especially React frontend and Node.js backend
  - 🔧 **Customizable Workflows** - Enable users to freely develop their own code generation workflows tailored to specific scenarios
  - 🏗️ **Three-Phase Architecture** - Design & Coding Phase followed by Refine Phase for robust code generation and error fixing
  - 📁 **Intelligent File Grouping** - Automatically groups related code files to minimize dependencies and reduce bugs
  - 🔄 **Auto Compilation & Fixing** - Automatic npm compilation with intelligent error analysis and iterative fixing

#### Demo

**AI Workspace Homepage**

Generate a complete ai workspace homepage with the following command:

```shell
PYTHONPATH=. openai_api_key=your-api-key openai_base_url=your-api-url python ms_agent/cli/cli.py run --config projects/code_scratch --query 'Build a comprehensive AI workspace homepage' --trust_remote_code true
```

The generated code will be output to the `output` folder in the current directory.

**Architecture Workflow:**
- **Design Phase**: Analyze requirements → Generate PRD & module design → Create implementation tasks
- **Coding Phase**: Execute coding tasks in intelligent file groups → Generate complete code structure
- **Refine Phase**: Auto-compilation → Error analysis → Iterative bug fixing → Human evaluation loop

For more details, refer to [Code Scratch](projects/code_scratch/README.md).

<br>

### FinResearch

The MS-Agent FinResearch project is a multi-agent workflow tailored for financial market research. It combines quantitative financial data analysis with deep research on online news/sentiment to automatically generate professional research reports.

#### Key Features

- 🤖 **Multi-Agent Architecture**: Orchestrates multiple specialized agents to handle task decomposition, data collection, quantitative analysis, sentiment research, and final report generation.

- 📁 **Multi-Dimensional Analysis**: Covers both financial indicators and public sentiment, enabling fusion analysis of structured and unstructured data.

- 💰 **Financial Data Collection**: Supports automatic retrieval of quotes, financial statements, macro indicators, and market data for A-share, Hong Kong, and U.S. markets.

- 🔍 **In-Depth Sentiment Research**: Deep research on multi-source information from news/media/communities.

- 📝 **Professional Report Generation**: Produces multi-chapter, well-structured, image-and-text reports following common methodologies (MECE, SWOT, Pyramid Principle, etc.).

- 🔒 **Secure Code Execution**: Runs data processing and analysis inside an isolated Docker sandbox to ensure security and reproducibility.

#### Quick Start

> 💡 Tips:
> 1. Before running the examples below, set the `OPENAI_API_KEY` and `OPENAI_BASE_URL` environment variables to access the required model APIs. To run the full workflow, also configure the search engine variables EXA_API_KEY (https://exa.ai) or SERPAPI_API_KEY (https://serpapi.com).
> 2. FinResearch requires ms-agent version >= 1.4.1.

**Usage**:

Quickly launch the full FinResearch workflow for testing:

```bash
# Run at the ms-agent project root
PYTHONPATH=. python ms_agent/cli/cli.py run --config projects/fin_research --query 'Analyze CATL (300750.SZ) profitability over the past four quarters and compare it with key new-energy competitors (e.g., BYD, Gotion High-Tech, CALB); considering industry policies and lithium price volatility, forecast its performance for the next two quarters.' --trust_remote_code true
```

You can also run a minimal version without configuring a search engine by adjusting the [workflow configuration](projects/fin_research/workflow.yaml) as follows:

```yaml
type: DagWorkflow

orchestrator:
  next:
    - collector
  agent_config: orchestrator.yaml

collector:
  next:
    - analyst
  agent_config: collector.yaml

analyst:
  next:
    - aggregator
  agent_config: analyst.yaml

aggregator:
  agent_config: aggregator.yaml
```

**Result**:

<https://github.com/user-attachments/assets/a11db8d2-b559-4118-a2c0-2622d46840ef>

**References**:
- README: [FinResearch](projects/fin_research/README.md)
- Documentation: [MS-Agent Documentation](https://ms-agent-en.readthedocs.io/en/latest/Projects/FinResearch.html)

<br>

### Interesting works

1. A news collection agent [ms-agent/newspaper](https://www.modelscope.cn/models/ms-agent/newspaper/summary)


## Roadmap

We are committed to continuously improving and expanding the MS-Agent framework to push the boundaries of large models and AI agents. Our future roadmap includes:

- [x] **Anthropic Agent Skills** - Full support for the [Anthropic-Agent-Skills](https://docs.claude.com/en/docs/agents-and-tools/agent-skills) protocol, enabling agents to autonomously explore and execute complex tasks using predefined or custom "skills".
- [ ] **FinResearch** – A financial deep-research agent dedicated to in-depth analysis and research in the finance domain.
  - [x] Long-term deep financial analysis report generation
  - [ ] Near real-time event-driven report generation
- [ ] **Multimodal Agentic Search** – Supporting large-scale multimodal document retrieval and generation of search results combining text and images.
- [ ] Enhanced **Agent Skills** – Providing a richer set of predefined skills and tools to expand agent capabilities and enabling multi-skill collaboration for complex task execution.
- [ ] **Agent-Workstation** - An unified WebUI with one-click local deployment support with combining all agent capabilities of MS-Agent, such as AgentChat, MCP, AgentSkills, DeepResearch, DocResearch, CodeScratch, etc.


## License

This project is licensed under the [Apache License (Version 2.0)](https://github.com/modelscope/modelscope/blob/master/LICENSE).

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=modelscope/modelscope-agent&type=Date)](https://star-history.com/#modelscope/modelscope-agent&Date)


---

<p align="center">
  <em> ❤️ Thanks for visiting ✨ MS-Agent !</em><br><br>
  <img src="https://visitor-badge.laobi.icu/badge?page_id=modelscope.ms-agent&style=for-the-badge&color=00d4ff" alt="Views">
</p>
