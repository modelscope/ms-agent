MS-Agent 文档
=============

MS-Agent 面向需要持续规划、执行与验证的复杂任务。你可以组合模型、工具、技能与子智能体，
在 CLI、TUI 或 WebUI 中开展工作，也可以将同一套 Python SDK 集成到自己的应用。

从这里开始
----------

* **体验智能体**：阅读 :doc:`安装指南 <GetStarted/installation>`，然后进入 :doc:`快速开始 <GetStarted/quick-start>`。
* **在浏览器中工作**：使用 :doc:`WebUI 工作台 <Interfaces/webui>`，围绕项目管理会话、文件、模型与工具。
* **构建自己的应用**：从 :doc:`智能体 <Components/llm-agent>` 与 :doc:`工作流 <Components/workflow>` 开始，再接入工具与技能。
* **定制运行机制**：阅读 :doc:`架构总览 <Architecture/ARCHITECTURE>`，了解上下文、权限、回调与扩展点。

.. toctree::
   :maxdepth: 1
   :caption: 快速开始

   GetStarted/installation
   GetStarted/quick-start

.. toctree::
   :maxdepth: 1
   :caption: 核心组件

   Components/llm-agent
   Components/workflow

.. toctree::
   :maxdepth: 1
   :caption: 能力与扩展

   Components/tools
   Components/agent-skills
   Components/multimodal-support

.. toctree::
   :maxdepth: 1
   :caption: 运行与集成

   Interfaces/webui
   作为 MCP 服务提供能力 <Components/capability-gateway>

.. toctree::
   :maxdepth: 1
   :caption: 参考

   配置参考 <Components/config>
   CLI 参考 <GetStarted/cli>
   模型与供应商 <Components/supported-models>

.. toctree::
   :maxdepth: 1
   :caption: 应用项目

   Projects/deep-research
   Projects/code-genesis
   Projects/fin-research
   Projects/video-generation
   DocResearch <https://github.com/modelscope/ms-agent/blob/main/projects/doc_research/README_zh.md>
   Skill Evolution <https://github.com/modelscope/ms-agent/blob/main/projects/skill_evolution/README_zh.md>

.. toctree::
   :maxdepth: 1
   :caption: 架构与设计

   Architecture/ARCHITECTURE
   Architecture/ROADMAP
   Architecture/rfcs/plugins
   Architecture/rfcs/hooks-executors
   Architecture/rfcs/mcp-runtime-api

.. toctree::
   :maxdepth: 1
   :caption: 贡献指南

   Components/contributor-guide
