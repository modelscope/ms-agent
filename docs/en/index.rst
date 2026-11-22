MS-Agent Documentation
======================

MS-Agent is built for complex tasks that require sustained planning, execution, and verification.
Compose models, tools, skills, and sub-agents, work through the CLI, TUI, or WebUI,
or embed the same Python SDK in your own application.

Start here
----------

* **Try an agent**: follow the :doc:`installation guide <GetStarted/Installation>`, then the :doc:`quick start <GetStarted/Introduction>`.
* **Work in your browser**: use the :doc:`WebUI workspace <Interfaces/WebUI>` to manage project sessions, files, models, and tools.
* **Build an application**: start with :doc:`agents <Components/LLMAgent>` and :doc:`workflows <Components/Workflow>`, then add tools and skills.
* **Customize execution**: read the :doc:`architecture overview <Architecture/ARCHITECTURE>` for context, permissions, callbacks, and extension points.

.. toctree::
   :maxdepth: 1
   :caption: Getting Started

   GetStarted/Installation
   GetStarted/Introduction

.. toctree::
   :maxdepth: 1
   :caption: Core Components

   Components/LLMAgent
   Components/Workflow

.. toctree::
   :maxdepth: 1
   :caption: Capabilities and Extensions

   Components/Tools
   Components/AgentSkills
   Components/MultimodalSupport

.. toctree::
   :maxdepth: 1
   :caption: Interfaces and Integrations

   Interfaces/WebUI
   Expose Capabilities over MCP <Components/CapabilityGateway>

.. toctree::
   :maxdepth: 1
   :caption: Reference

   Configuration Reference <Components/Config>
   CLI Reference <GetStarted/CLI>
   Models and Providers <Components/SupportedModels>

.. toctree::
   :maxdepth: 1
   :caption: Applications

   Projects/DeepResearch
   Projects/CodeGenesis
   Projects/FinResearch
   Projects/VideoGeneration
   DocResearch <https://github.com/modelscope/ms-agent/blob/main/projects/doc_research/README.md>
   Skill Evolution <https://github.com/modelscope/ms-agent/blob/main/projects/skill_evolution/README.md>

.. toctree::
   :maxdepth: 1
   :caption: Architecture and Design

   Architecture/ARCHITECTURE
   Architecture/ROADMAP
   Architecture/rfcs/plugins
   Architecture/rfcs/hooks-executors
   Architecture/rfcs/mcp-runtime-api

.. toctree::
   :maxdepth: 1
   :caption: Contributing

   Components/ContributorGuide
