# 简介

**MS-Agent 是轻量、灵活、可定制的开源智能体框架，专为复杂任务的长程自主执行打造。**

MS-Agent 支持自由组合模型、工具、技能与子智能体，基于可定制的 Agent Harness 统筹规划、上下文、权限、执行反馈、记忆与自主调度，持续推进长周期任务。WebUI、TUI、CLI 与 Python SDK 共享同一套能力，开箱即用，也能按需扩展。

## 核心特性

::::{grid} 1 1 2 2
:gutter: 3

:::{grid-item-card} {octicon}`stack;1.1em;sd-mr-2` 模块化构建
:class-card: ms-feature

以配置组合角色、模型、工具与技能，快速搭建专业智能体。开放式任务由主智能体动态委派子智能体，阶段明确的流程交给工作流编排。
+++
[子智能体](../core/subagents.md) · [工作流](../core/workflows.md)
:::

:::{grid-item-card} {octicon}`gear;1.1em;sd-mr-2` 可定制 Harness
:class-card: ms-feature

按需组合上下文管理、权限控制与结果检查，定制智能体的执行策略。通过生命周期扩展点，把业务规则接入规划、工具调用与任务收尾，决定智能体如何行动、何时交由人工确认。
+++
[Callbacks](../core/callbacks.md) · [Hooks](../core/hooks.md) · [权限](../core/permissions.md)
:::

:::{grid-item-card} {octicon}`history;1.1em;sd-mr-2` 长程自主执行
:class-card: ms-feature

灵活定制上下文压缩与记忆模块，保持上下文可控，沉淀项目知识；结合自主调度与分层权限，让长周期任务持续推进，减少人工值守。
+++
[上下文](../core/context.md) · [记忆](../core/memory.md) · [调度](../core/scheduling.md) · [权限](../core/permissions.md)
:::

:::{grid-item-card} {octicon}`sync;1.1em;sd-mr-2` 技能复用与进化
:class-card: ms-feature

将领域知识与操作方法封装为按需加载的 Agent Skills，在不同任务间复用。技能进化机制分析执行轨迹与评测反馈，自动修订技能，只保留通过验证的改进。
+++
[Skills](../core/skills.md) · [Skill Evolution](../applications/skill-evolution.md)
:::

:::{grid-item-card} {octicon}`plug;1.1em;sd-mr-2` 开放协议与生态
:class-card: ms-feature

支持 ModelScope、DashScope、DeepSeek、Kimi、OpenAI、Anthropic 等主流模型服务；通过 MCP 连接外部工具，也能把框架能力发布为 MCP 服务；以 ACP 接入编辑器、以 A2A 协作远程智能体，并兼容 Claude Code、Codex 等社区插件。
+++
[模型](../core/models.md) · [MCP](../core/mcp-client.md) · [ACP](../core/acp.md) · [A2A](../core/a2a.md) · [Agent Hub](../core/agent-hub.md)
:::

:::{grid-item-card} {octicon}`device-desktop;1.1em;sd-mr-2` 多端开箱即用
:class-card: ms-feature

WebUI 集中管理项目、会话与文件，实时呈现执行过程与产物；TUI 适合在终端持续协作，CLI 便于脚本与自动化；Python SDK 支持将框架能力嵌入业务系统。
+++
[WebUI](../user-guide/webui.md) · [TUI](../user-guide/tui.md) · [CLI](../user-guide/cli.md) · [SDK](python-sdk.md)
:::

::::

## 领域应用

同时，MS-Agent 沉淀了覆盖研究、开发与创作的专业应用。它们可以直接用于实际任务，也是二次开发的起点。

::::{grid} 1 2 3 3
:gutter: 2

:::{grid-item-card} 深度研究
:link: ../applications/deep-research
:link-type: doc
:class-card: ms-app

**Agentic Insight** 规划检索、交叉核验证据并撰写研究报告，曾位列 DeepResearch Bench 开源方案第二。
:::

:::{grid-item-card} 软件开发
:link: ../applications/code-genesis
:link-type: doc
:class-card: ms-app

**CodeGenesis** 从需求、架构到编码与验证，以多阶段协作完成项目开发。
:::

:::{grid-item-card} 金融研究
:link: ../applications/fin-research
:link-type: doc
:class-card: ms-app

**FinResearch** 整合金融数据、分析方法与报告规范，多角色协作产出研究报告。
:::

:::{grid-item-card} 文档研究
:link: ../applications/doc-research
:link-type: doc
:class-card: ms-app

**DocResearch** 解析文件与网页链接，综合分析后生成图文结合的多模态报告，可导出 PDF、PPTX 等格式。
:::

:::{grid-item-card} 视频创作
:link: ../applications/singularity-cinema
:link-type: doc
:class-card: ms-app

**Singularity Cinema** 编排脚本、配图、配音与动画，把主题或资料制作成科普短视频。
:::

:::{grid-item-card} 技能进化
:link: ../applications/skill-evolution
:link-type: doc
:class-card: ms-app

**Skill Evolution** 基于执行轨迹与评测反馈迭代技能，在验证集上筛选有效改进。
:::

::::

## 下一步

- [快速开始](quick-start.md)：安装 MS-Agent，在 WebUI 或终端完成第一个任务。
- [Python SDK](python-sdk.md)：在自己的应用中调用智能体。
- [核心模块](../core/configuration.md)：了解各模块的工作方式与扩展接口。
