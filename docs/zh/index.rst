MS-Agent 文档
=============

.. raw:: html

   <section class="ms-hero">
   <p class="eyebrow">构建 · 使用 · 扩展</p>
   <p class="lead">从第一次对话到复杂任务，把模型、工具、技能和工作流组合成适合你的智能体。选择熟悉的界面开始，再逐步了解它的运行机制。</p>
   <div class="actions"><a href="get-started/quick-start.html">立即开始 →</a><a href="get-started/introduction.html">了解 MS-Agent</a></div>
   </section>

选择你的阅读路径
----------------

.. grid:: 1 2 2 2
   :gutter: 3

   .. grid-item-card:: 01 · 快速开始
      :link: get-started/quick-start
      :link-type: doc

      安装、配置模型并完成首个任务；开发者可直接进入 Python SDK。

   .. grid-item-card:: 02 · 使用教程
      :link: user-guide/webui
      :link-type: doc

      在 WebUI、TUI 或 CLI 中处理文件、管理会话，并在下次继续工作。

   .. grid-item-card:: 03 · 核心模块
      :link: core/configuration
      :link-type: doc

      理解模型、工具、上下文和记忆，按接口配置与扩展智能体。

   .. grid-item-card:: 04 · 领域应用
      :link: applications/deep-research
      :link-type: doc

      探索研究、编码、金融、文档和视频工作流，了解各自的入口与前提。

   .. grid-item-card:: 05 · 开发与参考
      :link: development/architecture
      :link-type: doc

      查阅配置字段、命令、存储布局与架构，或为框架贡献改进。

从小任务开始
------------

先完成一次正常对话，再验证工具和会话恢复，最后按需增加技能、MCP 或工作流。

.. toctree::
   :hidden:
   :maxdepth: 1
   :caption: 快速开始

   get-started/introduction
   get-started/quick-start
   get-started/python-sdk

.. toctree::
   :hidden:
   :maxdepth: 1
   :caption: 使用教程

   user-guide/webui
   user-guide/tui
   user-guide/cli
   user-guide/projects-sessions
   user-guide/model-settings
   user-guide/skills-mcp
   user-guide/skill-management
   user-guide/memory
   user-guide/scheduled-tasks
   user-guide/deployment
   user-guide/troubleshooting

.. toctree::
   :hidden:
   :maxdepth: 1
   :caption: 核心模块

   core/configuration
   core/models
   core/messages-events
   core/agents
   core/multimodal
   core/tools
   core/execution-environments
   core/mcp-client
   core/skills
   core/sessions
   core/context
   core/memory
   core/prompts
   core/personalization
   core/retrieval
   core/rag
   core/permissions
   core/callbacks
   core/hooks
   core/plugins
   core/subagents
   core/workflows
   core/scheduling
   core/acp
   core/a2a
   core/agent-hub
   core/capability-gateway

.. toctree::
   :hidden:
   :maxdepth: 1
   :caption: 领域应用

   applications/deep-research
   applications/code-genesis
   applications/fin-research
   applications/doc-research
   applications/singularity-cinema
   applications/skill-evolution

.. toctree::
   :hidden:
   :maxdepth: 1
   :caption: 开发与参考

   development/configuration-reference
   development/cli-reference
   development/storage
   development/glossary
   development/architecture
   development/contributing
   development/skill-management
   development/skill-management-checklist
   development/rfcs/plugins
   development/rfcs/hooks-executors
   development/rfcs/mcp-runtime-api
