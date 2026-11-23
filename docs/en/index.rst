MS-Agent documentation
======================

.. raw:: html

   <section class="ms-hero">
   <p class="eyebrow">BUILD · USE · EXTEND</p>
   <p class="lead">From your first conversation to complex tasks: combine models, tools, skills, and workflows into an agent that fits your work. Start with a familiar interface, then explore the mechanisms behind it.</p>
   <div class="actions"><a href="get-started/quick-start.html">Get started →</a><a href="get-started/introduction.html">What is MS-Agent</a></div>
   </section>

Choose your path
----------------

.. grid:: 1 2 2 2
   :gutter: 3

   .. grid-item-card:: 01 · Getting started
      :link: get-started/quick-start
      :link-type: doc

      Install, configure a model, and run your first task. Developers can start with the Python SDK.

   .. grid-item-card:: 02 · User guide
      :link: user-guide/webui
      :link-type: doc

      Work with files and sessions in the WebUI, TUI, or CLI, and pick up where you left off.

   .. grid-item-card:: 03 · Core modules
      :link: core/configuration
      :link-type: doc

      Understand models, tools, context, and memory. Configure and extend agents through their interfaces.

   .. grid-item-card:: 04 · Domain applications
      :link: applications/deep-research
      :link-type: doc

      Explore research, coding, finance, document, and video workflows with their prerequisites and entry points.

   .. grid-item-card:: 05 · Development & reference
      :link: development/architecture
      :link-type: doc

      Look up configuration, commands, storage, and architecture, or contribute improvements to the framework.

Start with a small task
-----------------------

Complete a conversation, check tool execution and session recovery, then add skills,
MCP connections, or workflows as needed.

.. toctree::
   :hidden:
   :maxdepth: 1
   :caption: Getting started

   get-started/introduction
   get-started/quick-start
   get-started/python-sdk

.. toctree::
   :hidden:
   :maxdepth: 1
   :caption: User guide

   user-guide/webui
   user-guide/tui
   user-guide/cli
   user-guide/projects-sessions
   user-guide/model-settings
   user-guide/credentials
   user-guide/skills-mcp
   user-guide/skill-management
   user-guide/memory
   user-guide/scheduled-tasks
   user-guide/deployment
   user-guide/troubleshooting

.. toctree::
   :hidden:
   :maxdepth: 1
   :caption: Core modules

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
   :caption: Domain applications

   applications/deep-research
   applications/code-genesis
   applications/fin-research
   applications/doc-research
   applications/singularity-cinema
   applications/skill-evolution

.. toctree::
   :hidden:
   :maxdepth: 1
   :caption: Development & reference

   development/configuration-reference
   development/cli-reference
   development/storage
   development/credential-storage
   development/glossary
   development/architecture
   development/contributing
   development/skill-management
   development/skill-management-checklist
   development/rfcs/plugins
   development/rfcs/hooks-executors
   development/rfcs/mcp-runtime-api
