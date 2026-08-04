# MS-Agent WebUI

[中文说明](./README_ZH.md)

This directory contains the source-checkout WebUI for MS-Agent:

- `frontend/`: React Router 8 with server-side rendering, React 19, Vite, and
  Ant Design.
- `backend/`: FastAPI, the MS-Agent SDK adapter, and SSE chat streaming.

The supported launcher is intended for a local developer workspace. One
`ms-agent ui` command supervises two child services:

```text
http://127.0.0.1:7860       React Router development server
          /api/*  ────────> FastAPI on http://127.0.0.1:8000
```

This is not a production deployment or a standalone wheel installation. The
command needs an MS-Agent source checkout containing this `webui/` directory,
and the frontend is served by its development server.

### Not carried over from the previous WebUI

This interface replaced an earlier Vite/MUI one. It is a general agent
workspace and deliberately does **not** reproduce that version's dedicated
**Deep Research** view (the `deep_research_worker` / `DeepResearchView`
pipeline). Run Agentic Insight v2 from the CLI instead — see
[`projects/deep_research/v2`](../projects/deep_research/v2/README.md).

### Runtime constraints

- The chat runtime, event buffers, turn locks, and permission futures all live
  in process memory, so the backend **must stay single-worker**. Adding uvicorn
  workers silently breaks stop/interrupt, re-attach, and authorization prompts.
- Chat streams over SSE; there is no WebSocket anywhere in the stack.
- `--host` accepts any interface, and the stack has **no authentication**. On a
  non-loopback host, anyone who can reach the port gets the agent — including
  its shell tool.

## Prerequisites

