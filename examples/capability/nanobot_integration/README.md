# ms-agent × nanobot Integration

This directory contains everything needed to use ms-agent's 30 MCP capabilities from within nanobot.

> **Python environment setup, capability-specific dependencies, API keys, troubleshooting, and test prompts** are covered in the shared [setup.md](../setup.md). Read that first, then come back here for nanobot-specific configuration.

## Prerequisites

1. **nanobot** installed (`pip install nanobot` or dev install)
2. **ms-agent** Python environment ready — see [setup.md](../setup.md)
3. API keys configured in a `.env` file — see [setup.md § Environment & API Keys](../setup.md#environment--api-keys)

## nanobot-Specific Notes

### Python Host — Shared Environment Works Well

nanobot is a Python application. When you launch it from an activated virtualenv or conda environment, the child process inherits the same PATH and Python interpreter. This means **Option A (shared environment)** works reliably for nanobot — as long as both nanobot and ms-agent are installed in the same environment.

If you prefer full isolation, use Option B with an absolute path.

## MCP Configuration

Merge the following into your nanobot `config.json`:

```json
{
  "tools": {
    "mcpServers": {
      "ms-agent": {
        "command": "python3",
        "args": ["-m", "ms_agent.capabilities.mcp_server"],
        "env": {
          "PYTHONPATH": "/path/to/ms-agent",
          "MS_AGENT_OUTPUT_DIR": "/path/to/workspace"
        },
        "toolTimeout": 600,
        "enabledTools": ["*"]
      }
    }
  }
}
```

Replace paths with your actual ms-agent location.

For Option B (dedicated venv), replace `"command"` with the absolute path and remove `PYTHONPATH`:

```json
{
  "tools": {
    "mcpServers": {
      "ms-agent": {
        "command": "/absolute/path/to/ms-agent/.venv/bin/python",
        "args": ["-m", "ms_agent.capabilities.mcp_server"],
        "env": {
          "MS_AGENT_OUTPUT_DIR": "/path/to/workspace"
        },
        "toolTimeout": 600,
        "enabledTools": ["*"]
      }
    }
  }
}
```

| Field | Description |
|-------|-------------|
| `command` + `args` | Launches the MCP server via stdio |
| `env.PYTHONPATH` | Ensures ms-agent is importable (not needed with Option B) |
| `env.MS_AGENT_OUTPUT_DIR` | Workspace root for file operations |
| `toolTimeout` | Seconds before tool call times out (600s recommended for async tasks) |
| `enabledTools` | `["*"]` for all tools, or list specific ones |

### nanobot Tool Naming

nanobot prefixes MCP tools to avoid collisions with built-in tools:

| MCP Tool Name | nanobot Tool Name |
|---------------|-----------------|
| `web_search` | `mcp_ms-agent_web_search` |
| `delegate_task` | `mcp_ms-agent_delegate_task` |
| `submit_research_task` | `mcp_ms-agent_submit_research_task` |
| `replace_file_contents` | `mcp_ms-agent_replace_file_contents` |

### Selective Tool Enablement

If you only need specific capabilities:

```json
{
  "enabledTools": [
    "web_search",
    "replace_file_contents",
    "replace_file_lines",
    "submit_research_task",
    "check_research_progress",
    "get_research_report"
  ]
}
```

## Quick Start

### Step 1: Set up the Python environment

Follow [setup.md](../setup.md) (Option A or B) and verify:

```bash
python3 -m ms_agent.capabilities.mcp_server --check
```

### Step 2: Install the ms-agent skill into nanobot's workspace

```bash
./install_skill.sh
```

This copies the `ms-agent-skills/` directory into nanobot's workspace skills directory so that nanobot's context builder can load it.

### Step 3: Configure nanobot

Merge the MCP server block (see above) into `~/.nanobot/config.json`.

> **Important:** Replace `/path/to/ms-agent` with the absolute path to your ms-agent repository root.

### Step 4: Start nanobot

```bash
nanobot agent
```

### Step 5: Test it

```bash
# Ask nanobot about available tools
nanobot agent -q "What ms-agent MCP tools do you have?"

# Or automated MCP test (no nanobot needed)
python3 test_mcp_tools.py
python3 test_mcp_tools.py --list          # List tools only
python3 test_mcp_tools.py --test ws       # Test web search only
python3 test_mcp_tools.py --test fs,ws    # Combined tests
```

## How It Works

```
┌──────────────────────────────────────────────────────┐
│  nanobot                                              │
│  ┌──────────────┐    ┌───────────────────────────┐   │
│  │  AgentLoop    │    │  ToolRegistry             │   │
│  │  (ReAct)      │───>│  ├── read_file, exec, ... │   │
│  │               │    │  └── mcp_ms-agent_*  <─┐  │   │
│  └──────────────┘    └─────────────────────┼──┘   │
│                                             │      │
│  ┌──────────────┐                          │      │
│  │  ContextBuilder│                   stdio  │      │
│  │  ├── SOUL.md  │                          │      │
│  │  ├── Skills   │── ms-agent/SKILL.md      │      │
│  │  └── Memory   │                          │      │
│  └──────────────┘                          │      │
└─────────────────────────────────────────────┼──────┘
                                              │
                                              ▼
┌──────────────────────────────────────────────────────┐
│  ms-agent MCP Server                                 │
│  (python -m ms_agent.capabilities.mcp_server)        │
│  ┌──────────────────────────────────────────────┐    │
│  │  CapabilityRegistry (30 tools)               │    │
│  │  ├── web_search          (arxiv/exa/serpapi)  │    │
│  │  ├── delegate_task       (sync agent)         │    │
│  │  ├── submit/check/get_*  (async research)     │    │
│  │  ├── code_genesis        (code generation)    │    │
│  │  ├── lsp_check_directory (code validation)    │    │
│  │  ├── replace_file_*      (file editing)       │    │
│  │  └── ...                                      │    │
│  └──────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────┘
```

### Two Integration Layers

1. **MCP Tools** — nanobot connects to ms-agent's MCP server via stdio. All 30 capabilities appear as tools prefixed `mcp_ms-agent_*`.

2. **Skill Context** — the ms-agent skill is installed into nanobot's workspace. It teaches the agent *when* and *how* to use each tool, including the async submit/check/get pattern for long-running tasks.

## Files

| File | Purpose |
|------|---------|
| `config.json` | MCP server config to merge into nanobot's `config.json` |
| `install_skill.sh` | Copies ms-agent skill to nanobot workspace |
| `test_mcp_tools.py` | Standalone test that exercises MCP tools directly |
