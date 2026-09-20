<h1> MS-Agent: Lightweight Framework for Empowering Agents with Autonomous Exploration</h1>

<p align="center">
    <br>
    <img src="asset/logo.png" width="420" alt="MS-Agent"/>
    <br>
</p>

<p align="center">
<a href="https://modelscope.github.io/ms-agent/">Homepage</a> | <a href="https://modelscope.cn/mcp/playground">MCP Playground</a> | <a href="https://arxiv.org/abs/2309.00986">Paper</a> | <a href="https://ms-agent-en.readthedocs.io">Documentation</a> | <a href="https://ms-agent.readthedocs.io/zh-cn">中文文档</a>
<br>
</p>

<p align="center">
<img src="https://img.shields.io/badge/python-%E2%89%A53.10-5be.svg">
<a href='https://ms-agent-en.readthedocs.io/en/latest/'>
    <img src='https://readthedocs.org/projects/ms-agent/badge/?version=latest' alt='Documentation Status' />
</a>
<a href="https://github.com/modelscope/ms-agent/actions?query=branch%3Amain+workflow%3Acitest++"><img src="https://img.shields.io/github/actions/workflow/status/modelscope/ms-agent/citest.yaml?branch=main&logo=github&label=CI"></a>
<a href="https://github.com/modelscope/ms-agent/blob/main/LICENSE"><img src="https://img.shields.io/github/license/modelscope/ms-agent"></a>
<a href="https://github.com/modelscope/ms-agent/pulls"><img src="https://img.shields.io/badge/PR-welcome-55EB99.svg"></a>
<a href="https://pypi.org/project/ms-agent/"><img src="https://badge.fury.io/py/ms-agent.svg"></a>
<a href="https://pepy.tech/project/ms-agent"><img src="https://static.pepy.tech/badge/ms-agent"></a>
</p>

<p align="center">
<a href="https://trendshift.io/repositories/323" target="_blank"><img src="https://trendshift.io/api/badge/repositories/323" alt="modelscope%2Fms-agent | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>
</p>


[**中文**](README_ZH.md)

<a id="introduction"></a>

## 👋 Introduction

**MS-Agent is a modular, extensible open-source agent framework built for complex, long-running tasks.** Combine models, tools, skills, and sub-agents with a customizable harness to build a productivity assistant tailored to your work. The harness manages planning, context, permissions, and execution feedback, while project memory and autonomous scheduling help the assistant keep complex tasks moving forward.

A shared Python SDK handles execution and management for the **CLI, TUI, and WebUI**, so you can reuse agent logic and extensions across terminals, browser workspaces, and business applications with less integration and maintenance work.

<p align="center">
<a href="#features"><b>Features</b></a> · <a href="#installation"><b>Installation</b></a> · <a href="#applications"><b>Applications</b></a> · <a href="#documentation"><b>Documentation</b></a>
</p>

