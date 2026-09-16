# MS-Agent WebUI

Use MS-Agent in your browser to research, write code and work with project files.
Conversations, tool activity and generated results stay together so you can
follow a task and continue the conversation. [中文说明](README_ZH.md)

- **Organize work by project:** open a local folder, manage multiple sessions,
  and browse or edit project files.
- **Follow the agent's progress:** stream replies, reasoning, tool calls and
  generated files as the task runs.
- **Choose models and tools:** configure model providers, connect MCP tools and
  enable the skills each project needs.
- **Continue with context:** keep session history and manage project memory for
  later conversations.

## Quick start

### 1. Prepare the environment

| Tool | Requirement | Purpose |
| --- | --- | --- |
| [Python](https://www.python.org/downloads/) | 3.12 or newer | SDK and API server |
| [Node.js](https://nodejs.org/en/download) | 22.22.0 or newer | Frontend server |
| pnpm | 10.17.1 | Frontend dependencies |

After installing Node.js, install pnpm:

```bash
npm install --global pnpm@10.17.1
```

Check your environment with `python --version`, `node --version` and
`pnpm --version`. If you do not already have a Python environment, create one:

```bash
python -m venv .venv
source .venv/bin/activate
```

On Windows PowerShell, activate it with `.\.venv\Scripts\Activate.ps1` instead.
An existing virtual or Conda environment also works. Run the following `pip`
and `ms-agent` commands in that environment.

### 2. Install and start

```bash
pip install -U "ms-agent[webui]"
ms-agent ui
```

The `[webui]` extra installs the Python dependencies for the interface. The first
start also downloads frontend runtime dependencies; later starts reuse them.
Packages published on PyPI include built pages and styles. If you install the
SDK directly from Git or an unprepared source tree, the first start also builds
the frontend in your cache; later starts reuse the validated build.

The browser opens automatically, usually at **http://127.0.0.1:8000**. If the
port is occupied, the launcher selects another available port; use the URL
printed in the terminal. Press **Ctrl-C** to stop the service.

### 3. Start a conversation

1. Open **Settings → Models** and add a provider's API key, endpoint and model.
2. Create or open a project, choosing a workspace, skills and MCP tools as needed.
3. Create a session, choose a model and enter your task. Attach files or images
   when relevant.

## Edit project files

Open a project's workspace to create files or folders, rename entries in place,
and edit text files. Changes stay in the editor when switching between files;
press **Cmd/Ctrl+S** to save the open file, or choose **Save all and close**
when closing the workspace editor. Save before leaving the page
or refreshing the browser: these unsaved buffers are not stored on disk.

If another editor or the agent changes a file, the workspace detects it when
rechecking the open file. With unsaved edits, review the warning before choosing
to reload from disk or overwrite with your version. Reloading discards your draft.

## Startup options

```bash
# Choose the browser-facing port
ms-agent ui --port 8080

# Start without opening a browser
ms-agent ui --no-browser

# Listen on the machine's other network interfaces
ms-agent ui --host 0.0.0.0 --port 8000
```

The application has no built-in login. Configure access control through a
reverse proxy or network settings when sharing it with other users.

| Option | Description |
| --- | --- |
| `--host HOST` | Bind address; defaults to `127.0.0.1` |
| `--port PORT` | Browser-facing port; otherwise choose a free port from 8000 |
| `--backend-port PORT` | Internal API port; usually does not need to be set |
| `--no-browser` | Do not open a browser |
| `--skip-install` | Skip dependency installation; still validate pages and CSS and rebuild stale source output |
| `--prepare-only` | Prepare dependencies and exit without starting services |
| `--startup-timeout SECONDS` | Startup timeout; defaults to 120 seconds |
| `--production` | Compatibility option; built frontend output is already the default |
| `--reload` | Currently unsupported; use the development commands below |

Explicit ports must be available and different for the frontend and API. If a
service exits unexpectedly, the launcher stops the other service and reports
an error.

## Configuration and data

Models, tools and memory can usually be configured in the interface. Environment
variables such as `OPENAI_API_KEY` and `OPENAI_BASE_URL` are also supported;
`MS_AGENT_LLM_PROVIDER` and `MS_AGENT_LLM_MODEL` provide first-run defaults.

Project settings, sessions and managed skills are stored in `~/.ms_agent` by
default. Set `MS_AGENT_HOME` to use another directory. Project workspace files
remain at their original paths. Frontend dependency caches are separate from
application data; `MS_AGENT_WEBUI_CACHE` selects a different cache location.

Pip installations read process environment variables and saved SDK settings,
without discovering `.env` files in the current directory. Source installations
also read `.env` files from the repository root, `webui/` and `webui/backend/`,
in that order. Later files take precedence; process environment variables win
over all files. See the [configuration example](backend/.env.example).

Local vector memory needs the optional `fastembed` package and downloads an
embedding model on first use. For a pip installation, run `pip install fastembed`
in the active environment. For a source checkout, run
`uv sync --locked --extra local-embed` in `webui/backend/`. Other model and search services use their own
settings; ordinary chat does not require a local embedding model.

## Run from source and develop

Source installations also require [uv](https://docs.astral.sh/uv/getting-started/installation/)
0.5 or newer, which can be installed with `pip install uv`.

```bash
git clone https://github.com/modelscope/ms-agent.git
cd ms-agent
pip install -e .
ms-agent ui
```

The first start prepares the backend environment, installs frontend dependencies
and builds the application, including CSS. Later starts check whether source
changes require a new build.

For live development, open two terminals at the repository root:

```bash
# Terminal 1: API
cd webui/backend
uv sync --locked
uv run dev
```

```bash
# Terminal 2: frontend
cd webui/frontend
pnpm install --frozen-lockfile
pnpm dev
```

Open **http://localhost:5173**. The frontend development server connects to the
API on local port 8000 by default.

Install frontend dependencies before running backend tests; launcher tests use
the frontend’s `tsx` tool. Run `uv run pytest` in `webui/backend/`, and `pnpm typecheck` and `pnpm build` in
`webui/frontend/`. Use the full `pnpm build` command to generate matching CSS,
client files and server output.

Windows supports the same installation and startup commands. Source checkouts
also provide a PowerShell wrapper:

```powershell
.\webui\scripts\start-webui.ps1 --no-browser
```

See [AGENTS.md](AGENTS.md) for development conventions and the
[build tools guide](../.dev_scripts/webui/README.md) for package preparation.

## Run with Docker

Docker does not require Python, Node.js or pnpm on the host. Replace `TAG` with
the published image tag you want to use:

```bash
docker run --rm -p 127.0.0.1:9000:8000 \
  -e MS_AGENT_HOME=/data -v ms-agent-data:/data \
  modelscope-registry.us-west-1.cr.aliyuncs.com/modelscope-repo/ms-agent:TAG
```

Open **http://127.0.0.1:9000**. The `ms-agent-data` volume stores application data;
keep it when replacing the container. Mount project directories separately to
work on host files. To change the access port, change the left side of `9000:8000`.

`MS_AGENT_FRONTEND_HOSTED_MODE=1` hides local-path controls that are unsuitable
for remote users; access control still needs to be configured separately.

### Agent Python environment

The service runs in `/opt/venv`. The agent's shell uses the container's system
Python and pip under `/usr/local/bin`, with `requests`, `PyYAML` and
`beautifulsoup4` preinstalled. Git, Node.js, npm/npx, pnpm and uv/uvx are also
available. Ordinary `pip install` commands do not change the service's packages.

Reuse a project's own virtual environment when it has one, or create one for
incompatible package versions. Each tool call starts a new shell: use the
environment's executable path or activate it in the same call as the command.
With uv, use `uv pip install --system PACKAGE` for container system packages;
omit `--system` when installing into a project virtual environment.

`MS_AGENT_SHELL_PATH` selects the shell's default tool path without changing the
service PATH. Explicit `tools.code_executor.shell_env` settings take precedence.
Local SDK installs keep their existing PATH unless this variable is set.
Packages installed into a running container's system Python are lost when that
container is replaced. Put recurring dependencies in a derived image.

### Python package sources

The image uses the Tsinghua PyPI mirror for runtime `pip`, `uv` and `uvx`
downloads.

To use another mirror or a company package index, create two files on the host.
For example, to use the official PyPI index, save this as `pip.conf`:

```ini
[global]
index-url = https://pypi.org/simple
```

Save this as `uv.toml`:

```toml
[[index]]
url = "https://pypi.org/simple"
default = true
```

Add these options before the image name in the `docker run` command above:

```bash
--mount type=bind,src="$PWD/pip.conf",dst=/etc/pip.conf,readonly \
--mount type=bind,src="$PWD/uv.toml",dst=/etc/uv/uv.toml,readonly \
```

Use file mounts for container-wide defaults: the agent's execution tools do not
inherit every environment variable passed with `-e`. Package indexes cover
PyPI packages; Git repositories and model downloads use their own addresses.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| `ms-agent`, `node` or `pnpm` is not found | Confirm installation and command availability in the current terminal; reopen the terminal after installation if needed |
| Python or Node version is unsupported | Check the requirements above and which interpreter the terminal uses |
| An explicit port is occupied | Choose another `--port`, or omit it for automatic selection |
| Pages or styles are missing | For source installs, run `pnpm build` in `webui/frontend/`; for pip installs, reinstall the package and follow the error message to prepare its cache again |
| Default project metadata is missing | Open the WebUI recovery page. Choose **Not now** to keep the data as-is, or **Restore default project** and confirm. Recovery backs up the managed project directory before rebuilding its record; existing conversations and global settings are kept, but project settings reset to defaults |
| Model connection or authentication fails | Check the provider's API key, endpoint, model name and network access |
| WebUI Python dependencies are missing | Run `pip install -U "ms-agent[webui]"` in the environment used to start the app |
