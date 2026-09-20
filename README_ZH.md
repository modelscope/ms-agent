# MS-Agent: 赋能智能体自主探索的轻量级框架

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
<a href='https://ms-agent.readthedocs.io/zh-cn/latest/'>
    <img src='https://readthedocs.org/projects/ms-agent/badge/?version=latest' alt='Documentation Status' />
</a>
<a href="https://github.com/modelscope/ms-agent/actions?query=branch%3Amain+workflow%3Acitest++"><img src="https://img.shields.io/github/actions/workflow/status/modelscope/ms-agent/citest.yaml?branch=main&logo=github&label=CI"></a>
<a href="https://github.com/modelscope/ms-agent/blob/main/LICENSE"><img src="https://img.shields.io/github/license/modelscope/ms-agent"></a>
<a href="https://github.com/modelscope/ms-agent/pulls"><img src="https://img.shields.io/badge/PR-welcome-55EB99.svg"></a>
<a href="https://pypi.org/project/ms-agent/"><img src="https://badge.fury.io/py/ms-agent.svg"></a>
<a href="https://pepy.tech/project/ms-agent"><img src="https://static.pepy.tech/badge/ms-agent"></a>
</p>

<p align="center">
<a href="https://trendshift.io/repositories/323" target="_blank"><img src="https://trendshift.io/api/badge/repositories/323" alt="modelscope%2Fmodelscope-agent | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>
</p>


[**English**](README.md)

<a id="简介"></a>

## 👋 简介

**MS-Agent 是一个模块化、可扩展的开源智能体框架，专为复杂任务的长程执行打造。** 支持自由组合模型、工具、技能与子智能体，通过可定制的 Harness 统筹任务规划、上下文管理、权限控制与执行反馈，并结合项目记忆与自主调度，打造能够持续推进复杂任务的专属生产力助手。

框架以 Python SDK 为基础，为 **CLI、TUI 和 WebUI 提供统一的执行与管理能力**，支持从终端、浏览器工作台到业务系统的能力复用，减少多端适配与维护成本。

<p align="center">
<a href="#核心特性"><b>核心特性</b></a> · <a href="#安装"><b>安装</b></a> · <a href="#应用项目"><b>应用项目</b></a> · <a href="#文档"><b>文档</b></a>
</p>

