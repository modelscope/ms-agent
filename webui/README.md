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

**The new WebUI is not yet available on PyPI. Clone the source and install it in
editable mode as described below.** The published `ms-agent==1.6.0` uses the older
WebUI and does not provide the workspace described in this guide.

### 1. Prepare the environment

| Tool | Requirement | Purpose |
| --- | --- | --- |
| [Python](https://www.python.org/downloads/) | 3.12 or newer | SDK and API server |
| [Node.js](https://nodejs.org/en/download) | 22.22.0 or newer | Frontend server |
| pnpm | 10.17.1 | Frontend dependencies |
| [uv](https://docs.astral.sh/uv/) | 0.5 or newer | Separate backend Python environment |
| Git | A current version | Clone the source |

#### First-time Setup

The commands below use a macOS / Linux shell. If you do not yet have suitable Python and Node.js versions, follow the setup below. Otherwise, skip to [check and activate your environment](#check-and-activate-your-environment). First run `git --version`; if macOS prompts you to install Command Line Tools, complete that installation before continuing.

##### Install Node.js

Install [nvm](https://github.com/nvm-sh/nvm), then use it to install Node.js. This keeps Node in your user directory, so installing pnpm does not require `sudo`:

```bash
curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
export NVM_DIR="$HOME/.nvm"
source "$NVM_DIR/nvm.sh"
nvm install 22.22.0
npm install --global pnpm@10.17.1
node --version
pnpm --version
```

##### Install Python

Install uv and use it to download Python 3.12 and create an environment with pip. Run this in the directory where you plan to keep the project:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
uv venv --python 3.12 --seed ms-agent-env
source ms-agent-env/bin/activate
python --version
pip --version
```

Keep this terminal and environment active, then continue with the uv check and source installation below.

#### Check and Activate Your Environment

If Python and Node.js are already installed, check `python3 --version` and `node --version`, then install pnpm:

```bash
npm install --global pnpm@10.17.1
pnpm --version
```

If you do not have a Python environment yet, make sure `python3` is version 3.12+ and create one:

```bash
python3 -m venv ms-agent-env
source ms-agent-env/bin/activate
```

Activate an existing virtual or Conda environment instead if you already have one. If you created and activated an environment above, you can skip this step. In Windows PowerShell, use `python -m venv ms-agent-env` and `.\ms-agent-env\Scripts\Activate.ps1`. Run all subsequent commands in the activated environment.

Install uv and check that it is available in the current terminal:

```bash
pip install uv
uv --version
```

### 2. Clone, install and start

```bash
git clone https://github.com/modelscope/ms-agent.git
cd ms-agent
pip install -e .
ms-agent ui
```

The editable installation makes `ms-agent` use the SDK in this checkout.
On first start, uv prepares the backend and its dependencies in
`webui/backend/.venv`; the launcher installs frontend dependencies and builds
pages and styles in `webui/frontend/`. There is no need to install
`ms-agent[webui]` separately. Keep your network connection available and wait for
the ready URL in the terminal. Later starts check dependencies and build state,
reusing valid build output.

The browser opens automatically, usually at **http://127.0.0.1:8000**. If the
port is occupied, the launcher selects another available port; use the URL
printed in the terminal. Press **Ctrl-C** to stop the service.

### 3. Start a conversation

For ModelScope, obtain an API key from the [access token page](https://modelscope.cn/my/myaccesstoken).

1. Open **Settings → Models**, select **ModelScope → Edit**, enter your API key, and save. Built-in providers already have an endpoint. For another OpenAI-compatible service, use **Add provider** to enter its Base URL and key.
2. Click **Add model** under that provider and enter a model ID supported by the service, such as `Qwen/Qwen3-235B-A22B-Instruct-2507`. Availability and quotas depend on your provider account.
3. Return to chat, use the default project or create one, select the new model below the input, and send your first message. Attach files or images when relevant.
4. Configure a project workspace, skills, and MCP tools as needed.

### 4. Start Again Later

When you open a new terminal, activate the environment again and start the service. Assuming the environment and repository are in the same parent directory:

```bash
source ms-agent-env/bin/activate
cd ms-agent
ms-agent ui
```

First change to the directory where you saved them. Model configuration and sessions persist, so you do not need to enter your API key again. If you installed Node.js through nvm, check `node --version` in the new terminal. If the command is missing, run `source "$HOME/.nvm/nvm.sh"` first.

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
remain at their original paths. For source installations, the backend environment
lives in `webui/backend/.venv`, while frontend dependencies and build output live
in `webui/frontend/`, separate from project data.

The editable source installation described here reads saved SDK settings and
loads `.env` files from the repository root, `webui/` and `webui/backend/`, in
that order. Later files take precedence; process environment variables win over
all files. See the [configuration example](backend/.env.example).

Local vector memory needs the optional `fastembed` package and downloads an
embedding model on first use. Run `uv sync --locked --extra local-embed` in
`webui/backend/` to install it into the backend environment. Other model and search services use their own
settings; ordinary chat does not require a local embedding model.

## Run from source and develop

After completing the quick start above, develop in the same checkout.
Run `ms-agent ui` again after changing source files; it checks and rebuilds stale
frontend output.

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
| `ms-agent`, `uv`, `node` or `pnpm` is not found | Confirm installation, activate the Python environment and check command availability in the current terminal; reopen the terminal if needed |
| `python` / `pip` is missing, or `externally-managed-environment` appears | Create and activate a virtual environment as described above; avoid installing into the system Python. Check `python --version` and `pip --version` after activation |
| `npm install --global` reports `EACCES` | Use the nvm setup above to install Node.js and pnpm in your user directory |
| Python or Node version is unsupported | Check the requirements above and which interpreter the terminal uses |
| An explicit port is occupied | Choose another `--port`, or omit it for automatic selection |
| Pages or styles are missing | Run `ms-agent ui` again to validate and build the frontend; if the build fails, check Node.js, pnpm and network access as indicated by the error |
| Default project metadata is missing | Open the WebUI recovery page. Choose **Not now** to keep the data as-is, or **Restore default project** and confirm. Recovery backs up the managed project directory before rebuilding its record; existing conversations and global settings are kept, but project settings reset to defaults |
| Model connection or authentication fails | Check the provider's API key, endpoint, model name and network access |
| WebUI Python dependencies are missing | Confirm uv is available, then run `ms-agent ui` without `--skip-install` to synchronize the backend environment |
