# ms-agent × OpenClaw Integration

This directory contains everything needed to use ms-agent's 30 MCP capabilities from within [OpenClaw](https://github.com/openclaw/openclaw).

> **Python environment setup, capability-specific dependencies, API keys, troubleshooting, and test prompts** are covered in the shared [setup.md](../setup.md). Read that first, then come back here for OpenClaw-specific configuration.

## Prerequisites

1. **OpenClaw** installed
2. **ms-agent** Python environment ready — see [setup.md](../setup.md)
3. API keys configured in a `.env` file — see [setup.md § Environment & API Keys](../setup.md#environment--api-keys)

## OpenClaw-Specific Notes

### Node.js ≠ Python: `command` Resolution

OpenClaw is a **Node.js** application. When it spawns the MCP server subprocess, it resolves `command` via its own process PATH — which may differ from the conda/venv you activated in your terminal. Even if you run `conda activate my_env && openclaw gateway run`, the child process can still pick up a system `python3` instead of the conda one.

**Recommended:** Always use an **absolute path** to your Python interpreter in the OpenClaw MCP config. See [setup.md § Finding the Absolute Path](../setup.md#finding-the-absolute-path) for how to determine the correct path.

## MCP Configuration

Merge the following into your `~/.openclaw/openclaw.json`:

```json
{
  "mcp": {
    "servers": {
      "ms-agent": {
        "command": "/absolute/path/to/python",
        "args": ["-m", "ms_agent.capabilities.mcp_server"],
        "env": {
          "PYTHONPATH": "/path/to/ms-agent",
          "MS_AGENT_OUTPUT_DIR": "/path/to/workspace"
        }
      }
    }
  }
}
```

Replace `/absolute/path/to/python` with the output of `which python3` inside your ms-agent environment (or `python3 -c "import sys; print(sys.executable)"`).

If you installed ms-agent via `pip install -e .`, you can remove `PYTHONPATH`:

```json
{
  "mcp": {
    "servers": {
      "ms-agent": {
        "command": "/absolute/path/to/python",
        "args": ["-m", "ms_agent.capabilities.mcp_server"],
        "env": {
          "MS_AGENT_OUTPUT_DIR": "/path/to/workspace"
        }
      }
    }
  }
}
```

| Field | Description |
|-------|-------------|
| `command` + `args` | Launches the MCP server via stdio |
| `env.PYTHONPATH` | Ensures ms-agent is importable (not needed with `pip install -e .`) |
| `env.MS_AGENT_OUTPUT_DIR` | Workspace root for file operations |

> **Tool name collision:** OpenClaw has a built-in `web_search` tool. The ms-agent `web_search` will be skipped at startup. If you prefer to use ms-agent's version, disable OpenClaw's built-in web search in its config.

## Quick Start

### Step 1: Set up the Python environment

Follow [setup.md](../setup.md) (Option A or B) and verify:

```bash
python3 -m ms_agent.capabilities.mcp_server --check
```

### Step 2: Install the ms-agent skill into OpenClaw's workspace

```bash
./install_skill.sh
```

This copies the `ms-agent-skills/` directory into OpenClaw's workspace skills directory so the agent can reference it.

### Step 3: Configure OpenClaw

Merge the MCP server block (see above) into `~/.openclaw/openclaw.json`.

> **Important:** Replace placeholder paths with absolute paths to your ms-agent repository and Python interpreter.

### Step 4: Restart the Gateway

```bash
openclaw gateway start
```

### Step 5: Test it

```bash
# Interactive mode
openclaw agent --agent main --message "List your MCP tools"

# Or automated MCP test (no OpenClaw needed)
python3 test_openclaw_mcp.py
python3 test_openclaw_mcp.py --list          # List tools only
python3 test_openclaw_mcp.py --test ws       # Test web search only
python3 test_openclaw_mcp.py --test fs,ws    # Combined tests
```

## How It Works

```
┌──────────────────────────────────────────────────────┐
│  OpenClaw                                            │
│  ┌──────────────┐    ┌───────────────────────────┐   │
│  │  AgentLoop    │    │  ToolRegistry             │   │
│  │  (gateway)    │───>│  ├── native tools         │   │
│  │               │    │  └── mcp: ms-agent  <──┐  │   │
│  └──────────────┘    └─────────────────────┼──┘   │
│                                             │      │
│  ┌──────────────┐                          │      │
│  │  Workspace    │                   stdio  │      │
│  │  ├── AGENTS.md│                          │      │
│  │  └── skills/  │── ms-agent SKILL.md      │      │
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

1. **MCP Tools** — OpenClaw connects to ms-agent's MCP server via stdio. All 30 capabilities appear as tools. The agent can call them directly.

2. **Skill Context** — the ms-agent skill is installed into OpenClaw's workspace. It teaches the agent *when* and *how* to use each tool, including the async submit/check/get pattern for long-running tasks.

## Files

| File | Purpose |
|------|---------|
| `openclaw_mcp_config.json` | MCP server config to merge into `openclaw.json` |
| `install_skill.sh` | Copies ms-agent skill to OpenClaw workspace |
| `test_openclaw_mcp.py` | Standalone test that exercises MCP tools directly |