| Tool | Required version | Purpose |
| --- | --- | --- |
| Python | 3.12 or newer | WebUI backend; `uv` creates its isolated environment |
| [uv](https://docs.astral.sh/uv/) | Recent version | Synchronizes `webui/backend/.venv` |
| [Node.js](https://nodejs.org/) | **22.22.0 or newer** | Required by React Router 8 |
| [pnpm](https://pnpm.io/installation) | **10.x** | Synchronizes frontend dependencies; the project pins 10.17.1 |

With `--skip-install` only Node.js is required — the launcher never resolves
`uv` or `pnpm` in that mode.

### Installing the tools without Corepack

Corepack is no longer bundled with Node.js 25+, and inside a conda environment
"installed" is not the same as "resolved" — PATH may still find an older global
copy. The launcher prints the executable path it resolved whenever a version
check fails; to install both tools into the ACTIVE environment:

```bash
pip install uv                                        # uv into this env's bin/
npm install --global --prefix "$CONDA_PREFIX" pnpm@10.17.1
hash -r                                               # rehash, then verify:
command -v uv pnpm                                    # both under $CONDA_PREFIX/bin
```

On Node.js < 25, `corepack enable && corepack prepare pnpm@10.17.1 --activate`
still works as an alternative for pnpm.

The WebUI's Python 3.12 does not need to be the currently activated Python;
uv selects a compatible interpreter and can download one when necessary.

Check the tools before starting:

```bash
python --version
uv --version
node --version
pnpm --version
```

If Corepack is available, the pinned pnpm release can be activated with:

```bash
corepack enable
corepack prepare pnpm@10.17.1 --activate
```

## Quick start

Run these commands from the MS-Agent repository root:

```bash
pip install -e .
ms-agent ui
```

On the first launch, the command automatically runs the equivalent of:

```bash
cd webui/backend && uv sync --locked --no-dev --inexact
cd webui/frontend && pnpm install --frozen-lockfile
```

Later launches recheck both environments against their lockfiles. No global
Python or Node packages are installed by this synchronization. After both
services report ready, the browser opens at <http://127.0.0.1:7860>.

To verify the interface without a model credential, use the in-memory backend:

```bash
ms-agent ui --mock
```

On Windows, use the PowerShell wrapper (it forces UTF-8 console output before
delegating to the same command):

```powershell
py -m pip install -e .
.\webui\scripts\start-webui.ps1
```

Press `Ctrl+C` in the launcher terminal to stop both services.

## Configure a model

Environment variables are not required to open the WebUI. The simplest setup
for real chat is through the browser:

1. Start `ms-agent ui`.
2. Open **Settings → Models**.
3. Select a built-in provider, or add a compatible custom provider.
4. Configure its API key and base URL if required.
5. Add a model to that provider.
6. Select the default provider and model.

The settings are shared with the normal MS-Agent CLI/TUI under
`~/.ms_agent` unless `MS_AGENT_HOME` is explicitly changed. Provider
credentials stored through the UI are written to `settings.json` in that
directory in plaintext; do not publish or commit that file.

## Configuration files and environment variables

The backend reads dotenv files from broadest to most specific:

```text
<repository>/.env
<repository>/webui/.env
<repository>/webui/backend/.env
```

The effective precedence is:

```text
process environment / launcher injection
    > webui/backend/.env
    > webui/.env
    > repository .env
```

Real process environment variables are never overwritten by dotenv files.
This also makes arbitrary variables available to MCP `${NAME}` placeholders.
All `.env` files are ignored by Git.

For an advanced or scripted setup, copy the template:

```bash
cp webui/backend/.env.example webui/backend/.env
```

PowerShell equivalent:

```powershell
Copy-Item .\webui\backend\.env.example .\webui\backend\.env
```

### Model bootstrap variables

These are optional alternatives to configuring the model in the browser:

| Variable | Meaning |
| --- | --- |
| `MS_AGENT_LLM_MODEL` | Model ID to seed. **Bootstrap does nothing at all unless this is set** — the other three are ignored without it. |
| `MS_AGENT_LLM_PROVIDER` | MS-Agent provider ID to seed (default `openai`). Must actually serve the model above: `qwen*` is DashScope/ModelScope, not OpenAI. |
| `OPENAI_API_KEY` | Credential, applied **only** when the provider is `openai`. Other providers resolve their own variable (`DASHSCOPE_API_KEY`, `DEEPSEEK_API_KEY`, …). |
| `OPENAI_BASE_URL` | Base URL, same `openai`-only rule. |

Bootstrap only fills a missing `llm` block. If
`~/.ms_agent/settings.json` (or the selected `MS_AGENT_HOME`) already contains
`llm`, changing these variables does **not** replace it. Update the provider or
model in **Settings → Models** instead.

### Optional runtime variables

| Variable | Meaning |
| --- | --- |
| `MS_AGENT_HOME` | Override the SDK data directory; default is `~/.ms_agent` |
| `EXA_API_KEY` | Optional credential for Exa-backed web search |
| Any `${NAME}` variable | Expanded at runtime in MCP configuration |

### Launcher-managed variables

Normal `ms-agent ui` users should not set these manually:

| Variable | How it is managed |
| --- | --- |
| `HOST`, `PORT` | Internal FastAPI address, derived from launcher options |
| `AGENT_BACKEND` | `ms_agent` by default; `mock` when `--mock` is used |
| `API_BASE_URL` | Injected into the React Router process |
| `CORS_ORIGINS` | Only normally relevant when starting the services manually |

## Command-line options

| Option | Default | Description |
| --- | --- | --- |
| `--host HOST` | `127.0.0.1` | Frontend listen address |
| `--port PORT` | `7860` | Frontend port and browser URL |
| `--backend-port PORT` | `8000` | Internal FastAPI port |
| `--reload` | off | Reload the Python backend after source changes; frontend HMR is always active |
| `--mock` | off | Use in-memory demonstration data without model credentials |
| `--skip-install` | off | Skip both dependency synchronization commands; fails if either local environment is missing. With it, only Node.js needs to be on `PATH` — `uv` and `pnpm` are not resolved at all. |
| `--no-browser` | off | Do not open a browser automatically |
| `--production` | unsupported | Reserved option that exits with an explanatory error |

Examples:

```bash
# Use different ports
ms-agent ui --port 8080 --backend-port 8001

# UI development with mock data
ms-agent ui --mock --reload

# Start without opening a browser
ms-agent ui --no-browser

# Deliberately expose the frontend to the local network
ms-agent ui --host 0.0.0.0
```

The backend remains bound to `127.0.0.1`; browser API traffic goes through the
frontend proxy. Exposing the development server is not a production deployment
and does not add authentication or production hardening.

## Start the two services manually

Manual mode is useful when debugging the frontend and backend in separate
terminals. It is not needed for normal use.

### 1. Backend

For the real MS-Agent backend, first create `webui/backend/.env` and set
`AGENT_BACKEND=ms_agent`. Without that setting, a manually started backend uses
mock data by default.

```bash
cd webui/backend
uv sync --locked
uv run --frozen dev
```

The backend listens on <http://127.0.0.1:8000>; its health endpoint is
<http://127.0.0.1:8000/api/health>. The backend dependency points to the
containing MS-Agent checkout as an editable package.

### 2. Frontend

In another terminal:

```bash
cd webui/frontend
pnpm install --frozen-lockfile
pnpm dev
```

Open <http://localhost:5173>. The Vite development server proxies `/api/*` to
`http://127.0.0.1:8000`, which is also the default endpoint used by SSR route
loaders. To use another backend port, set `API_BASE_URL` for the frontend
process before starting it.

## Tests

The backend suite lives in `webui/backend/tests` and runs inside the backend's
own environment. Note that the launcher syncs that environment **without** the
dev group, so install it once before testing:

```bash
cd webui/backend
uv sync --locked            # includes the dev group (pytest)
./.venv/bin/python -m pytest
```

The launcher/contract suites live with the repository's tests and run with any
Python that has the SDK installed:

```bash
python -m pytest tests/cli/test_ui.py tests/ui
```

The frontend has no automated tests yet; `pnpm typecheck` is the gate, and
manual Chrome walkthroughs are the UI regression instrument.

The repository CI (`pytest tests`) does **not** include `webui/backend/tests` —
its dependencies (FastAPI and friends) are not installed there. Run it locally
as above when touching the backend or the SDK surfaces it consumes.

## Windows

PowerShell is recommended. From the repository root, use the included UTF-8
wrapper:

```powershell
.\webui\scripts\start-webui.ps1
```

All launcher arguments are forwarded:

```powershell
.\webui\scripts\start-webui.ps1 --mock --no-browser
```

The wrapper switches the current console to UTF-8 and sets `PYTHONUTF8` and
`PYTHONIOENCODING`, preserving the fix introduced after Windows users reported
garbled output.

If the local PowerShell execution policy blocks the script, allow it for the
current process only:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\webui\scripts\start-webui.ps1
```

This does not change the machine-wide or user-wide policy. The launcher uses a
Windows process group and stops descendant Python/Node processes when you press
`Ctrl+C`. The built-in terminal uses the native Windows command processor and
does not require a separate POSIX `sh`. Repository paths containing spaces and
non-ASCII characters are supported; keep the repository on a local filesystem
for the best file-watcher behavior.

Useful Windows checks:

```powershell
Get-Command ms-agent, uv, node, pnpm
node --version
pnpm --version
```

## Troubleshooting

### A required command was not found

Install the missing tool, reopen the terminal so `PATH` is refreshed, and run
the version checks above. The launcher rejects Node older than 22.22.0 and pnpm
outside the 10.x series before installing dependencies.

### Dependency synchronization failed

The first launch downloads both Python and Node dependencies and can take a
while. Check registry/network access, then run `ms-agent ui` again. To see the
failing operation independently, run the two synchronization commands shown in
the manual-start section. `--skip-install` is only appropriate after both
`webui/backend/.venv` and `webui/frontend/node_modules` already exist.

### A port is already in use

The launcher checks both ports before it touches any dependency, so this fails
fast and names the port. Two rules it enforces:

- `--port` and `--backend-port` must differ.
- The frontend uses `--strictPort`, so a busy frontend port is a hard failure —
  it never silently moves to the next one.

Select both ports explicitly:

```bash
ms-agent ui --port 8080 --backend-port 8001
```

On Windows, inspect the defaults with:

```powershell
Get-NetTCPConnection -LocalPort 7860,8000 -ErrorAction SilentlyContinue
```

### The page opens but API requests fail

Open <http://127.0.0.1:8000/api/health>, or the corresponding custom backend
port. If the health request fails, inspect the backend error in the launcher
terminal. In manual mode, confirm that the frontend's `API_BASE_URL` matches the
backend port.

### Chat reports a provider, model, or authentication error

Return to **Settings → Models** and verify all three items: provider credential,
model entry, and selected default model. If environment changes appear to be
ignored, an existing `settings.json.llm` is taking precedence by design.

### The browser did not open

Open the printed frontend URL manually. Browser launch failure does not stop
the services; `--no-browser` disables the attempt intentionally.

### Windows output is garbled

Stop the launcher and use `webui\scripts\start-webui.ps1` from PowerShell. The
plain `ms-agent ui` command still works, but it cannot retroactively change the
encoding of a parent console that was opened with a legacy code page.

### `--production` exits immediately

This is expected. The current one-command mode deliberately runs the React
Router development server and FastAPI for a local source checkout. Production
SSR deployment, static packaging, wheels, and container images are outside this
launcher.
