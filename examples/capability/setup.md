# ms-agent MCP Server — Python Environment Setup

This document covers the shared setup steps for running the ms-agent MCP server with **any** MCP-compatible host (OpenClaw, Hermes, nanobot, Cursor, Claude Desktop, etc.). Each host's integration README links here for the common parts and adds host-specific configuration on top.

## How the MCP Server Runs

The MCP server (`python -m ms_agent.capabilities.mcp_server`) runs as a **child process** spawned by the host agent. The Python interpreter used is determined by the `command` field in the MCP config — **not** by the shell or environment you use to start the host.

This means:

- The host calls `spawn(command, args)` to start the MCP server.
- `command` is resolved via the child process's PATH, which may differ from your interactive shell.
- **Non-Python hosts** (e.g. OpenClaw/Node.js) are especially prone to resolving `python3` to a different interpreter than expected — see [Option A caveats](#option-a-caveats) below.

## Option A: Shared Environment (simpler)

Install ms-agent into the same Python environment you already use:

```bash
cd /path/to/ms-agent
pip install -e .

# Verify
python3 -m ms_agent.capabilities.mcp_server --check
```

Then set `"command": "python3"` in your MCP config.

### Option A Caveats

Using a bare `python3` means the MCP subprocess gets whichever interpreter the host process finds on PATH. This works reliably when:

- The host is a **Python** program (e.g. Hermes, nanobot) launched from the same virtualenv/conda environment where ms-agent is installed — the child inherits the same PATH.
- You always activate the correct environment before starting the host.

It is **unreliable** when:

- The host is a **non-Python** program (e.g. OpenClaw is Node.js). Even if you activate conda before running `node openclaw.mjs ...`, the Node.js child process may resolve `python3` to a system Python with different (or missing) dependencies.
- You have multiple Python installations (system Python, Homebrew, conda, pyenv). The child may pick a different one than you expect.

> **Recommendation for non-Python hosts:** Use Option B, or at minimum use an absolute path to your conda/venv interpreter in `command` instead of bare `python3`. See [Finding the absolute path](#finding-the-absolute-path) below.

## Option B: Dedicated venv (recommended)

Create an independent virtualenv for ms-agent. This approach is environment-agnostic — the MCP server works regardless of how or where the host is started.

```bash
cd /path/to/ms-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e '.[all]'

# Verify
python3 -m ms_agent.capabilities.mcp_server --check
deactivate
```

Then set `command` to the **absolute path** of the venv interpreter:

```
/absolute/path/to/ms-agent/.venv/bin/python
```

With this option:

- No `PYTHONPATH` needed — `pip install -e .` registered ms-agent into the venv's site-packages.
- No PATH ambiguity — the absolute path bypasses all resolution.
- Works with any host (Python, Node.js, or otherwise).

### Finding the Absolute Path

If you already have a working environment and just need the absolute path for your config:

```bash
# For a venv / virtualenv
source /path/to/ms-agent/.venv/bin/activate
which python3
# → /path/to/ms-agent/.venv/bin/python3

# For conda
conda activate my_env
which python3
# → /opt/homebrew/anaconda3/envs/my_env/bin/python3

# Generic: print the current interpreter's path from within Python
python3 -c "import sys; print(sys.executable)"
```

Copy the output and use it as the `command` value in your MCP config.

## Capability-Specific Dependencies

ms-agent registers all 30 capabilities by default, but different capabilities depend on different Python packages. The base install (`pip install -e .`) covers the framework dependencies (`requirements/framework.txt`). Install extras based on which capabilities you need:


| Capability                                              | Install command                | Requirements file            |
| ------------------------------------------------------- | ------------------------------ | ---------------------------- |
| Core (agent chat, file editing, web search, delegation) | `pip install -e .`             | `requirements/framework.txt` |
| Deep Research / Doc Research / Financial Research       | `pip install -e '.[research]'` | `requirements/research.txt`  |
| Code Genesis                                            | `pip install -e '.[code]'`     | `requirements/code.txt`      |
| All capabilities                                        | `pip install -e '.[all]'`      | all of the above             |


> **Important:** Some dependencies have strict version constraints (e.g. `docling<=2.38.1`). Always install via `pip install -e '.[research]'` rather than `pip install docling` to respect the pinned versions in `setup.py`. Installing an incompatible version (e.g. docling 2.84.0) will cause `ModuleNotFoundError` at runtime due to API changes in the library.

> **Tip:** If you encounter `ModuleNotFoundError` or import errors when calling a specific tool, install the missing extras and restart the host agent. The MCP server will reload with the new dependencies available.

## Environment & API Keys

Create a `.env` file in the ms-agent project root:

```bash
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MODELSCOPE_API_KEY=xxx
EXA_API_KEY=xxx        # optional, for exa web search
SERPAPI_API_KEY=xxx    # optional, for serpapi web search
```

### How `.env` Loading Works

The MCP server loads environment variables from `.env` files on startup (see `_load_env()` in `mcp_server.py`). All loads use `override=False` — a variable that is already set in the process environment is **never** overwritten by a `.env` file.

The loading chain (in order):

1. **Host MCP config `env` block** — values set here become process environment variables *before* the server starts. They always win.
2. **`--env-file` (if provided)** — if you pass `--env-file /path/to/.env`, this file is loaded. Skips step 3a.
3. **Automatic `.env` discovery (if `--env-file` is not provided):**
  - **3a. CWD walk-up** — `find_dotenv(usecwd=True)` walks up from the current working directory to find the nearest `.env`. This may be the host agent's own `.env` (e.g. Hermes's project directory).
  - **3b. ms-agent package root** — always loads `<ms-agent-root>/.env` (three directories up from `mcp_server.py`). This is the recommended location for ms-agent-specific keys.

Since all loads are `override=False`, the **effective priority** (highest to lowest) is:

1. Host MCP config `env` block (or shell `export`)
2. CWD `.env` (or `--env-file`)
3. ms-agent project root `.env`

> **Why two `.env` files?** The host agent (Hermes, OpenClaw, etc.) may set CWD to its own project directory, which may contain a `.env` with host-specific keys but not ms-agent-specific ones like `MODELSCOPE_API_KEY`. Loading both ensures ms-agent always finds its own keys.

**Explicit path:** If your `.env` is not in an ancestor directory of CWD, pass it explicitly:

```
"args": ["-m", "ms_agent.capabilities.mcp_server", "--env-file", "/path/to/.env"]
```

### Variable Reference


| Variable              | Required by                                      | Notes                                                |
| --------------------- | ------------------------------------------------ | ---------------------------------------------------- |
| `OPENAI_API_KEY`      | deep_research, delegate_task, code_genesis, etc. | Any OpenAI-compatible provider                       |
| `OPENAI_BASE_URL`     | deep_research, delegate_task                     | DashScope, OpenAI, or other compatible endpoint      |
| `MODELSCOPE_API_KEY`  | delegate_task, agent_task                        | For ModelScope API inference                         |
| `EXA_API_KEY`         | web_search (exa engine)                          | Only needed for `engine_type='exa'`                  |
| `SERPAPI_API_KEY`     | web_search (serpapi engine)                      | Only needed for `engine_type='serpapi'`              |
| `MS_AGENT_OUTPUT_DIR` | replace_file_*, lsp_check_*                      | Workspace root for file operations (defaults to cwd) |


## Test Prompts

These prompts work with any host agent once the MCP server is connected:


| Category                   | Duration  | Prompt                                                                                                                |
| -------------------------- | --------- | --------------------------------------------------------------------------------------------------------------------- |
| File Editing               | instant   | Create a file called test_demo.py with a hello world function, then use replace_file_contents to rename the function. |
| Web Search                 | instant   | Search arxiv for recent papers on LLM agent frameworks.                                                               |
| LSP Validation             | 1-5 min   | Check the code in /path/to/project for TypeScript errors using LSP.                                                   |
| Agent Delegation (sync)    | minutes   | Use delegate_task to research the top 3 Python async frameworks.                                                      |
| Deep Research (async)      | 20-60 min | Research "the current state of AI agent frameworks in 2026" — submit as a background task and tell me when it's done. |
| Code Generation (async)    | 10-30 min | Generate a todo app with React frontend, Express backend, and SQLite.                                                 |
| Financial Research (async) | 20-60 min | Analyze CATL (300750.SZ) over the past four quarters.                                                                 |
| Document Research (async)  | 1-20 min  | Analyze this paper: [https://arxiv.org/pdf/2504.17432](https://arxiv.org/pdf/2504.17432)                              |
| Video Generation (async)   | ~20 min   | Create a short educational video about GDP economics.                                                                 |


## Troubleshooting


| Symptom                                                   | Likely cause                                     | Fix                                                                                          |
| --------------------------------------------------------- | ------------------------------------------------ | -------------------------------------------------------------------------------------------- |
| `ModuleNotFoundError: No module named 'ms_agent'`         | ms-agent not installed in the Python used by MCP | Install ms-agent in the correct env (see Option A/B)                                         |
| `ModuleNotFoundError: No module named 'mcp'`              | `mcp` package missing                            | `pip install mcp` in the same env                                                            |
| `ModuleNotFoundError` for `docling`, `exa_py`, etc.       | Missing capability-specific dependencies         | `pip install -e '.[research]'` or `'.[all]'`                                                 |
| MCP server starts but a tool call fails with import error | The tool's extra dependencies are not installed  | Install the missing extras, then restart the host                                            |
| `python3` resolves to wrong interpreter                   | Shared env (Option A) picked up wrong Python     | Use absolute path (Option B) or verify with `python3 -c "import sys; print(sys.executable)"` |
| docling `ModuleNotFoundError` despite being installed     | docling version too new (API changed in 2.39+)   | `pip install 'docling<=2.38.1'` or reinstall via `pip install -e '.[research]'`              |
| Tool name collision (e.g. `web_search` skipped)           | Host has a built-in tool with the same name      | Rename or disable the conflicting built-in tool in the host config                           |
