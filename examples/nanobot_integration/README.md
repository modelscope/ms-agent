# ms-agent × nanobot Integration

This directory contains everything needed to use ms-agent's 30 MCP capabilities
from within nanobot.

## Prerequisites

1. **ms-agent** installed (or available on `PYTHONPATH`)
2. **nanobot** installed (`pip install nanobot` or dev install)
3. **mcp** package installed (`pip install mcp`)
4. API keys configured in a `.env` file (see [Environment & API Keys](#environment--api-keys))

## Quick Start

### Step 1: Verify ms-agent capabilities

```bash
cd /path/to/ms-agent
python3 -m ms_agent.capabilities.mcp_server --check
```

Expected output: JSON listing all 30 capabilities.

### Step 2: Install the ms-agent skill into nanobot's workspace

```bash
./install_skill.sh
```

This copies the `ms-agent-skills/` directory into nanobot's workspace skills
directory so that nanobot's context builder can load it.

### Step 3: Configure nanobot

```bash
# Option A: Use this demo config directly
nanobot agent -c examples/nanobot_integration/config.json

# Option B: Merge into your existing ~/.nanobot/config.json
# Add the mcpServers block from config.json
```

### Step 4: Test it

```bash
# Interactive mode
nanobot agent -c examples/nanobot_integration/config.json

# Or automated MCP test (no nanobot needed)
python3 test_mcp_tools.py
python3 test_mcp_tools.py --list          # List tools only
python3 test_mcp_tools.py --test ws       # Test web search only
python3 test_mcp_tools.py --test cg       # Test code genesis only
python3 test_mcp_tools.py --test fr       # Test financial research only
python3 test_mcp_tools.py --test vg       # Test video generation only
python3 test_mcp_tools.py --test docr     # Test document research only
```

## How It Works

```
┌──────────────────────────────────────────────────────────┐
│  nanobot                                                  │
│  ┌──────────────────┐    ┌─────────────────────────────┐ │
│  │  AgentLoop        │    │  ToolRegistry               │ │
│  │  (ReAct pattern)  │───▶│  ├── read_file, exec, ...  │ │
│  │                   │    │  └── mcp_ms-agent_*  ◄──┐  │ │
│  └──────────────────┘    └─────────────────────┼───┘ │
│                                                 │      │
│  ┌──────────────────┐                          │      │
│  │  ContextBuilder   │                          │      │
│  │  ├── SOUL.md      │                   stdio  │      │
│  │  ├── Skills ◄─────┼── ms-agent SKILL.md     │      │
│  │  └── Memory       │                          │      │
│  └──────────────────┘                          │      │
└─────────────────────────────────────────────────┼──────┘
                                                  │
                                                  ▼
┌──────────────────────────────────────────────────────────┐
│  ms-agent MCP Server (python -m ms_agent.capabilities.   │
│                        mcp_server)                        │
│  ┌────────────────────────────────────────────────────┐  │
│  │  CapabilityRegistry (30 tools)                     │  │
│  │  ├── web_search           (arxiv/exa/serpapi)      │  │
│  │  ├── delegate_task        (sync agent)             │  │
│  │  ├── submit/check/get/cancel_agent_task            │  │
│  │  ├── submit/check/get_research_*  (deep research)  │  │
│  │  ├── submit/check/get_doc_research_* (doc)         │  │
│  │  ├── submit/check/get_fin_research_* (finance)     │  │
│  │  ├── submit/check/get_code_genesis_* (codegen)     │  │
│  │  ├── submit/check/get_video_generation_* (video)   │  │
│  │  ├── lsp_check_directory  (code validation)        │  │
│  │  ├── lsp_update_and_check                          │  │
│  │  ├── replace_file_contents (concurrent-safe edit)  │  │
│  │  └── replace_file_lines                            │  │
│  └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

### Two Integration Layers

1. **MCP Tools** — nanobot connects to ms-agent's MCP server via stdio.
   All 30 capabilities appear as tools (prefixed `mcp_ms-agent_<name>`).
   The agent can call them directly during the ReAct loop.

2. **Skill Context** — the `ms-agent-skills/SKILL.md` is installed into
   nanobot's workspace. It teaches the agent *when* and *how* to use each
   MCP tool. The skill includes a decision guide and links to detailed
   reference docs for each capability.

## Test Prompts

### Web Search (instant)

> Search arxiv for recent papers on LLM agent frameworks.

### File Editing (instant)

> Create a file called test_demo.py with a hello world function, then use
> replace_file_contents to rename the function from hello to greet.

### LSP Validation (1-5 min)

> Check the code in /path/to/project for TypeScript errors using LSP.

### Agent Delegation (sync, minutes)

> Use delegate_task to research and compare the top 3 Python async frameworks.

### Deep Research (async, 20-60 min)

> Research "the current state of AI agent frameworks in 2026" — submit it
> as a background task and let me know when it's done.

### Agent Delegation (async)

> Submit an agent task to analyze the architecture of this project and suggest
> improvements. Check on it periodically and show me the results when done.

### Code Generation (10-30 min)

> Generate a todo app with React frontend, Express backend, and SQLite database.
> Use the standard 7-stage workflow.

### Financial Research (20-60 min)

> Analyze CATL (300750.SZ) profitability over the past four quarters and compare
> with BYD and Gotion High-Tech.

### Document Research (1-20 min)

> Analyze and summarize this paper: https://arxiv.org/pdf/2504.17432

### Video Generation (~20 min)

> Create a short educational video about GDP economics, about 3 minutes long.

## Environment & API Keys

The MCP server automatically loads a `.env` file on startup, so all
capabilities (web search, deep research, agent delegation, etc.) and their
subprocesses can access API keys without any extra configuration.

**Setup:** Create a `.env` file in the ms-agent project root:

```bash
# LLM provider
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

# Search engines (optional, only needed if you use exa/serpapi)
EXA_API_KEY=xxx
SERPAPI_API_KEY=xxx
```

**How it works:** The server uses `find_dotenv()` to walk up from the current
directory and find the nearest `.env`.  Variables already set in the process
environment (e.g. via the MCP client `env` block or `export`) are **never**
overwritten, so you can always override `.env` values per-session.

**Priority** (highest → lowest):

1. MCP client `env` block (in `config.json`)
2. Shell `export` / system environment
3. `.env` file

**Explicit path:** If your `.env` is not in an ancestor directory, pass it
explicitly:

```json
{
  "args": ["-m", "ms_agent.capabilities.mcp_server", "--env-file", "/path/to/.env"]
}
```

| Variable | Required by | Notes |
|----------|-------------|-------|
| `OPENAI_API_KEY` | deep_research, delegate_task | Any OpenAI-compatible provider |
| `OPENAI_BASE_URL` | deep_research, delegate_task | Defaults to DashScope if unset in YAML |
| `EXA_API_KEY` | web_search (exa engine) | Only needed for `engine_type='exa'` |
| `SERPAPI_API_KEY` | web_search (serpapi engine) | Only needed for `engine_type='serpapi'` |

## MCP Configuration

The key block in `config.json`:

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
        "toolTimeout": 120,
        "enabledTools": ["*"]
      }
    }
  }
}
```

**Key settings:**

| Field | Description |
|-------|-------------|
| `command` + `args` | Launches the MCP server via stdio |
| `env.PYTHONPATH` | Ensures ms-agent is importable |
| `env.MS_AGENT_OUTPUT_DIR` | Workspace root for file operations |
| `toolTimeout` | Seconds before tool call times out (120s recommended for delegate_task) |
| `enabledTools` | `["*"]` for all tools, or list specific ones |

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

## Files

| File | Purpose |
|------|---------|
| `config.json` | nanobot config with ms-agent MCP server |
| `install_skill.sh` | Copies ms-agent skill to nanobot workspace |
| `test_mcp_tools.py` | Standalone test that exercises MCP tools directly |
