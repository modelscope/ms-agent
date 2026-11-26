# MS-Agent: 赋能智能体自主探索的轻量级框架

<p align="center">
    <br>
    <img src="https://raw.githubusercontent.com/modelscope/ms-agent/release/1.7/asset/logo.png" width="420" alt="MS-Agent"/>
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


[**English**](https://github.com/modelscope/ms-agent/blob/release/1.7/README.md)

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
| <img src="https://raw.githubusercontent.com/modelscope/ms-agent/release/1.7/asset/discord_qr.jpg" width="200" alt="Discord 社区二维码"> | <img src="https://raw.githubusercontent.com/modelscope/ms-agent/release/1.7/asset/ms-agent.jpg" width="200" alt="微信群二维码"> |

</details>

旧版体验与文档：[ModelScope-Agent 0.8.0 及更早版本](https://github.com/modelscope/ms-agent/tree/0.8.0)。

## 🎉 新闻

- 🚀 **2026年11月26日：发布 MS-Agent v1.7.0 —— 全面升级多端工作台与可定制 Agent Harness，让复杂长程任务更可控、更易扩展。** 现已同步发布 [PyPI 安装包](https://pypi.org/project/ms-agent/1.7.0/) 与 Docker 镜像，也可在 [魔搭 Agent 实验场](https://www.modelscope.cn/agents/playground) 在线体验（[Release Notes](https://github.com/modelscope/ms-agent/releases/tag/v1.7.0)）：
  - **全新 WebUI 工作台与终端 TUI**：重构浏览器工作台（`ms-agent ui`）并推出默认终端界面（`ms-agent`），与 SDK 共享统一运行时底座，围绕本地项目支持全过程任务观测、运行中动态干预与交互决策、多路径会话分支探索及工作区文件协同。[WebUI 指南](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/user-guide/webui.md) · [TUI 指南](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/user-guide/tui.md)
  - **面向长程任务的多层上下文与记忆架构**：将完整会话历史、模型活跃上下文与跨会话长期记忆解耦治理，支持可组合的上下文裁剪与自动/手动压缩策略、多后端可插拔的统一记忆体系（涵盖本地文件及 ReMe、mem0 等生态适配），并原生兼容 `AGENTS.md` 等主流工作区指令与提示词模板体系，保障复杂长链路任务稳定演进与断点续接。[上下文管理](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/core/context.md) · [记忆架构](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/core/memory.md)
  - **精细化执行控制与生产级安全加固**：在执行控制侧引入可编程生命周期 Hooks、执行过程反馈与 Cron 周期调度，支持精细定制智能体行为边界与自动化节奏；落地分层权限审批、受管凭据静态加密、WebUI 可选单用户认证及 MCP 服务故障隔离，全面提升本地与远程部署的可靠性。[权限](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/core/permissions.md) · [Hooks](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/core/hooks.md) · [凭据安全](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/user-guide/credentials.md)
  - **技能全生命周期治理与评测驱动进化**：优化 Skills 安装与维护体验，提供更新前差异审查与版本回溯，让技能成为可审计的工程资产；支持 **Skill Evolution** 工作流，基于执行轨迹、自动评测与反思反馈迭代修订技能，并在验证集上对比筛选有效演进。[技能管理](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/user-guide/skill-management.md) · [Skill Evolution](https://github.com/modelscope/ms-agent/blob/release/1.7/projects/skill_evolution/README_zh.md)
  - **开放协议与跨框架生态互通**：原生兼容 Claude Code、Codex、OpenClaw 等主流社区插件格式，支持通过 **Agent Hub** 功能实现跨框架的指令、技能与记忆迁移同步，打通 **ACP** 编辑器与客户端接入以及 **A2A** 远端智能体协同。[插件生态](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/core/plugins.md) · [Agent Hub](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/core/agent-hub.md) · [ACP](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/core/acp.md) · [A2A](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/core/a2a.md)

* 🚀 2026年7月13日：支持 **Agent Hub** —— 通过 `ms-agent agent` 命令在本地与远端 ModelScope 仓库之间管理 agent 工作区文件：上传/下载、后台同步（`watch`）、跨框架转换、状态查看、备份与恢复，覆盖 `qoder`、`qwenpaw`、`openclaw`、`hermes`、`nanobot`、`openhuman` 与 `ms-agent`。

- 🏆 **2026年4月9日**：Agentic Insight v2 在 [DeepResearch Bench](https://github.com/Ayanami0730/deep_research_bench) 上位列**开源方案 #2**（总榜 #5）——提交版本得分 **55.31**（Qwen3.5-Plus + GPT 5.2）。[排行榜](https://huggingface.co/spaces/muset-ai/DeepResearch-Bench-Leaderboard) | [Agentic Insight v2](https://github.com/modelscope/ms-agent/blob/release/1.7/projects/deep_research/v2/README.md)。

- 🚀 **2026年3月23日：发布 MS-Agent v1.6.0，主要更新内容如下：**
  - **上下文压缩**：新增上下文压缩机制，支持 Token 用量监控与溢出检测，通过裁剪历史工具输出和 LLM 摘要自动压缩对话上下文。
  - **Agentic Insight v2 增强**：深度研究系统架构与性能大幅优化，基于 GPT5、Qwen3.5-plus/flash 模型组合在 DeepResearch Bench 上的评分达到 **55.43** 分。详情请参考 [Agentic Insight v2](https://github.com/modelscope/ms-agent/tree/main/projects/deep_research/v2)。
  - **知识库搜索**：集成 Sirchmunk 智能检索，支持在 Agent 对话中自动检索本地代码库与文档，详情请参考[检索说明](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/core/retrieval.md)。
  - **多模态模型输入**：支持图片、视频等多模态输入，详情请参考[多模态说明](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/core/multimodal.md)。

* 🚀 **2026年2月6日：发布 MS-Agent v1.6.0rc1，主要更新内容如下：**
  - **Agentic Insight v2**：完整重构的深度研究系统，性能更优、可扩展性更强、可信度更高，提供了 WebUI 入口，详情请参考 [Agentic Insight v2](https://github.com/modelscope/ms-agent/tree/main/projects/deep_research/v2)

* 🚀 **2026年2月4日：发布 MS-Agent v1.6.0rc0，主要更新内容如下：**
  - **Code Genesis**：针对复杂代码生成任务的专项功能，详情请参考 [Code Genesis](https://github.com/modelscope/ms-agent/tree/main/projects/code_genesis)
  - **Singularity Cinema**：动画视频生成工作流的重构版本，详情请参考 [Singularity Cinema](https://github.com/modelscope/ms-agent/tree/main/projects/singularity_cinema)
  - **全新技能框架 (Skills Framework)**：全新设计的技能系统，显著增强了系统的健壮性与可扩展性。详情请参考 [MS-Agent Skills](https://github.com/modelscope/ms-agent/tree/main/ms_agent/skill)
  - **WebUI**：新增 Web 交互界面，支持智能体对话、复杂代码生成以及视频生成工作流。

<details><summary>2025 及更早</summary>

* 🎬 2025.11.13: 发布了“奇点放映室”，用于进行知识类文档的复杂场景短视频制作，具体查看[这里](https://github.com/modelscope/ms-agent/blob/release/1.7/projects/singularity_cinema/README.md)

* 🚀 2025.11.12：发布MS-Agent v1.5.0，包含以下更新：
  - 🔥 新增 [**FinResearch**](https://github.com/modelscope/ms-agent/blob/release/1.7/projects/fin_research/README.md)，支持金融领域的深度研究和分析
  - 支持基于[Akshare](https://github.com/akfamily/akshare)和[Baostock](http://baostock.com/mainContent?file=home.md)的金融数据获取工具
  - 支持以Dag形式编排工作流
  - 优化DeepResearch稳定性与效率
  - 官方文档： [金融深度研究](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/applications/fin-research.md)
  - 魔搭创空间DEMO: [FinResearchStudio](https://modelscope.cn/studios/ms-agent/FinResearch)
  - 报告样例: [FinResearchExamples](https://www.modelscope.cn/models/ms-agent/fin_research_examples)

* 🚀 2025.11.07：发布MS-Agent v1.4.0，包含以下更新：
  - 🔥 新增 [**MS-Agent Skills**](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/core/skills.md), 基于 [**Anthropic-Agent-Skills**](https://docs.claude.com/en/docs/agents-and-tools/agent-skills) 协议实现.
  - 🔥 新增 [中文文档](https://ms-agent.readthedocs.io/zh-cn)和[英文文档](https://ms-agent-en.readthedocs.io/en)
  - 🔥 支持沙箱框架 [ms-enclave](https://github.com/modelscope/ms-enclave)

* 🚀 2025.9.22：发布MS-Agent v1.3.0，包含以下更新：
  - 🔥 支持[Code Scratch](https://github.com/modelscope/ms-agent/blob/release/1.7/projects/code_genesis/README.md)
  - 支持`Memory`用于构建具有长期和短期记忆的智能体
  - 增强DeepResearch工作流
  - 支持RAY加速文档信息提取
  - 支持LLMs的Anthropic API格式

* 🚀 2025.8.28：发布MS-Agent v1.2.0，包含以下更新：
  - DocResearch现在支持推送到`ModelScope`、`HuggingFace`、`GitHub`以便于分享研究报告。详情请参考[Doc Research](https://github.com/modelscope/ms-agent/blob/release/1.7/projects/doc_research/README.md)。
  - DocResearch现在支持将Markdown报告导出为`HTML`、`PDF`、`PPTX`和`DOCX`格式，详情请参考[Doc Research](https://github.com/modelscope/ms-agent/blob/release/1.7/projects/doc_research/README.md)。
  - DocResearch现在支持`TXT`文件处理和文件预处理，详情请参考[Doc Research](https://github.com/modelscope/ms-agent/blob/release/1.7/projects/doc_research/README.md)。


* 🚀 2025.7.31：发布MS-Agent v1.1.0，包含以下更新：
- 🔥 支持[文档研究](https://github.com/modelscope/ms-agent/blob/release/1.7/projects/doc_research/README.md)，演示：[DocResearchStudio](https://modelscope.cn/studios/ms-agent/DocResearch) - 为智能洞察（DeepResearch）添加`通用网络搜索引擎`
  - 为Agent与MCP聊天添加`最大连续运行次数`。

* 🚀 2025.7.18：发布MS-Agent v1.0.0，改进Agent与MCP聊天的体验，并更新[智能洞察](https://github.com/modelscope/ms-agent/blob/release/1.7/projects/deep_research/README.md)的说明文档。

* 🚀 2025.7.16：发布MS-Agent v1.0.0rc0，包含以下更新：
  - 支持Agent与MCP（模型上下文协议）聊天
  - 支持深度研究（智能洞察），参考：[报告演示](https://github.com/modelscope/ms-agent/blob/release/1.7/projects/deep_research/examples/task_20250617a/report.md)，[脚本演示](https://github.com/modelscope/ms-agent/blob/release/1.7/projects/deep_research/run.py)
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

<a id="统一内核的多端交互工作台"></a>

### 🖥️ 统一内核的多端交互工作台

以共享 Python SDK 为统一执行底座，无缝驱动 **WebUI 浏览器工作台（`ms-agent ui`）、原生终端 TUI（`ms-agent`）、CLI 与业务系统嵌入调用**。面向真实项目场景提供透明的执行过程观测、运行中排队与动态插话、结构化交互决策、任意历史节点的会话分支探索以及同屏文件编辑与预览，并内置多厂商模型能力元数据，开箱即可自动对齐上下文预算、思考档位与视觉能力。[WebUI 指南](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/user-guide/webui.md) · [TUI 指南](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/user-guide/tui.md)

<a id="可定制的-agent-harness"></a>

### 🧩 可定制 Harness 与生产安全底座

**可扩展的执行编排与定制**：将工具调用、计划检查与过程反馈组织为高度可定制的运行时架构，通过**生命周期回调与命令型 Hooks** 灵活注入业务规则、审查或改写调用参数并驱动反馈闭环，结合周期任务调度支撑研究、巡检与持续维护工作。

**生产级安全边界与容错加固**：通过**规则级安全护栏与分层权限审批体系**明确自动执行与人工确认边界，配合**受管凭据静态加密**、**WebUI 可选单用户登录认证**以及 **MCP 启动故障隔离机制**，保障本地项目与远程部署的安全可控。[权限](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/core/permissions.md) · [Hooks](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/core/hooks.md) · [凭据安全](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/user-guide/credentials.md)

<a id="面向长任务的上下文与记忆"></a>

### 🧠 面向长任务的上下文与记忆

将**完整会话历史、模型活跃上下文与跨任务项目记忆**三层解耦治理：会话日志完整留痕并支持断点恢复，上下文层支持可组合的工具输出裁剪与自动/手动压缩策略，记忆层提供统一协议与可插拔后端（覆盖本地文件存储及 ReMe、mem0 等生态适配），同时原生兼容 `SOUL.md`、`AGENTS.md`、`PROFILE.md` 等工作区指令与提示词模板，让长周期任务持续保持连贯性与可追溯性。[上下文管理](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/core/context.md) · [记忆](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/core/memory.md) · [工作区个性化](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/core/personalization.md)

<a id="自主协作与显式工作流编排"></a>

### 🤝 自主协作与显式工作流编排

开放式复杂任务可由主智能体动态委派给拥有独立上下文的专用子智能体；阶段与依赖清晰的生产流程，则可通过工作流显式编排。支持为不同角色按需组合模型、工具与技能，实现从自主探索到分步交付的无缝衔接。[子智能体](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/core/subagents.md) · [工作流](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/core/workflows.md)

<a id="可复用可评测的-agent-skills"></a>

### 📈 可治理、可评测进化的 Agent Skills

将领域知识与标准作业流程封装为**按需渐进加载的 Agent Skills**，跨任务高效复用。支持从 GitHub / ModelScope 链接直接安装与升级，提供更新前文件 Diff 审查与一键版本回溯，让技能成为可审计的团队工程资产。[安装与更新](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/user-guide/skill-management.md)

**Skill Evolution** 工作流进一步基于执行轨迹与评测反馈自动提炼修订方案，在验证集上对候选技能进行系统性对比评估并保留历史版本与得分，让经验沉淀与能力演进有据可循。[工作流说明](https://github.com/modelscope/ms-agent/blob/release/1.7/projects/skill_evolution/README_zh.md)

<a id="开放生态与跨框架资产复用"></a>

### 🔌 开放协议与跨框架生态互通

支持接入主流模型服务，构建无生态锁定的开放互操作层：通过 **ACP（Agent Client Protocol）** 实现与主流代码编辑器及交互客户端的双向接入与会话代理；通过 **A2A（Agent-to-Agent）** 支持跨服务远端智能体的能力发现与任务协同。

原生兼容 **Claude Code、Codex、OpenClaw** 等社区插件格式中的技能、命令、Agent 定义、Hooks 与 MCP 配置，并通过 **Agent Hub（`ms-agent agent`）** 实现指令、技能与记忆在 **MS-Agent、QwenPaw、OpenClaw、Hermes** 等框架间的转换、脱敏同步与备份恢复。[插件生态](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/core/plugins.md) · [Agent Hub](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/core/agent-hub.md) · [ACP](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/core/acp.md) · [A2A](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/core/a2a.md)

<a id="从框架能力到专业应用"></a>

### 🎯 从框架能力到专业应用

从深度研究、软件开发到金融分析与内容创作，内置应用将模型、工具和多智能体协作组织为**完整工作流**。既可直接用于专业任务，也可作为二次开发的起点，复用已有的设计与领域经验。[探索应用项目](#应用项目)

<a id="安装"></a>

## 🚀 安装

可从 [PyPI](https://pypi.org/project/ms-agent/)、[Docker 镜像](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/user-guide/deployment.md#docker) 或[源码](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/get-started/quick-start.md#source-install)安装，也可零门槛在线体验。按你的使用方式选择最短路径：

| 使用入口 | 适合的场景 | 最快上手命令 / 链接 |
| :--- | :--- | :--- |
| ☁️ **[Agent 实验场](https://www.modelscope.cn/agents/playground)** | 零安装、在魔搭社区直接体验 MS-Agent 能力 | [立即体验 modelscope.cn/agents/playground](https://www.modelscope.cn/agents/playground) |
| 🖥️ **[WebUI](#webui)** | 浏览器本地项目工作台，实时查看执行过程、编辑文件（Python 3.12+、Node 22.22.0+、pnpm） | `python -m pip install -U "ms-agent[webui]"` → `ms-agent ui` |
| ⌨️ **[TUI / CLI / SDK](#终端与-sdk)** | 终端持续协作、脚本自动化或嵌入 Python 应用（Python 3.10+） | `python -m pip install -U ms-agent` → `ms-agent` |
| 🐳 **[Docker 镜像](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/user-guide/deployment.md#docker)** | 宿主机零 Python / Node 环境，一键启动工作台 | `docker run ... ms-agent:1.7.0`（见[部署指南](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/user-guide/deployment.md#docker)） |

项目默认支持 ModelScope 推理服务，可在[访问令牌页面](https://modelscope.cn/my/myaccesstoken)获取 API Key；以下本地安装步骤均以 PyPI 为例。

<a id="webui"></a>

### 🖥️ WebUI

MS-Agent WebUI 是面向本地项目的智能体工作台。你可以在浏览器中与模型对话、查看工具执行过程、配置技能和 MCP 工具，并直接浏览或编辑项目文件。

**WebUI 演示：活动资料整理与简报生成。** 查看任务规划、写入确认与成果检查的实际过程。

https://github.com/user-attachments/assets/43b3c1cc-555a-4184-b1dd-66e0a21e7a12

> [!IMPORTANT]
> WebUI 需要 **Python 3.12+**、**Node.js 22.22.0+** 和 **pnpm 10.17.1**。

先用 `python3 --version` 和 `node --version` 确认版本，环境安装方法见[快速开始](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/get-started/quick-start.md#准备-python-环境)。确认 Python 为 3.12+ 后，创建并激活虚拟环境；已有环境可直接激活：

```bash
python3 -m venv ms-agent-env
source ms-agent-env/bin/activate
```

在同一终端中安装并启动：

```bash
npm install --global pnpm@10.17.1
python -m pip install -U "ms-agent[webui]"
ms-agent ui
```

安装包已包含构建好的前端，首次启动仍需联网下载 Node 依赖并存入本地缓存。准备完成后，浏览器会打开终端显示的地址，通常是 **http://127.0.0.1:8000**；如果该端口被占用，会自动选择其他端口。在启动终端按 Ctrl-C 可停止服务。

然后配置模型，并发送第一条消息：

1. 打开 **设置 → 模型设置**，选择服务商，点击 **编辑** 填写 API Key 并保存。ModelScope 的 Key 可在[访问令牌页面](https://modelscope.cn/my/myaccesstoken)获取。若服务商未列出，先按[模型设置指南](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/user-guide/model-settings.md)添加。
2. 在该服务商下点击 **添加模型**，填写其支持的模型 ID，例如 ModelScope 的 `Qwen/Qwen3.8-Flash-Next`。保存 Key 不会自动添加或选中模型。
3. 回到对话页，在输入框下方选中模型，权限模式保持为 **总是询问**，发送一句简短请求，例如：“用两句话介绍你能怎样帮助我。”

密钥和会话默认保存在本机的 `~/.ms_agent` 目录。不要提交 `.env` 文件，也不要在聊天内容或截图中暴露 API Key。

后续操作见 [WebUI 教程](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/user-guide/webui.md)；若请求失败，见[故障排查](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/user-guide/troubleshooting.md)。

```bash
ms-agent ui --port 8080    # 指定访问端口
ms-agent ui --no-browser  # 不自动打开浏览器
```

更多安装方式与开发说明见 [WebUI 说明](https://github.com/modelscope/ms-agent/blob/release/1.7/webui/README_ZH.md)。

<a id="终端与-sdk"></a>

### ⌨️ 终端与 SDK

TUI、CLI 和 Python SDK 需要 **Python 3.10+**，无需安装 Node.js 或 pnpm。若已安装 WebUI，直接复用其 Python 环境并配置下方的 API Key。否则，先创建或激活 Python 环境，再从 PyPI 安装；环境准备见[快速开始](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/get-started/quick-start.md#准备-python-环境)：

```bash
python3 -m venv ms-agent-env
source ms-agent-env/bin/activate
python -m pip install -U ms-agent
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
ms-agent
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
<summary>可选依赖</summary>

在同一 Python 环境中按需安装扩展依赖：

| 功能 | 命令 |
| --- | --- |
| 向量 / 混合技能检索 | `python -m pip install -U "ms-agent[retrieval]"` |
| 深度研究 / 文档解析 | `python -m pip install -U "ms-agent[research]"` |
| 视频生成 | `python -m pip install -U "ms-agent[cinema]"` |
| 全部运行时扩展，含 WebUI（Python 3.12+） | `python -m pip install -U "ms-agent[all]"` |

完整列表见[快速开始](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/get-started/quick-start.md#按需增加依赖)。

</details>

重新打开终端后，需要再次激活 Python 环境。WebUI 用户运行 `ms-agent ui` 即可。终端与 SDK 用户还需重新设置 API Key，或将其保存在本地 `.env` 文件中（不要提交该文件）。详见[配置参考](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/development/configuration-reference.md)。

<a id="配置与扩展"></a>

### ⚙️ 配置与扩展

完成首次对话后，可以更换模型、接入 MCP 工具或加载技能。WebUI 可在设置中管理这些配置，详见[模型设置](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/user-guide/model-settings.md)和[技能与 MCP](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/user-guide/skills-mcp.md)。终端与 SDK 的用法见[工具](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/core/tools.md)和[技能](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/core/skills.md)。也可以在 [MCP Playground](https://modelscope.cn/mcp/playground) 在线体验工具调用。

定时任务 `ms-agent cron`、Agent Hub `ms-agent agent` 及更多命令见 [CLI 参考](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/development/cli-reference.md)。

<a id="应用项目"></a>

## 🎯 应用项目

这些应用将框架用于完整的专业任务，也提供可供二次开发的智能体编排、工具与工作流。你可以按场景选择应用，或借鉴其中的设计构建自己的系统。各项目的模型、依赖与运行方式见对应使用指南。

<a id="agentic-insight--从研究问题到证据驱动的报告"></a>

### 🔎 Agentic Insight · 从研究问题到证据驱动的报告

围绕开放式研究问题，Researcher 编排 Searcher 与 Reporter 迭代开展检索、证据整理和报告撰写。v2 将结构化中间产物保存在文件系统中，并将报告论述显式绑定到证据，便于追溯来源、检查研究过程与继续任务。

2026 年 4 月 9 日，Agentic Insight v2 在 **DeepResearch Bench 获得 55.31 分**（Qwen3.5-Plus + GPT 5.2），当时位列开源方案第 2、总榜第 5。

[v2 使用指南](https://github.com/modelscope/ms-agent/blob/release/1.7/projects/deep_research/v2/README_zh.md) · [报告演示](https://github.com/user-attachments/assets/b1091dfc-9429-46ad-b7f8-7cbd1cf3209b) · [评测结果](https://huggingface.co/spaces/muset-ai/DeepResearch-Bench-Leaderboard) · [v1 基础与扩展工作流](https://github.com/modelscope/ms-agent/blob/release/1.7/projects/deep_research/README_zh.md)

<a id="codegenesis--从自然语言需求到软件项目"></a>

### 💻 CodeGenesis · 从自然语言需求到软件项目

将需求分析、架构设计、文件规划、编码与修正组织为多智能体开发流程。按文件依赖关系安排生成顺序，结合 LSP 诊断与运行反馈迭代代码；提供七阶段标准流程和四阶段简化流程，适配需要详细设计的项目与快速原型。

[设计与使用指南](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/applications/code-genesis.md) · [项目源码](https://github.com/modelscope/ms-agent/tree/release/1.7/projects/code_genesis) · [工作流示意](https://raw.githubusercontent.com/modelscope/ms-agent/release/1.7/projects/code_genesis/asset/workflow.jpg)

<a id="finresearch--结合金融数据与市场信息的研究"></a>

### 📊 FinResearch · 结合金融数据与市场信息的研究

由五个专用智能体协作完成任务拆解、数据采集、量化分析、舆情研究与报告汇总。结合 AkShare / BaoStock 的结构化金融数据和互联网公开信息，将数据分析、可视化与定性研究整合为图文报告。

[使用指南](https://github.com/modelscope/ms-agent/blob/release/1.7/projects/fin_research/README_zh.md) · [在线体验](https://modelscope.cn/studios/ms-agent/FinResearch) · [报告样例](https://www.modelscope.cn/models/ms-agent/fin_research_examples) · [视频演示](https://github.com/user-attachments/assets/a11db8d2-b559-4118-a2c0-2622d46840ef)

<a id="docresearch--将多份资料整理为图文报告"></a>

### 📑 DocResearch · 将多份资料整理为图文报告

面向论文阅读与资料研究，接收多份文档或 URL，提取关键信息并生成包含图表的研究报告。支持 PDF、TXT、PPT、DOCX 等输入，以及 PDF、PPTX、DOCX、HTML 报告导出，便于将研究成果用于阅读、汇报和分享。

[使用指南](https://github.com/modelscope/ms-agent/blob/release/1.7/projects/doc_research/README_zh.md) · [在线体验](https://modelscope.cn/studios/ms-agent/DocResearch)

<a id="singularity-cinema--奇点放映室"></a>

### 🎬 Singularity Cinema · 奇点放映室

从主题或纯文本资料出发，编排台本、分镜、配音、画面生成与视频合成，将知识内容转化为短视频。面向科普、技术原理与经济类讲解，可组合图片、字幕和生成视频等素材，定制自己的创作流程。

[使用指南与更多作品](https://github.com/modelscope/ms-agent/blob/release/1.7/projects/singularity_cinema/README.md) · 点击下方预览观看「如何部署大语言模型」：

[![奇点放映室作品：如何部署大语言模型](https://raw.githubusercontent.com/modelscope/ms-agent/release/1.7/projects/singularity_cinema/show_case/deploy_llm.png)](http://modelscope.oss-cn-beijing.aliyuncs.com/ms-agent/show_case/video/deploy_llm_claude_sonnet_4_5_mllm_gemini_3_pro_image_gen_gemini_3_pro_image.mp4)

<a id="skill-evolution--用任务反馈改进技能"></a>

### 🧬 Skill Evolution · 用任务反馈改进技能

面向可自动评测的任务，运行当前技能、收集轨迹与得分，再由反思和技能管理智能体提炼经验、创建或修订技能。工作流在验证集上比较候选技能，最后分别测试初始版本、最终版本和验证表现最佳的版本；内置 SearchQA 基线，便于研究技能如何从任务经验中改进。

[工作流与运行指南](https://github.com/modelscope/ms-agent/blob/release/1.7/projects/skill_evolution/README_zh.md)

<a id="文档"></a>

## 📚 文档

按需直达对应文档（支持在线阅读 **[完整中文文档](https://ms-agent.readthedocs.io/zh-cn/latest/)**）：

| 需求 | 推荐入口 |
| :--- | :--- |
| 零门槛在线试用，或在本地完成第一个任务 | [Agent 实验场](https://www.modelscope.cn/agents/playground) · [本地快速开始](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/get-started/quick-start.md) · [Python SDK](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/get-started/python-sdk.md) |
| 在浏览器或终端中管理项目并掌控长任务过程 | [WebUI 工作台](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/user-guide/webui.md) · [TUI 终端](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/user-guide/tui.md) · [项目与会话分支](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/user-guide/projects-sessions.md) |
| 治理长任务上下文、统一记忆与工作区个性化 | [上下文管理](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/core/context.md) · [记忆架构](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/core/memory.md) · [个性化模板](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/core/personalization.md) · [定时调度](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/user-guide/scheduled-tasks.md) |
| 安装、审查更新或评测进化 Skills | [Skill 安装与更新](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/user-guide/skill-management.md) · [技能机制](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/core/skills.md) · [Skill Evolution](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/applications/skill-evolution.md) |
| 定制执行控制、安全权限与多智能体协作 | [权限](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/core/permissions.md) · [Hooks](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/core/hooks.md) · [Callbacks](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/core/callbacks.md) · [子智能体](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/core/subagents.md) · [工作流](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/core/workflows.md) |
| 复用社区插件、跨框架同步或对接开放协议 | [插件生态](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/core/plugins.md) · [Agent Hub](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/core/agent-hub.md) · [MCP](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/core/mcp-client.md) · [ACP](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/core/acp.md) · [A2A](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/core/a2a.md) |
| 远程部署、凭据加密迁移或排查问题 | [部署与认证](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/user-guide/deployment.md) · [密钥保存与恢复](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/user-guide/credentials.md) · [故障排查](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/user-guide/troubleshooting.md) |

[架构总览](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/development/architecture.md) · [配置参考](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/development/configuration-reference.md) · [CLI 参考](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/development/cli-reference.md) · [贡献指南](https://github.com/modelscope/ms-agent/blob/release/1.7/docs/zh/development/contributing.md)

<a id="许可证"></a>

## 📄 许可证

本项目采用 [Apache License 2.0](https://github.com/modelscope/ms-agent/blob/release/1.7/LICENSE)。

<a id="star-历史"></a>

## ⭐ Star 历史

[![Star History Chart](https://api.star-history.com/svg?repos=modelscope/ms-agent&type=Date)](https://star-history.com/#modelscope/ms-agent&Date)
