# ms-agent × Hermes Agent Integration

This directory contains everything needed to use ms-agent's 30 MCP capabilities from within [Hermes Agent](https://github.com/NousResearch/hermes-agent).

> **Python environment setup, capability-specific dependencies, API keys, troubleshooting, and test prompts** are covered in the shared [setup.md](../setup.md). Read that first, then come back here for Hermes-specific configuration.

## Prerequisites

1. **Hermes Agent** installed
2. **ms-agent** Python environment ready — see [setup.md](../setup.md)
3. API keys configured in a `.env` file — see [setup.md § Environment & API Keys](../setup.md#environment--api-keys)

## Hermes-Specific Notes

### Python Host — Shared Environment Works Well

Hermes is a Python application. When you run `hermes chat` from an activated virtualenv or conda environment, the child process inherits the same PATH and Python interpreter. This means **Option A (shared environment)** works reliably for Hermes — as long as both Hermes and ms-agent are installed in the same environment.

If you prefer full isolation, use Option B with an absolute path.

## MCP Configuration

Merge the following into `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  ms-agent:
    command: "python3"              # Option A: shared env
    # command: "/absolute/path/to/python"  # Option B: dedicated venv
    args: ["-m", "ms_agent.capabilities.mcp_server"]
    env:
      PYTHONPATH: "/path/to/ms-agent"       # not needed with Option B (pip install -e .)
      MS_AGENT_OUTPUT_DIR: "/path/to/workspace"  # workspace root for file operations
```

Replace paths with your actual ms-agent location.

For Option B (dedicated venv), replace `command` with the absolute path and remove `PYTHONPATH`:

```yaml
mcp_servers:
  ms-agent:
    command: "/absolute/path/to/ms-agent/.venv/bin/python"
    args: ["-m", "ms_agent.capabilities.mcp_server"]
    env:
      MS_AGENT_OUTPUT_DIR: "/path/to/workspace"
```

| Field | Description |
|-------|-------------|
| `command` + `args` | Launches the MCP server via stdio |
| `env.PYTHONPATH` | Ensures ms-agent is importable (not needed with Option B) |
| `env.MS_AGENT_OUTPUT_DIR` | Workspace root for file operations |

### Tool Filtering

Hermes supports per-server tool filtering. To expose only a subset of ms-agent tools:

```yaml
mcp_servers:
  ms-agent:
    command: "/absolute/path/to/python"
    args: ["-m", "ms_agent.capabilities.mcp_server"]
    tools:
      include:
        - web_search
        - replace_file_contents
        - submit_research_task
        - check_research_progress
        - get_research_report
```

### Hermes Tool Naming

Hermes prefixes MCP tools to avoid collisions with built-in tools:

| MCP Tool Name | Hermes Tool Name |
|---------------|-----------------|
| `web_search` | `mcp_ms-agent_web_search` |
| `delegate_task` | `mcp_ms-agent_delegate_task` |
| `submit_research_task` | `mcp_ms-agent_submit_research_task` |
| `replace_file_contents` | `mcp_ms-agent_replace_file_contents` |

## Quick Start

### Step 1: Set up the Python environment

Follow [setup.md](../setup.md) (Option A or B) and verify:

```bash
python3 -m ms_agent.capabilities.mcp_server --check
```

### Step 2: Install the ms-agent skill into Hermes

```bash
./install_skill.sh
```

This copies the `ms-agent-skills/` directory into `~/.hermes/skills/ms-agent/` so Hermes can discover and load it via the progressive disclosure system.

### Step 3: Configure Hermes

Merge the MCP server block (see above) into `~/.hermes/config.yaml`.

> **Important:** Replace `/path/to/ms-agent` with the absolute path to your ms-agent repository root.

### Step 4: Start Hermes

```bash
hermes chat
```

### Step 5: Test it

```bash
# Ask Hermes about available tools
hermes chat -q "What ms-agent MCP tools do you have?"

# Or automated MCP test (no Hermes needed)
python3 test_hermes_mcp.py
python3 test_hermes_mcp.py --list          # List tools only
python3 test_hermes_mcp.py --test ws       # Test web search only
python3 test_hermes_mcp.py --test fs,ws    # Combined tests
```

## How It Works

```
┌──────────────────────────────────────────────────────┐
│  Hermes Agent                                        │
│  ┌──────────────┐    ┌───────────────────────────┐   │
│  │  AgentLoop    │    │  ToolRegistry             │   │
│  │  (run_agent)  │───>│  ├── 47 built-in tools    │   │
│  │               │    │  └── mcp_ms-agent_*  <─┐  │   │
│  └──────────────┘    └─────────────────────┼──┘   │
│                                             │      │
│  ┌──────────────┐                          │      │
│  │  Skills       │                   stdio  │      │
│  │  ~/.hermes/   │                          │      │
│  │  skills/      │── ms-agent/SKILL.md      │      │
│  │               │   + references/          │      │
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

1. **MCP Tools** — Hermes connects to ms-agent's MCP server via stdio. All 30 capabilities appear as tools prefixed `mcp_ms-agent_*`.

2. **Skill Context** — the ms-agent skill is installed into `~/.hermes/skills/ms-agent/`. Hermes loads it via progressive disclosure (Level 0 → Level 1 → Level 2 references) to teach the agent *when* and *how* to use each tool.

## Files

| File | Purpose |
|------|---------|
| `hermes_mcp_config.yaml` | MCP server config to merge into `config.yaml` |
| `install_skill.sh` | Copies ms-agent skill to Hermes skills directory |
| `test_hermes_mcp.py` | Standalone test that exercises MCP tools directly |
