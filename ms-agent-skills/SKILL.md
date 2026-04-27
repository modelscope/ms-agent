---
name: ms-agent
description: >-
  Access ms-agent's advanced AI capabilities via MCP tools: deep research with
  async submit/check/get pattern, web search (arxiv/exa/serpapi), LSP code
  validation (TypeScript/Python/Java), concurrent-safe file editing, and agent
  delegation for complex multi-step tasks. Use when the user asks to research
  a topic, search the web, validate code, edit files precisely, or delegate a
  complex task to a specialized agent. Requires ms-agent (pip install ms-agent).
metadata: {"nanobot":{"emoji":"🤖","requires":{"bins":["python3"],"env":[]}}}
---

# ms-agent Skills

This skill connects you to the **ms-agent Capability Gateway** — a unified
interface to ms-agent's projects, components, and atomic tools, exposed as
MCP tools.

## Setup

Verify ms-agent is installed:

```bash
python scripts/check_ms_agent.py
```

The MCP server must be configured in your agent's config. See below for
nanobot-specific setup.

### nanobot config.json

```json
{
  "tools": {
    "mcpServers": {
      "ms-agent": {
        "command": "python3",
        "args": ["-m", "ms_agent.capabilities.mcp_server"],
        "env": {"MS_AGENT_OUTPUT_DIR": "/path/to/workspace"},
        "toolTimeout": 120,
        "enabledTools": ["*"]
      }
    }
  }
}
```

Once configured, all 14 capabilities below are available as MCP tools
(prefixed `mcp_ms-agent_<tool_name>` in nanobot).

## Capability Index

### Research & Search

| Tool | Type | Duration | Reference |
|------|------|----------|-----------|
| `submit_research_task` | async submit | seconds | [deep-research.md](references/deep-research.md) |
| `check_research_progress` | async poll | seconds | [deep-research.md](references/deep-research.md) |
| `get_research_report` | async result | seconds | [deep-research.md](references/deep-research.md) |
| `deep_research` | sync (blocks) | hours | [deep-research.md](references/deep-research.md) |
| `web_search` | instant | seconds | [web-search.md](references/web-search.md) |

### Agent Delegation

| Tool | Type | Duration | Reference |
|------|------|----------|-----------|
| `delegate_task` | sync (blocks) | minutes | [agent-delegate.md](references/agent-delegate.md) |
| `submit_agent_task` | async submit | seconds | [agent-delegate.md](references/agent-delegate.md) |
| `check_agent_task` | async poll | seconds | [agent-delegate.md](references/agent-delegate.md) |
| `get_agent_result` | async result | seconds | [agent-delegate.md](references/agent-delegate.md) |
| `cancel_agent_task` | async cancel | seconds | [agent-delegate.md](references/agent-delegate.md) |

The `tools` parameter for agent delegation currently supports the basic tool
components `web_search`, `file_system`, and `todo_list` (`filesystem` is kept
as a backward-compatible alias).

### Code Validation

| Tool | Type | Duration | Reference |
|------|------|----------|-----------|
| `lsp_check_directory` | full scan | minutes | [lsp-code-server.md](references/lsp-code-server.md) |
| `lsp_update_and_check` | incremental | seconds | [lsp-code-server.md](references/lsp-code-server.md) |

### File Editing

| Tool | Type | Duration | Reference |
|------|------|----------|-----------|
| `replace_file_contents` | content-match | seconds | [filesystem-tools.md](references/filesystem-tools.md) |
| `replace_file_lines` | line-range | seconds | [filesystem-tools.md](references/filesystem-tools.md) |

## Quick Decision Guide

```
User wants to...
│
├── Research a topic in depth (20-60 min)
│   └── submit_research_task → check_research_progress → get_research_report
│
├── Search the web for quick info
│   └── web_search(query="...", engine_type="arxiv|exa|serpapi")
│
├── Delegate a complex multi-step task to an AI agent
│   ├── Short task (< 3 min) → delegate_task(query="...")
│   └── Long task → submit_agent_task → check_agent_task → get_agent_result
│
├── Validate code for errors
│   ├── Full project → lsp_check_directory(directory="src/", language="typescript")
│   └── Single file → lsp_update_and_check(file_path="...", content="...", language="...")
│
└── Edit a file precisely
    ├── Know exact text → replace_file_contents (concurrent-safe)
    └── Know line numbers → replace_file_lines
```

## Async Pattern

Several capabilities (deep research, agent delegation) support an async
submit/check/get pattern. This does NOT block the agent — continue handling
other messages while the task runs in the background.

```
1. submit_*_task(...)      → returns task_id immediately
2. check_*_task(task_id)   → poll status (repeat every few minutes)
3. get_*_result/report(task_id)   → retrieve final result when completed
4. cancel_*_task(task_id)  → cancel if no longer needed
```

Read the reference files for detailed SOP workflows for each capability.
