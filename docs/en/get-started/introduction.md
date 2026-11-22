# Introduction

**MS-Agent is a lightweight, flexible, and customizable open-source agent framework built for long-horizon execution of complex tasks.**

MS-Agent lets you freely combine models, tools, skills, and subagents. Built on a customizable Agent Harness, it coordinates planning, context, permissions, execution feedback, memory, and autonomous scheduling to carry long-running tasks forward. The WebUI, TUI, CLI, and Python SDK share the same capabilities—ready out of the box and easy to extend.

## Key features

::::{grid} 1 1 2 2
:gutter: 3

:::{grid-item-card} {octicon}`stack;1.1em;sd-mr-2` Modular by design
:class-card: ms-feature

Assemble specialized agents from roles, models, tools, and skills in configuration. A lead agent delegates open-ended work to subagents on the fly, while well-defined processes run as workflows.
+++
[Subagents](../core/subagents.md) · [Workflows](../core/workflows.md)
:::

:::{grid-item-card} {octicon}`gear;1.1em;sd-mr-2` Customizable harness
:class-card: ms-feature

Combine context management, permission control, and result checks to shape how the agent executes. Lifecycle extension points bring your business rules into planning, tool calls, and task completion—deciding how the agent acts and when a person signs off.
+++
[Callbacks](../core/callbacks.md) · [Hooks](../core/hooks.md) · [Permissions](../core/permissions.md)
:::

:::{grid-item-card} {octicon}`history;1.1em;sd-mr-2` Long-horizon execution
:class-card: ms-feature

Customize context compaction and memory to keep context under control and retain project knowledge. Autonomous scheduling and layered permissions keep long-running tasks moving with less human supervision.
+++
[Context](../core/context.md) · [Memory](../core/memory.md) · [Scheduling](../core/scheduling.md) · [Permissions](../core/permissions.md)
:::

:::{grid-item-card} {octicon}`sync;1.1em;sd-mr-2` Reusable, evolving skills
:class-card: ms-feature

Package domain knowledge and procedures as on-demand Agent Skills reused across tasks. Skill evolution analyzes execution traces and evaluation feedback to revise skills automatically, keeping only validated improvements.
+++
[Skills](../core/skills.md) · [Skill Evolution](../applications/skill-evolution.md)
:::

:::{grid-item-card} {octicon}`plug;1.1em;sd-mr-2` Open protocols and ecosystem
:class-card: ms-feature

Work with ModelScope, DashScope, DeepSeek, Kimi, OpenAI, Anthropic, and other providers. Connect tools through MCP or publish framework capabilities as MCP services, reach editors through ACP and remote agents through A2A, and reuse community plugins from Claude Code, Codex, and more.
+++
[Models](../core/models.md) · [MCP](../core/mcp-client.md) · [ACP](../core/acp.md) · [A2A](../core/a2a.md) · [Agent Hub](../core/agent-hub.md)
:::

:::{grid-item-card} {octicon}`device-desktop;1.1em;sd-mr-2` Ready in every interface
:class-card: ms-feature

The WebUI brings projects, sessions, and files together with live execution and artifacts. The TUI supports continuous terminal work, the CLI fits scripts and automation, and the Python SDK lets you embed framework capabilities in business systems.
+++
[WebUI](../user-guide/webui.md) · [TUI](../user-guide/tui.md) · [CLI](../user-guide/cli.md) · [SDK](python-sdk.md)
:::

::::

## Application ecosystem

MS-Agent also offers professional applications for research, development, and content creation—ready for real work and a starting point for your own.

::::{grid} 1 2 3 3
:gutter: 2

:::{grid-item-card} Deep research
:link: ../applications/deep-research
:link-type: doc
:class-card: ms-app

**Agentic Insight** plans searches, cross-checks evidence, and writes research reports, and has ranked #2 among open-source entries on DeepResearch Bench.
:::

:::{grid-item-card} Software development
:link: ../applications/code-genesis
:link-type: doc
:class-card: ms-app

**CodeGenesis** takes a project from requirements and architecture through coding and verification in coordinated stages.
:::

:::{grid-item-card} Financial research
:link: ../applications/fin-research
:link-type: doc
:class-card: ms-app

**FinResearch** combines financial data, analysis methods, and reporting standards in a multi-role research workflow.
:::

:::{grid-item-card} Document research
:link: ../applications/doc-research
:link-type: doc
:class-card: ms-app

**DocResearch** parses files and web links into multimodal reports that combine text and images, with export to PDF, PPTX, and more.
:::

:::{grid-item-card} Video creation
:link: ../applications/singularity-cinema
:link-type: doc
:class-card: ms-app

**Singularity Cinema** orchestrates scripts, images, narration, and animation to turn a topic or document into an explainer video.
:::

:::{grid-item-card} Skill evolution
:link: ../applications/skill-evolution
:link-type: doc
:class-card: ms-app

**Skill Evolution** iterates on skills from execution traces and evaluation feedback, keeping improvements that pass validation.
:::

::::

## Next steps

- [Quick start](quick-start.md): install MS-Agent and complete a first task in the WebUI or terminal.
- [Python SDK](python-sdk.md): call agents from your own application.
- [Core modules](../core/configuration.md): learn how each module works and extends.
