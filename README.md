<h1> MS-Agent: Lightweight Framework for Empowering Agents with Autonomous Exploration</h1>

<p align="center">
    <br>
    <img src="https://modelscope.oss-cn-beijing.aliyuncs.com/modelscope.gif" width="400"/>
    <br>
<p>

<p align="center">
<a href="https://modelscope.cn/home">Modelscope Hub</a> ｜ <a href="https://arxiv.org/abs/2309.00986">Paper</a>
<br>
</p>

<p align="center">
<img src="https://img.shields.io/badge/python-%E2%89%A53.8-5be.svg">
<a href='https://modelscope-agent.readthedocs.io/en/latest/?badge=latest'>
    <img src='https://readthedocs.org/projects/modelscope-agent/badge/?version=latest' alt='Documentation Status' />
</a>
<a href="https://github.com/modelscope/modelscope-agent/actions?query=branch%3Amaster+workflow%3Acitest++"><img src="https://img.shields.io/github/actions/workflow/status/modelscope/modelscope-agent/citest.yaml?branch=master&logo=github&label=CI"></a>
<a href="https://github.com/modelscope/modelscope-agent/blob/main/LICENSE"><img src="https://img.shields.io/github/license/modelscope/modelscope-agent"></a>
<a href="https://github.com/modelscope/modelscope-agent/pulls"><img src="https://img.shields.io/badge/PR-welcome-55EB99.svg"></a>
<a href="https://pypi.org/project/modelscope-agent/"><img src="https://badge.fury.io/py/modelscope-agent.svg"></a>
<a href="https://pepy.tech/project/modelscope-agent"><img src="https://pepy.tech/badge/modelscope-agent"></a>
</p>

<p align="center">
<a href="https://trendshift.io/repositories/323" target="_blank"><img src="https://trendshift.io/api/badge/repositories/323" alt="modelscope%2Fmodelscope-agent | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>
</p>

## Introduction

MS-Agent is a lightweight framework designed to empower agents with autonomous exploration capabilities. It provides a flexible and extensible architecture that allows developers to create agents capable of performing complex tasks, such as code generation, data analysis, and tool calling for general purposes with MCP (Model Calling Protocol) support.

### Features

- **Multi-Agent for general purpose**: Chat with agent with tool-calling capabilities based on MCP.
- **Deep Research**: To enable advanced capabilities for autonomous exploration and complex task execution.
- **Code Generation**: Supports code generation tasks with artifacts.
- **Lightweight and Extensible**: Easy to extend and customize for various applications.


> [WARNING] For historical archive versions, please refer to: https://github.com/modelscope/ms-agent/tree/0.8.0

|  WeChat Group
|:-------------------------:
|  <img src="asset/ms-agent.jpg" width="200" height="200">


## 🎉 News

* 🔥July 16, 2025: Release MS-Agent v1.0.0rc0, which includes the following updates:
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
pip install ms-agent
```


### Install from source

```shell
git clone git@github.com:modelscope/ms-agent.git

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

### Using MCP
This project supports interaction with models via the MCP (Model Context Protocol). Below is a complete example showing
how to configure and run an LLMAgent with MCP support.

By default, the agent uses ModelScope's API inference service. Before running the agent, make sure to set your
ModelScope API key.
```bash
export MODELSCOPE_API_KEY={your_modelscope_api_key}
```
You can find or generate your API key at https://modelscope.cn/my/myaccesstoken.

```python
from ms_agent import LLMAgent
import asyncio

# Configure MCP server
mcp = {
    "mcpServers": {
        "fetch": {
            "type": "sse",
            "url": "https://{your_mcp_url}.api-inference.modelscope.net/sse"
        }
    }
}

async def main():
    # Initialize the agent with MCP configuration
    llm_agent = LLMAgent(mcp_config=mcp)
    # Run a task
    await llm_agent.run('Briefly introduce modelscope.cn')

if __name__ == '__main__':
    # Launch the async main function
    asyncio.run(main())
```
----
💡 Tip: You can find available MCP server configurations at modelscope.cn/mcp.

For example: https://modelscope.cn/mcp/servers/@modelcontextprotocol/fetch.
Replace the url in `mcp["mcpServers"]["fetch"]` with your own MCP server endpoint.

### Code Generation Agent
Refer to [Website Generation](projects/code_scratch/README.md)


### Deep Research
This project provides a framework for deep research, enabling agents to autonomously explore and execute complex tasks.

- **Autonomous Exploration**
- **Multi-modal report generation**
- **Lightweight and Extensible**
- **Fast and Efficient**

For interleaved text and image report, refer to the [Report](projects/deep_research/examples/task_20250617a/report.md).

Refer to [Example](projects/deep_research/run.py)


## License

This project is licensed under the [Apache License (Version 2.0)](https://github.com/modelscope/modelscope/blob/master/LICENSE).

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=modelscope/modelscope-agent&type=Date)](https://star-history.com/#modelscope/modelscope-agent&Date)