Join the community and share feedback: [Discord](https://discord.gg/qmTFPY9byM) · [GitHub Issues](https://github.com/modelscope/ms-agent/issues)

<details>
<summary>WeChat and Discord QR codes</summary>

| Discord | WeChat |
| :---: | :---: |
| <img src="asset/discord_qr.jpg" width="200" alt="Discord community QR code"> | <img src="asset/ms-agent.jpg" width="200" alt="WeChat community QR code"> |

</details>

For earlier demos and documentation, see [ModelScope-Agent 0.8.0 and earlier](https://github.com/modelscope/ms-agent/tree/0.8.0).

## 🎉 News

* 🚀 Jul 13, 2026: Added **Agent Hub** support for managing agent workspace files locally and in remote ModelScope repositories with `ms-agent agent`. Features include uploads and downloads, background sync (`watch`), conversion between frameworks, status checks, backups, and restoration for `qoder`, `qwenpaw`, `openclaw`, `hermes`, `nanobot`, `openhuman`, and `ms-agent`.

* 🏆 Apr 09, 2026: Agentic Insight v2 is now **#2 Open-Source** (#5 Overall) on [DeepResearch Bench](https://github.com/Ayanami0730/deep_research_bench) — scoring **55.31** with the submitted version (Qwen3.5-Plus + GPT 5.2). [Leaderboard](https://huggingface.co/spaces/muset-ai/DeepResearch-Bench-Leaderboard) | [Agentic Insight v2](projects/deep_research/v2/README.md).

* 🚀 Mar 23, 2026: Release MS-Agent v1.6.0, which includes the following updates:
  - **Context Compression**: Added context compression mechanism with token usage monitoring, overflow detection, and automatic context compaction via pruning historical tool outputs and LLM-based summarization.
  - **Agentic Insight v2 Enhancements**: Major architecture and performance improvements to the deep research system; achieves **55.43** on DeepResearch Bench with GPT5 and Qwen3.5-plus/flash. See [Agentic Insight v2](https://github.com/modelscope/ms-agent/tree/main/projects/deep_research/v2).
  - **Knowledge Search**: Integrated Sirchmunk for intelligent retrieval over local codebases and documentation during agent conversations. See [Config Docs](docs/en/Components/Config.md).
  - **Multimodal Model Input**: Support image, video, and other multimodal inputs. See [Multimodal Docs](docs/en/Components/MultimodalSupport.md).

* 🚀 Feb 06, 2026: Release MS-Agent v1.6.0rc1, which includes the following updates:
  - **Agentic Insight v2**: A fully refactored deep-research system with better performance, scalability, and trustworthiness, with a WebUI entry point. See [Agentic Insight v2](https://github.com/modelscope/ms-agent/tree/main/projects/deep_research/v2).

* 🚀 Feb 04, 2026: Release MS-Agent v1.6.0rc0, which includes the following updates:
  - **Code Genesis** for complex code generation tasks, refer to [Code Genesis](https://github.com/modelscope/ms-agent/tree/main/projects/code_genesis)
  - **Singularity Cinema** for animated video generation workflow, refactored version, refer to [Singularity Cinema](https://github.com/modelscope/ms-agent/tree/main/projects/singularity_cinema)
  - **Agent Skills v2**: Knowledge-driven skill system — skills as procedural knowledge with progressive disclosure, multi-source loading, and standard tool integration. Refer to [Agent Skills](https://github.com/modelscope/ms-agent/tree/main/ms_agent/skill).
  - **WebUI**: A new WebUI has been added, featuring agentic chatting capabilities, complex code generation and video generation workflow.


<details><summary>2025 and earlier</summary>

* 🎬 Nov 13, 2025: Release Singularity Cinema, to support short video generation for complex scenarios, check [here](projects/singularity_cinema/README_EN.md)

* 🚀 Nov 12, 2025: Release MS-Agent v1.5.0, which includes the following updates:
  - 🔥 We present [FinResearch](projects/fin_research/README.md), a multi-agent workflow tailored for financial research
  - Support financial data collection via [Akshare](https://github.com/akfamily/akshare) and [Baostock](http://baostock.com/mainContent?file=home.md)
  - Support DagWorkflow for workflow orchestration
  - Optimize the DeepResearch workflow for stability and efficiency
  - FinResearch official documentation: [FinResearch Doc](https://ms-agent-en.readthedocs.io/en/latest/Projects/FinResearch.html)
  - DEMO: [FinResearchStudio](https://modelscope.cn/studios/ms-agent/FinResearch)
  - Examples: [FinResearchExamples](https://www.modelscope.cn/models/ms-agent/fin_research_examples)

* 🚀 Nov 07, 2025: Release MS-Agent v1.4.0, which includes the following updates:
  - 🔥 We present [**MS-Agent Skills**](docs/en/Components/AgentSkills.md), an **Implementation** of [Anthropic-Agent-Skills](https://docs.claude.com/en/docs/agents-and-tools/agent-skills) Protocol.
  - 🔥 Add [Docs](https://ms-agent-en.readthedocs.io/en) and [中文文档](https://ms-agent.readthedocs.io/zh-cn)
  - 🔥 Support Sandbox Framework [ms-enclave](https://github.com/modelscope/ms-enclave)

* 🚀 Sep 22, 2025: Release MS-Agent v1.3.0, which includes the following updates:
  - 🔥 Support [Code Scratch](projects/code_genesis/README.md)
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
* Oct 30, 2023: [Facechain Agent](https://modelscope.cn/studios/CVstudio/facechain_agent_studio/summary) released a local version of the Facechain Agent that can be run locally. For detailed usage instructions, please refer to [Facechain Agent](https://github.com/modelscope/ms-agent/tree/0.8.0#facechain-agent).
* Oct 25, 2023: [Story Agent](https://modelscope.cn/studios/damo/story_agent/summary) released a local version of the Story Agent for generating storybook illustrations. It can be run locally. For detailed usage instructions, please refer to [Story Agent](https://github.com/modelscope/ms-agent/tree/0.8.0#story-agent).
* Sep 20, 2023: [ModelScope GPT](https://modelscope.cn/studios/damo/ModelScopeGPT/summary) offers a local version through gradio that can be run locally. You can navigate to the demo/msgpt/ directory and execute `bash run_msgpt.sh`.
* Sep 4, 2023: Three demos, [demo_qwen](https://github.com/modelscope/ms-agent/blob/0.8.0/demo/demo_qwen_agent.ipynb), [demo_retrieval_agent](https://github.com/modelscope/ms-agent/blob/0.8.0/demo/demo_retrieval_agent.ipynb) and [demo_register_tool](https://github.com/modelscope/ms-agent/blob/0.8.0/demo/demo_register_new_tool.ipynb), have been added, along with detailed tutorials provided.
* Sep 2, 2023: The [preprint paper](https://arxiv.org/abs/2309.00986) associated with this project was published.
* Aug 22, 2023: Support accessing various AI model APIs using ModelScope tokens.
* Aug 7, 2023: The initial version of the modelscope-agent repository was released.

</details>

<a id="features"></a>

## ✨ Features

<a id="a-customizable-agent-harness"></a>

### 🧩 A Customizable Agent Harness

An extensible runtime brings together tool execution, permission checks, and feedback. Use **lifecycle callbacks and Hooks** to integrate business rules, validate plans, and check results. Customize how agents act, when people intervene, and how execution feedback informs the next step.

<a id="context-and-memory-for-long-running-tasks"></a>

### 🧠 Context and Memory for Long-running Tasks

Manage **session history, active context, and project memory** as distinct layers. Preserve full records while pruning tool output and compacting older context, then draw on project memory in later tasks. Cron supports recurring and one-time jobs for ongoing research, monitoring, and maintenance.

<a id="autonomous-collaboration-and-explicit-workflows"></a>

### 🤝 Autonomous Collaboration and Explicit Workflows

Let a lead agent delegate open-ended tasks to specialist sub-agents, or define stages and dependencies with **sequential workflows or directed acyclic graphs (DAGs)**. Choose models, tools, and skills for each role to suit the task, from autonomous exploration to execution in defined stages.

<a id="reusable-agent-skills-with-evaluation-driven-improvement"></a>

### 📈 Reusable Agent Skills with Evaluation-driven Improvement

Package domain knowledge and procedures into skills loaded on demand and reused across tasks. A dedicated **Skill Evolution** workflow uses execution traces and evaluation feedback to revise skills, then tests candidate updates on a validation set, making improvements measurable.

<a id="an-open-ecosystem-with-portable-agent-resources"></a>

### 🔌 An Open Ecosystem with Portable Agent Resources

Connect to multiple model providers, use MCP for external tools, integrate with editors and other agents through ACP / A2A, and extend functionality with plugins. **Agent Hub** converts, merges, and synchronizes instructions, skills, and memory across frameworks so you can reuse them in different environments. Applications can also be exposed as MCP services.

<a id="from-framework-capabilities-to-domain-applications"></a>

### 🎯 From Framework Capabilities to Domain Applications

Built-in applications bring models, tools, and multi-agent collaboration together into **complete workflows** for research, software development, financial analysis, and content creation. Use them directly for specialized tasks, or build on their workflows and domain expertise to create your own applications. [Explore the applications](#applications)

<a id="installation"></a>

## 🚀 Installation

Choose the interface that fits your work. Start with **WebUI** to explore projects, sessions, and tool use. You can also work in the terminal or integrate the SDK into a Python application.

| Interface | Best suited for |
| --- | --- |
| 🖥️ **[WebUI](#webui)** | Work on local projects in the browser, follow task progress, and review results |
| ⌨️ **[TUI](#terminal-and-sdk)** | Chat with agents and manage or resume sessions in the terminal |
| 🛠️ **[CLI](#terminal-and-sdk)** | Run a single task or use agents from scripts |
| 🐍 **[Python SDK](#terminal-and-sdk)** | Customize agents and embed them in applications |

For the default ModelScope provider, get an API key from the [access token page](https://modelscope.cn/my/myaccesstoken).

<a id="webui"></a>

### 🖥️ WebUI

MS-Agent WebUI provides a browser workspace for local projects.
Chat with models, follow tool activity, manage skills and MCP tools, and browse
or edit project files without leaving the interface.

**WebUI demo: organize event materials and create a briefing.** See task planning, approvals for file changes, and result checks in action.

https://github.com/user-attachments/assets/43b3c1cc-555a-4184-b1dd-66e0a21e7a12

> [!IMPORTANT]
> **Install the new WebUI from source.** You will need Git, **Python 3.12+**, **Node.js 22.22.0+**, **pnpm 10.17.1**, and **uv 0.5+**.

If this is your first installation, follow the [environment setup guide](webui/README.md#first-time-setup). If Python and Node.js are already installed, check their versions with `python3 --version` and `node --version`. To create a Python environment, run the following in the directory where you plan to keep the project:

```bash
python3 -m venv ms-agent-env
source ms-agent-env/bin/activate
```

Make sure `python3` is version 3.12+ before creating the environment. If you already have a virtual environment or Conda environment, activate it instead. Then install and start the app in the same terminal:

```bash
npm install --global pnpm@10.17.1
git clone https://github.com/modelscope/ms-agent.git
cd ms-agent
pip install uv
pip install -e .
ms-agent ui
```

On first launch, MS-Agent sets up the backend environment with uv, installs frontend
dependencies, and builds the frontend. Stay connected to the internet until setup finishes.
The browser then opens at the URL printed in the terminal, usually
**http://127.0.0.1:8000**.
In **Settings → Models**, select a provider, click **Edit** to save your API key,
then use **Add model** to enter a model ID. Return to the chat page and select the model
below the message box to start a conversation. Press Ctrl-C to stop the service.

```bash
ms-agent ui --port 8080    # Choose another port
ms-agent ui --no-browser  # Do not open a browser
```

For virtual environment setup, development, Docker, and configuration, see the
[WebUI guide](webui/README.md).

<a id="terminal-and-sdk"></a>

### ⌨️ Terminal and SDK

TUI, CLI, and the Python SDK require **Python 3.10+**; Node.js and pnpm are not needed. You can [install Python with uv](webui/README.md#install-python) if you do not have a compatible version. Otherwise, check `python3 --version`, then create and activate an environment:

```bash
python3 -m venv ms-agent-env
source ms-agent-env/bin/activate
```

If you already have a virtual environment or Conda environment, activate it instead. If you have installed WebUI, skip environment creation and source installation, and configure your API key in the same environment. Otherwise, continue with:

```bash
git clone https://github.com/modelscope/ms-agent.git
cd ms-agent
pip install -e .
```

The following examples use ModelScope inference by default. Set your API key in the terminal where you will run the commands or Python program:

```bash
export MODELSCOPE_API_KEY="your_modelscope_api_key"
```

The first run of the default agent may install additional dependencies for local code execution. Stay connected to the internet and wait for the input prompt or task result.

<a id="tui"></a>

#### ⌨️ TUI

Start the terminal interface and enter a task. Use `/help` to see commands for session management and more, and `/quit` to exit:

```bash
ms-agent tui
```

<a id="cli"></a>

#### 🛠️ CLI

Run a task directly. Omit `--query` to enter interactive mode:

```bash
ms-agent run --query "Introduce the applications of MS-Agent"
```

<a id="python-sdk"></a>

#### 🐍 Python SDK

Save the following as `quickstart.py`, then run `python quickstart.py` in the same terminal where you configured the API key:

```python
import asyncio
from ms_agent import LLMAgent

async def main():
    agent = LLMAgent()
    await agent.run("Introduce the applications of MS-Agent")

asyncio.run(main())
```

<details>
<summary>Optional dependencies and the published release</summary>

From the source repository root, with the Python environment active, install extensions as needed:

```bash
# Vector / hybrid skill search
pip install -e '.[retrieval]'

# Deep research / document parsing
pip install -e '.[research]'

# Video generation
pip install -e '.[cinema]'

# All runtime extensions (includes WebUI; requires Python 3.12+)
pip install -e '.[all]'
```

See the [installation guide](docs/en/GetStarted/Installation.md#optional-dependencies-extras) for the full list. Keep the quotes: macOS defaults to zsh, which otherwise treats square brackets as filename patterns.

The current [PyPI release](https://pypi.org/project/ms-agent/) is 1.6.0. It has the older WebUI and dependency set, lacks the current TUI, and does not provide `retrieval` or `cinema` extras. Install from source when setting up a new environment; see the installation guide for version differences and known installation issues.

</details>

When you open a new terminal, activate the Python environment again. WebUI users can then run `ms-agent ui`; terminal and SDK users also need to set their API key again, or save it in a `.env` file as described in the configuration guide.

<a id="configuration-and-extensions"></a>

### ⚙️ Configuration and Extensions

After your first conversation, choose another model, connect MCP tools, or load skills as needed. Manage these in WebUI settings, or follow the [model and configuration reference](docs/en/Components/Config.md), [tools and MCP guide](docs/en/Components/Tools.md), and [Agent Skills guide](docs/en/Components/AgentSkills.md) for terminal and SDK usage. Try tool calls online in the [MCP Playground](https://modelscope.cn/mcp/playground).

For scheduled jobs with `ms-agent cron`, Agent Hub with `ms-agent agent`, and more commands, see the [CLI reference](docs/en/GetStarted/CLI.md).

<a id="applications"></a>

## 🎯 Applications

These applications use the framework to handle specialized tasks from start to finish. Use them directly or adapt their agent orchestration, tools, and workflows for your own systems. Each linked guide lists the required models and dependencies and explains how to run the project.

<a id="agentic-insight--from-research-questions-to-evidence-based-reports"></a>

### 🔎 Agentic Insight · From Research Questions to Evidence-based Reports

A Researcher agent coordinates Searcher and Reporter agents to investigate open-ended questions through iterative search, evidence collection, and writing. Version 2 stores structured intermediate artifacts in the filesystem and explicitly ties report claims to evidence, making it easier to trace sources, review the research process, and resume work.

As of April 9, 2026, Agentic Insight v2 scored **55.31 on DeepResearch Bench** with Qwen3.5-Plus + GPT 5.2 and ranked second among open-source entries and fifth overall.

[v2 guide](projects/deep_research/v2/README.md) · [Report demo](https://github.com/user-attachments/assets/b1091dfc-9429-46ad-b7f8-7cbd1cf3209b) · [Benchmark results](https://huggingface.co/spaces/muset-ai/DeepResearch-Bench-Leaderboard) · [v1 base and extended workflows](projects/deep_research/README.md)

<a id="codegenesis--from-natural-language-requirements-to-software-projects"></a>

### 💻 CodeGenesis · From Natural-language Requirements to Software Projects

Coordinate requirements analysis, architecture design, file planning, coding, and refinement through a multi-agent development workflow. Generate files in dependency order and iterate using LSP diagnostics and runtime feedback. A seven-stage standard workflow supports detailed project design; a four-stage alternative supports rapid prototyping.

[Design and usage guide](docs/en/Projects/CodeGenesis.md) · [Source code](projects/code_genesis) · [Workflow diagram](projects/code_genesis/asset/workflow.jpg)

<a id="finresearch--financial-data-meets-market-research"></a>

### 📊 FinResearch · Financial Data Meets Market Research

Five specialist agents handle task decomposition, data collection, quantitative analysis, market sentiment analysis, and report writing. Combine structured financial data from AkShare / BaoStock with public information from the web to produce illustrated reports that bring together data analysis, visualizations, and qualitative findings.

[Usage guide](projects/fin_research/README.md) · [Online demo](https://modelscope.cn/studios/ms-agent/FinResearch) · [Example reports](https://www.modelscope.cn/models/ms-agent/fin_research_examples) · [Video demo](https://github.com/user-attachments/assets/a11db8d2-b559-4118-a2c0-2622d46840ef)

<a id="docresearch--turn-source-documents-into-illustrated-reports"></a>

### 📑 DocResearch · Turn Source Documents into Illustrated Reports

Read papers and research material from multiple documents or URLs, extract key information, and generate reports with figures. Supported inputs include PDF, TXT, PPT, and DOCX; export reports as PDF, PPTX, DOCX, or HTML for reading, presentations, and sharing.

[Usage guide](projects/doc_research/README.md) · [Online demo](https://modelscope.cn/studios/ms-agent/DocResearch)

<a id="singularity-cinema--turn-knowledge-into-short-videos"></a>

### 🎬 Singularity Cinema · Turn Knowledge into Short Videos

Start with a topic or plain-text material and coordinate scripting, storyboarding, narration, visual generation, and video composition. Create explainers about science, technology, and economics, combining images, captions, and generated video clips in a customizable creative workflow.

[Usage guide and more videos](projects/singularity_cinema/README_EN.md) · Click the preview to watch “How to Deploy a Large Language Model”:

[![Singularity Cinema: How to Deploy a Large Language Model](projects/singularity_cinema/show_case/deploy_llm_en.png)](http://modelscope.oss-cn-beijing.aliyuncs.com/ms-agent/show_case/video/en_deploy_llm_claude_sonnet_4_5_mllm_gemini_3_pro_image_gen_gemini_3_pro_image.mp4)

<a id="skill-evolution--improve-skills-with-task-feedback"></a>

### 🧬 Skill Evolution · Improve Skills with Task Feedback

For tasks that can be evaluated automatically, run the current skills, collect traces and scores, then use reflection and skill-management agents to create or revise skills. Candidate updates are tested on a validation set and accepted only if scores improve. A SearchQA baseline provides a starting point for studying how task experience can improve a skill library.

[Workflow and usage guide](projects/skill_evolution/README.md)

<a id="documentation"></a>

## 📚 Documentation

- [User guide](https://ms-agent-en.readthedocs.io/en/latest/): getting started, core components, extensions, and configuration.
- [Contributor guide](docs/en/Components/ContributorGuide.md): contribute to the framework and applications.

<a id="license"></a>

## 📄 License

This project is licensed under the [Apache License 2.0](LICENSE).

<a id="star-history"></a>

## ⭐ Star History

[![Star History Chart](https://api.star-history.com/svg?repos=modelscope/ms-agent&type=Date)](https://star-history.com/#modelscope/ms-agent&Date)