社区交流与反馈：[Discord](https://discord.gg/qmTFPY9byM) · [GitHub Issues](https://github.com/modelscope/ms-agent/issues)

<details>
<summary>微信群与 Discord 二维码</summary>

| Discord | 微信群 |
| :---: | :---: |
| <img src="asset/discord_qr.jpg" width="200" alt="Discord 社区二维码"> | <img src="asset/ms-agent.jpg" width="200" alt="微信群二维码"> |

</details>

旧版体验与文档：[ModelScope-Agent 0.8.0 及更早版本](https://github.com/modelscope/ms-agent/tree/0.8.0)。

## 🎉 新闻

* 🚀 2026年7月13日：支持 **Agent Hub** —— 通过 `ms-agent agent` 命令在本地与远端 ModelScope 仓库之间管理 agent 工作区文件：上传/下载、后台同步（`watch`）、跨框架转换、状态查看、备份与恢复，覆盖 `qoder`、`qwenpaw`、`openclaw`、`hermes`、`nanobot`、`openhuman` 与 `ms-agent`。

- 🏆 **2026年4月9日**：Agentic Insight v2 在 [DeepResearch Bench](https://github.com/Ayanami0730/deep_research_bench) 上位列**开源方案 #2**（总榜 #5）——提交版本得分 **55.31**（Qwen3.5-Plus + GPT 5.2）。[排行榜](https://huggingface.co/spaces/muset-ai/DeepResearch-Bench-Leaderboard) | [Agentic Insight v2](projects/deep_research/v2/README.md)。

- 🚀 **2026年3月23日：发布 MS-Agent v1.6.0，主要更新内容如下：**
  - **上下文压缩**：新增上下文压缩机制，支持 Token 用量监控与溢出检测，通过裁剪历史工具输出和 LLM 摘要自动压缩对话上下文。
  - **Agentic Insight v2 增强**：深度研究系统架构与性能大幅优化，基于 GPT5、Qwen3.5-plus/flash 模型组合在 DeepResearch Bench 上的评分达到 **55.43** 分。详情请参考 [Agentic Insight v2](https://github.com/modelscope/ms-agent/tree/main/projects/deep_research/v2)。
  - **知识库搜索**：集成 Sirchmunk 智能检索，支持在 Agent 对话中自动检索本地代码库与文档，详情请参考[配置文档](docs/zh/Components/config.md)。
  - **多模态模型输入**：支持图片、视频等多模态输入，详情请参考[多模态文档](docs/zh/Components/multimodal-support.md)。

* 🚀 **2026年2月6日：发布 MS-Agent v1.6.0rc1，主要更新内容如下：**
  - **Agentic Insight v2**：完整重构的深度研究系统，性能更优、可扩展性更强、可信度更高，提供了 WebUI 入口，详情请参考 [Agentic Insight v2](https://github.com/modelscope/ms-agent/tree/main/projects/deep_research/v2)

* 🚀 **2026年2月4日：发布 MS-Agent v1.6.0rc0，主要更新内容如下：**
  - **Code Genesis**：针对复杂代码生成任务的专项功能，详情请参考 [Code Genesis](https://github.com/modelscope/ms-agent/tree/main/projects/code_genesis)
  - **Singularity Cinema**：动画视频生成工作流的重构版本，详情请参考 [Singularity Cinema](https://github.com/modelscope/ms-agent/tree/main/projects/singularity_cinema)
  - **全新技能框架 (Skills Framework)**：全新设计的技能系统，显著增强了系统的健壮性与可扩展性。详情请参考 [MS-Agent Skills](https://github.com/modelscope/ms-agent/tree/main/ms_agent/skill)
  - **WebUI**：新增 Web 交互界面，支持智能体对话、复杂代码生成以及视频生成工作流。

<details><summary>2025 及更早</summary>

* 🎬 2025.11.13: 发布了“奇点放映室”，用于进行知识类文档的复杂场景短视频制作，具体查看[这里](projects/singularity_cinema/README.md)

* 🚀 2025.11.12：发布MS-Agent v1.5.0，包含以下更新：
  - 🔥 新增 [**FinResearch**](projects/fin_research/README.md)，支持金融领域的深度研究和分析
  - 支持基于[Akshare](https://github.com/akfamily/akshare)和[Baostock](http://baostock.com/mainContent?file=home.md)的金融数据获取工具
  - 支持以Dag形式编排工作流
  - 优化DeepResearch稳定性与效率
  - 官方文档： [金融深度研究](https://ms-agent.readthedocs.io/zh-cn/latest/Projects/fin-research.html)
  - 魔搭创空间DEMO: [FinResearchStudio](https://modelscope.cn/studios/ms-agent/FinResearch)
  - 报告样例: [FinResearchExamples](https://www.modelscope.cn/models/ms-agent/fin_research_examples)

* 🚀 2025.11.07：发布MS-Agent v1.4.0，包含以下更新：
  - 🔥 新增 [**MS-Agent Skills**](docs/zh/Components/agent-skills.md), 基于 [**Anthropic-Agent-Skills**](https://docs.claude.com/en/docs/agents-and-tools/agent-skills) 协议实现.
  - 🔥 新增 [中文文档](https://ms-agent.readthedocs.io/zh-cn)和[英文文档](https://ms-agent-en.readthedocs.io/en)
  - 🔥 支持沙箱框架 [ms-enclave](https://github.com/modelscope/ms-enclave)

* 🚀 2025.9.22：发布MS-Agent v1.3.0，包含以下更新：
  - 🔥 支持[Code Scratch](projects/code_genesis/README.md)
  - 支持`Memory`用于构建具有长期和短期记忆的智能体
  - 增强DeepResearch工作流
  - 支持RAY加速文档信息提取
  - 支持LLMs的Anthropic API格式

* 🚀 2025.8.28：发布MS-Agent v1.2.0，包含以下更新：
  - DocResearch现在支持推送到`ModelScope`、`HuggingFace`、`GitHub`以便于分享研究报告。详情请参考[Doc Research](projects/doc_research/README.md)。
  - DocResearch现在支持将Markdown报告导出为`HTML`、`PDF`、`PPTX`和`DOCX`格式，详情请参考[Doc Research](projects/doc_research/README.md)。
  - DocResearch现在支持`TXT`文件处理和文件预处理，详情请参考[Doc Research](projects/doc_research/README.md)。


* 🚀 2025.7.31：发布MS-Agent v1.1.0，包含以下更新：
- 🔥 支持[文档研究](projects/doc_research/README.md)，演示：[DocResearchStudio](https://modelscope.cn/studios/ms-agent/DocResearch) - 为智能洞察（DeepResearch）添加`通用网络搜索引擎`
  - 为Agent与MCP聊天添加`最大连续运行次数`。

* 🚀 2025.7.18：发布MS-Agent v1.0.0，改进Agent与MCP聊天的体验，并更新[智能洞察](projects/deep_research/README.md)的说明文档。

* 🚀 2025.7.16：发布MS-Agent v1.0.0rc0，包含以下更新：
  - 支持Agent与MCP（模型上下文协议）聊天
  - 支持深度研究（智能洞察），参考：[报告演示](projects/deep_research/examples/task_20250617a/report.md)，[脚本演示](projects/deep_research/run.py)
  - 支持[MCP-Playground](https://modelscope.cn/mcp/playground)
  - 为Agent聊天添加回调机制

* 🔥🔥🔥2024年8月8日：Modelscope-Agent发布了一个新的基于图的代码生成工具[CodexGraph](https://arxiv.org/abs/2408.03910)，它已被证明在各种代码相关任务上有效且通用，请查看[示例](https://github.com/modelscope/modelscope-agent/tree/master/apps/codexgraph_agent)。
* 🔥🔥2024年8月1日：一个高效可靠的数据科学助手正在Modelscope-Agent上运行，请在[示例](https://github.com/modelscope/modelscope-agent/tree/master/apps/datascience_assistant)中查看详情。
* 🔥2024年7月17日：Modelscope-Agent-Server上的并行工具调用，请在[文档](https://github.com/modelscope/modelscope-agent/blob/master/modelscope_agent_servers/README.md)中查看详情。
* 🔥2024年6月17日：基于LLama-index升级RAG流程，允许用户通过不同策略和模态混合搜索知识，请在[文档](https://github.com/modelscope/modelscope-agent/blob/master/modelscope_agent/rag/README_zh.md)中查看详情。
* 🔥2024年6月6日：通过 [Modelscope-Agent-Server](https://github.com/modelscope/modelscope-agent/blob/master/modelscope_agent_servers/README.md)，**Qwen2** 可以通过 OpenAI SDK 使用工具调用能力，详情请查看[文档](https://github.com/modelscope/modelscope-agent/blob/master/docs/llms/qwen2_tool_calling.md)。
* 🔥2024年6月4日：Modelscope-Agent 支持 Mobile-Agent-V2[arxiv](https://arxiv.org/abs/2406.01014)，基于 Android Adb 环境，请在[应用](https://github.com/modelscope/modelscope-agent/tree/master/apps/mobile_agent)中查看。
* 🔥2024年5月17日：Modelscope-Agent 在 [gradio](https://github.com/modelscope/modelscope-agent/tree/master/apps/multi_roles_chat_room) 中支持多角色房间聊天。
* 2024年5月14日：Modelscope-Agent 在 `RolePlay` 智能体中支持图像输入，使用最新的 OpenAI 模型 `GPT-4o`。开发者可以通过指定 `image_url` 参数来体验此功能。
* 2024年5月10日：Modelscope-Agent 推出了用户友好的 `Assistant API`，并提供了在隔离、安全容器中执行实用程序的 `Tools API`，请查看[文档](https://github.com/modelscope/modelscope-agent/blob/master/modelscope_agent_servers/)
* 2024年4月12日：多智能体解决方案的 [Ray](https://docs.ray.io/en/latest/) 版本已在 modelscope-agent 上线，请查看[文档](https://github.com/modelscope/modelscope-agent/blob/master/modelscope_agent/multi_agents_utils/README.md)
* 2024年3月15日：Modelscope-Agent 和 [AgentFabric](https://github.com/modelscope/modelscope-agent/tree/master/apps/agentfabric)（GPTs 的开源版本）正在 [modelscope studio](https://modelscope.cn/studios/agent) 的生产环境中运行。
* 2024年2月10日：在中国新年期间，我们将modelscope agent升级到v0.3版本，以便开发者通过编码更方便地定制各种类型的智能体，并使多智能体演示更容易实现。更多详情，您可以参考[#267](https://github.com/modelscope/modelscope-agent/pull/267)和[#293](https://github.com/modelscope/modelscope-agent/pull/293)。

* 2023年11月26日：[AgentFabric](https://github.com/modelscope/modelscope-agent/tree/master/apps/agentfabric)现在支持在ModelScope的[创作空间](https://modelscope.cn/studios/modelscope/AgentFabric/summary)中协作使用，允许在创作空间中分享自定义应用程序。此次更新还包括最新的[GTE](https://modelscope.cn/models/damo/nlp_gte_sentence-embedding_chinese-base/summary)文本嵌入集成。

* 2023年11月17日：[AgentFabric](https://github.com/modelscope/modelscope-agent/tree/master/apps/agentfabric)发布，这是一个交互式框架，旨在促进创建针对各种现实世界应用的智能体。

* 2023年10月30日：[Facechain Agent](https://modelscope.cn/studios/CVstudio/facechain_agent_studio/summary)发布了可以在本地运行的Facechain Agent本地版本。详细使用说明请参考[Facechain Agent](https://github.com/modelscope/ms-agent/tree/0.8.0#facechain-agent)。

* 2023年10月25日：[Story Agent](https://modelscope.cn/studios/damo/story_agent/summary)发布了用于生成故事书插图的Story Agent本地版本。它可以在本地运行。详细使用说明请参考[Story Agent](https://github.com/modelscope/ms-agent/tree/0.8.0#story-agent)。

* 2023年9月20日：[ModelScope GPT](https://modelscope.cn/studios/damo/ModelScopeGPT/summary)通过gradio提供了可以在本地运行的本地版本。您可以导航到demo/msgpt/目录并执行`bash run_msgpt.sh`。
* 2023年9月4日：新增了三个演示，[demo_qwen](https://github.com/modelscope/ms-agent/blob/0.8.0/demo/demo_qwen_agent.ipynb)、[demo_retrieval_agent](https://github.com/modelscope/ms-agent/blob/0.8.0/demo/demo_retrieval_agent.ipynb) 和 [demo_register_tool](https://github.com/modelscope/ms-agent/blob/0.8.0/demo/demo_register_new_tool.ipynb)，并提供了详细的教程。
* 2023年9月2日：发布了与该项目相关的[预印本论文](https://arxiv.org/abs/2309.00986)。
* 2023年8月22日：支持使用 ModelScope 令牌访问各种 AI 模型 API。
* 2023年8月7日：发布了 modelscope-agent 仓库的初始版本。

</details>

<a id="核心特性"></a>

## ✨ 核心特性

<a id="可定制的-agent-harness"></a>

### 🧩 可定制的 Agent Harness

将工具执行、权限确认与过程反馈组织成可扩展的运行机制。通过**生命周期回调与 Hooks** 接入业务规则、计划检查和结果验证，让开发者能够定制智能体如何行动、何时接受人工干预，以及怎样利用执行反馈继续工作。

<a id="面向长任务的上下文与记忆"></a>

### 🧠 面向长任务的上下文与记忆

将**会话历史、当前上下文与项目记忆**分层管理：保留完整记录，按需裁剪工具输出、压缩历史内容，并在后续任务中利用项目记忆。配合 Cron 的定时、周期与单次任务调度，支持需要反复推进的研究、巡检和维护工作。

<a id="自主协作与显式工作流编排"></a>

### 🤝 自主协作与显式工作流编排

开放式任务可以由主智能体动态委派给专用子智能体；阶段和依赖明确的任务，则可使用**链式或 DAG 工作流**编排。为不同角色选择模型、工具与技能，从自主探索到分步交付，按任务需要组织协作。

<a id="可复用可评测的-agent-skills"></a>

### 📈 可复用、可评测的 Agent Skills

将领域知识与操作方法组织为按需加载的技能，供不同任务复用。独立的 **Skill Evolution** 工作流进一步利用执行轨迹和评测反馈修订技能，通过验证集筛选更新，为经验积累与能力改进提供可检验的依据。

<a id="开放生态与跨框架资产复用"></a>

### 🔌 开放生态与跨框架资产复用

接入多家模型服务，通过 MCP 连接外部工具，通过 ACP / A2A 对接编辑器与其他智能体，并利用插件组合扩展能力。**Agent Hub** 支持跨框架转换、合并和同步指令、技能与记忆，让已有积累可以随工作环境迁移；应用也可作为 MCP 服务供外部智能体调用。

<a id="从框架能力到专业应用"></a>

### 🎯 从框架能力到专业应用

从深度研究、软件开发到金融分析与内容创作，内置应用将模型、工具和多智能体协作组织为**完整工作流**。既可直接用于专业任务，也可作为二次开发的起点，复用已有的设计与领域经验。[探索应用项目](#应用项目)

<a id="安装"></a>

## 🚀 安装

选择适合你的入口。推荐先从 **WebUI** 体验项目、会话与工具协作；也可以直接使用终端界面，或将 SDK 集成到 Python 应用中。

| 使用入口 | 适合的场景 |
| --- | --- |
| 🖥️ **[WebUI](#webui)** | 在浏览器中处理本地项目、查看执行过程与成果 |
| ⌨️ **[TUI](#终端与-sdk)** | 在终端持续对话、管理和恢复会话 |
| 🛠️ **[CLI](#终端与-sdk)** | 执行单次任务，或与脚本配合使用 |
| 🐍 **[Python SDK](#终端与-sdk)** | 自定义智能体并集成到应用 |

项目支持使用默认的 ModelScope 服务商，可在[访问令牌页面](https://modelscope.cn/my/myaccesstoken)获取 API Key。

<a id="webui"></a>

### 🖥️ WebUI

MS-Agent WebUI 是面向本地项目的智能体工作台。你可以在浏览器中与模型对话、查看工具执行过程、配置技能和 MCP 工具，并直接浏览或编辑项目文件。

**WebUI 演示：活动资料整理与简报生成。** 查看任务规划、写入确认与成果检查的实际过程。

https://github.com/user-attachments/assets/43b3c1cc-555a-4184-b1dd-66e0a21e7a12

> [!IMPORTANT]
> **新版 WebUI 请优先从源码安装。** 需要 Git、**Python 3.12+**、**Node.js 22.22.0+**、**pnpm 10.17.1** 和 **uv 0.5+**。

首次配置环境，请先完成 [环境准备](webui/README_ZH.md#首次配置)。已有 Python 和 Node.js 时，用 `python3 --version`、`node --version` 确认版本；如果尚未创建 Python 环境，可在准备存放项目的目录执行：

```bash
python3 -m venv ms-agent-env
source ms-agent-env/bin/activate
```

创建前请确认 `python3` 为 3.12+。已有虚拟环境或 Conda 环境的用户直接激活即可。然后在同一终端中安装并启动：

```bash
npm install --global pnpm@10.17.1
git clone https://github.com/modelscope/ms-agent.git
cd ms-agent
pip install uv
pip install -e .
ms-agent ui
```

首次启动会通过 uv 准备后端环境、安装前端依赖并构建页面和样式，需要保持网络连接。就绪后浏览器会打开终端显示的地址，通常是 **http://127.0.0.1:8000**。在 **设置 → 模型设置** 选择服务商，点击 **编辑** 保存 API Key，再通过 **添加模型** 填写模型 ID。返回对话页，在输入框下方选中该模型即可开始使用。按 Ctrl-C 停止服务。

```bash
ms-agent ui --port 8080    # 指定访问端口
ms-agent ui --no-browser  # 不自动打开浏览器
```

虚拟环境准备、开发、Docker 和配置说明见 [WebUI 完整指南](webui/README_ZH.md)。

<a id="终端与-sdk"></a>

### ⌨️ 终端与 SDK

TUI、CLI 和 Python SDK 需要 **Python 3.10+**，无需安装 Node.js 或 pnpm。还没有合适的 Python 时，可用 [uv 准备 Python 环境](webui/README_ZH.md#安装-python)。已有 Python 时，先用 `python3 --version` 确认版本，再创建并激活环境：

```bash
python3 -m venv ms-agent-env
source ms-agent-env/bin/activate
```

已有虚拟环境或 Conda 环境的用户直接激活即可。已完成 WebUI 安装的用户，可跳过环境创建和源码安装，直接在同一环境中配置 API Key。其余用户继续执行：

```bash
git clone https://github.com/modelscope/ms-agent.git
cd ms-agent
pip install -e .
```

以下示例默认使用 ModelScope 推理服务，在运行命令或 Python 程序的终端中设置：

```bash
export MODELSCOPE_API_KEY="your_modelscope_api_key"
```

首次使用默认智能体时，会按需安装本地代码执行所需的额外依赖。请保持网络连接，等待出现输入提示或任务结果。

<a id="tui"></a>

#### ⌨️ TUI

启动终端交互界面，输入任务即可开始。使用 `/help` 查看会话管理等命令，使用 `/quit` 退出：

```bash
ms-agent tui
```

<a id="cli"></a>

#### 🛠️ CLI

直接执行一个任务；不传 `--query` 时进入交互模式：

```bash
ms-agent run --query "介绍一下 MS-Agent 的应用场景"
```

<a id="python-sdk"></a>

#### 🐍 Python SDK

将下面的代码保存为 `quickstart.py`，在已配置 API Key 的同一终端中运行 `python quickstart.py`：

```python
import asyncio
from ms_agent import LLMAgent

async def main():
    agent = LLMAgent()
    await agent.run("介绍一下 MS-Agent 的应用场景")

asyncio.run(main())
```

<details>
<summary>可选依赖与已发布版本</summary>

在源码仓库根目录、已激活的 Python 环境中，可以按需安装扩展依赖：

```bash
# 向量 / 混合技能检索
pip install -e '.[retrieval]'

# 深度研究 / 文档解析
pip install -e '.[research]'

# 视频生成
pip install -e '.[cinema]'

# 全部运行时扩展（包含 WebUI，需 Python 3.12+）
pip install -e '.[all]'
```

完整列表见[安装指南](docs/zh/GetStarted/installation.md#可选依赖extras)。这些命令中的引号需要保留，避免 macOS 默认的 zsh 将方括号作为文件匹配表达式。

[PyPI 已发布版本](https://pypi.org/project/ms-agent/)目前为 1.6.0，使用旧版 WebUI 和依赖组合，不包含当前源码的 TUI，也没有 `retrieval`、`cinema` extras。新环境请使用上面的源码安装；版本差异与已知安装问题见安装指南。

</details>

重新打开终端后，需要再次激活 Python 环境。WebUI 用户运行 `ms-agent ui` 即可；终端与 SDK 用户还需重新设置 API Key，或按配置文档将其保存在 `.env` 文件中。

<a id="配置与扩展"></a>

### ⚙️ 配置与扩展

完成首次对话后，可以按需更换模型、接入 MCP 工具或加载技能。WebUI 可在设置中管理这些配置；终端与 SDK 的用法见[模型与配置参考](docs/zh/Components/config.md)、[工具与 MCP](docs/zh/Components/tools.md)和[Agent Skills](docs/zh/Components/agent-skills.md)。也可以在 [MCP Playground](https://modelscope.cn/mcp/playground) 在线体验工具调用。

定时任务 `ms-agent cron`、Agent Hub `ms-agent agent` 及更多命令见 [CLI 参考](docs/zh/GetStarted/cli.md)。

<a id="应用项目"></a>

## 🎯 应用项目

这些应用将框架用于完整的专业任务，也提供可供二次开发的智能体编排、工具与工作流。你可以按场景选择应用，或借鉴其中的设计构建自己的系统。各项目的模型、依赖与运行方式见对应使用指南。

<a id="agentic-insight--从研究问题到证据驱动的报告"></a>

### 🔎 Agentic Insight · 从研究问题到证据驱动的报告

围绕开放式研究问题，Researcher 编排 Searcher 与 Reporter 迭代开展检索、证据整理和报告撰写。v2 将结构化中间产物保存在文件系统中，并将报告论述显式绑定到证据，便于追溯来源、检查研究过程与继续任务。

2026 年 4 月 9 日，Agentic Insight v2 在 **DeepResearch Bench 获得 55.31 分**（Qwen3.5-Plus + GPT 5.2），当时位列开源方案第 2、总榜第 5。

[v2 使用指南](projects/deep_research/v2/README_zh.md) · [报告演示](https://github.com/user-attachments/assets/b1091dfc-9429-46ad-b7f8-7cbd1cf3209b) · [评测结果](https://huggingface.co/spaces/muset-ai/DeepResearch-Bench-Leaderboard) · [v1 基础与扩展工作流](projects/deep_research/README_zh.md)

<a id="codegenesis--从自然语言需求到软件项目"></a>

### 💻 CodeGenesis · 从自然语言需求到软件项目

将需求分析、架构设计、文件规划、编码与修正组织为多智能体开发流程。按文件依赖关系安排生成顺序，结合 LSP 诊断与运行反馈迭代代码；提供七阶段标准流程和四阶段简化流程，适配需要详细设计的项目与快速原型。

[设计与使用指南](docs/zh/Projects/code-genesis.md) · [项目源码](projects/code_genesis) · [工作流示意](projects/code_genesis/asset/workflow.jpg)

<a id="finresearch--结合金融数据与市场信息的研究"></a>

### 📊 FinResearch · 结合金融数据与市场信息的研究

由五个专用智能体协作完成任务拆解、数据采集、量化分析、舆情研究与报告汇总。结合 AkShare / BaoStock 的结构化金融数据和互联网公开信息，将数据分析、可视化与定性研究整合为图文报告。

[使用指南](projects/fin_research/README_zh.md) · [在线体验](https://modelscope.cn/studios/ms-agent/FinResearch) · [报告样例](https://www.modelscope.cn/models/ms-agent/fin_research_examples) · [视频演示](https://github.com/user-attachments/assets/a11db8d2-b559-4118-a2c0-2622d46840ef)

<a id="docresearch--将多份资料整理为图文报告"></a>

### 📑 DocResearch · 将多份资料整理为图文报告

面向论文阅读与资料研究，接收多份文档或 URL，提取关键信息并生成包含图表的研究报告。支持 PDF、TXT、PPT、DOCX 等输入，以及 PDF、PPTX、DOCX、HTML 报告导出，便于将研究成果用于阅读、汇报和分享。

[使用指南](projects/doc_research/README_zh.md) · [在线体验](https://modelscope.cn/studios/ms-agent/DocResearch)

<a id="singularity-cinema--奇点放映室"></a>

### 🎬 Singularity Cinema · 奇点放映室

从主题或纯文本资料出发，编排台本、分镜、配音、画面生成与视频合成，将知识内容转化为短视频。面向科普、技术原理与经济类讲解，可组合图片、字幕和生成视频等素材，定制自己的创作流程。

[使用指南与更多作品](projects/singularity_cinema/README.md) · 点击下方预览观看「如何部署大语言模型」：

[![奇点放映室作品：如何部署大语言模型](projects/singularity_cinema/show_case/deploy_llm.png)](http://modelscope.oss-cn-beijing.aliyuncs.com/ms-agent/show_case/video/deploy_llm_claude_sonnet_4_5_mllm_gemini_3_pro_image_gen_gemini_3_pro_image.mp4)

<a id="skill-evolution--用任务反馈改进技能"></a>

### 🧬 Skill Evolution · 用任务反馈改进技能

面向可自动评测的任务，运行当前技能、收集轨迹与得分，再由反思和技能管理智能体提炼经验、创建或修订技能。候选更新经过验证集筛选，只有表现提升才被接受；内置 SearchQA 基线，便于研究技能如何从任务经验中持续改进。

[工作流与运行指南](projects/skill_evolution/README_zh.md)

<a id="文档"></a>

## 📚 文档

- [用户文档](https://ms-agent.readthedocs.io/zh-cn/latest/)：快速开始、核心组件、能力扩展与配置参考。
- [贡献指南](docs/zh/Components/contributor-guide.md)：参与框架与应用开发。

<a id="许可证"></a>

## 📄 许可证

本项目采用 [Apache License 2.0](LICENSE)。

<a id="star-历史"></a>

## ⭐ Star 历史

[![Star History Chart](https://api.star-history.com/svg?repos=modelscope/ms-agent&type=Date)](https://star-history.com/#modelscope/ms-agent&Date)
