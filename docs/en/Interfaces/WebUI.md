---
slug: webui
title: WebUI Workspace
description: Manage MS-Agent project sessions, files, models, skills, and MCP tools in your browser.
---

# WebUI Workspace

MS-Agent WebUI brings agent conversations and project files into one browser workspace. Ask agents to research, write code, or process files, follow their execution, and continue tasks in existing sessions.

## Work by project

- **Projects and sessions:** open a local workspace, create multiple sessions for a project, and retain task history.
- **Execution visibility:** follow streamed responses, reasoning content, and tool calls; use permission interactions for operations requiring confirmation.
- **Files and artifacts:** browse, preview, and edit project files alongside conversations and generated results.
- **Models and extensions:** configure model providers, select project skills, connect MCP tools, and manage memory.

## Get started

Environment requirements, launch commands, source development, and Docker deployment are maintained in the [WebUI guide](https://github.com/modelscope/ms-agent/blob/main/webui/README.md). WebUI has its own environment requirements; follow that guide when preparing it.

After launching:

1. Add a provider, API key, and model in **Settings → Models**.
2. Create a project or open an existing folder, then configure skills and MCP tools for your task.
3. Create a session, select a model, and describe the task. Attach files or images when needed.
4. Follow tool activity and results, continue the conversation, or edit files in the workspace.

## Relationship to the SDK and project workflows

WebUI reuses the SDK's agent execution, project and session storage, configuration, skills, and MCP management. The interface handles interaction and presentation while the SDK provides execution logic, allowing framework capabilities to be shared with the CLI and TUI.

General project conversations and the repository's specialized workflows have their own entry points. For DeepResearch, CodeGenesis, FinResearch, and video generation, follow the [DeepResearch](../Projects/DeepResearch.md), [CodeGenesis](../Projects/CodeGenesis.md), [FinResearch](../Projects/FinResearch.md), and [video generation](../Projects/VideoGeneration.md) guides and project READMEs.

## Related reading

- [Quick start](../GetStarted/Introduction.md)
- [Configuration reference](../Components/Config.md)
- [Architecture overview](../Architecture/ARCHITECTURE.md)
