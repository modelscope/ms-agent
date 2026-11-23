# MS-Agent WebUI

Use MS-Agent in your browser to research, write code and work with project files.
Conversations, tool activity and generated results stay together so you can
follow a task and continue the conversation. [中文说明](README_ZH.md)

- **Organize work by project:** open a local folder, manage multiple sessions,
  and browse or edit project files.
- **Follow the agent's progress:** stream replies, reasoning, tool calls and
  generated files as the task runs.
- **Add input while a task runs:** queue follow-ups or steer the current task,
  with editable pending messages that survive a page refresh.
- **Choose models and tools:** configure model providers, connect MCP tools and
  enable the skills each project needs.
- **Continue with context:** keep session history and manage project memory for
  later conversations.

## Quick start

Install and start the WebUI from source with the following steps.

### 1. Prepare the environment

| Tool | Requirement | Purpose |
| --- | --- | --- |
| [Python](https://www.python.org/downloads/) | 3.12 or newer | SDK and API server |
| [Node.js](https://nodejs.org/en/download) | 22.22.0 or newer | Frontend server |
| pnpm | 10.17.1 | Frontend dependencies |
| [uv](https://docs.astral.sh/uv/) | 0.5 or newer | Separate backend Python environment |
| Git | A current version | Clone the source |

<a id="first-time-setup"></a>

#### First-time Setup

See the [documentation quick start](../docs/en/get-started/quick-start.md) for complete setup, including Python through uv, Node.js through nvm, and Windows environment activation. The steps below remain a standalone launch guide when Python and Node.js are already available.

<a id="install-nodejs"></a>
<a id="install-python"></a>

If you need Python or Node.js, complete “Prepare Python” and its environment-setup dropdown in the quick start before continuing.

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

Activate an existing virtual or Conda environment instead if you already have one. If you created and activated an environment in the quick start, you can skip this step. In Windows PowerShell, use `python -m venv ms-agent-env` and `.\ms-agent-env\Scripts\Activate.ps1`. Run all subsequent commands in the activated environment.

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

1. Open **Settings → Models**. For a built-in provider such as ModelScope, OpenAI, or Alibaba (DashScope), select it, click **Edit**, enter your API key, and save. Built-in providers already have an endpoint. You can get a ModelScope key from the [access token page](https://modelscope.cn/my/myaccesstoken).
2. If your service is not in the list, click **Add provider**. Enter a **Provider ID**, the **Base URL** supplied by your provider, and an **API Key**. Choose a **Protocol**, then save. A **Display Name** is optional. Do not use a website console or the full `chat/completions` path as the Base URL.
3. Under the selected provider, click **Add model** and enter a model ID from that service. For ModelScope, one example is `Qwen/Qwen3.8-Flash-Next`. For other providers, use the model ID they give you. Saving a key does not add or select a model.
4. Return to chat, use the default project or create one, select the new model below the input, leave the permission setting at **Always ask**, and send a short text request such as: “Describe in two sentences how you can help me.” Attach files or images later, when you need them.

Keys and sessions are saved on this computer (by default under `~/.ms_agent`). You can set `MS_AGENT_HOME` to use another directory. Do not commit `.env` files, and do not put real keys in the chat or in screenshots.

### 4. Start Again Later

When you open a new terminal, activate the environment again and start the service. Assuming the environment and repository are in the same parent directory:

```bash
source ms-agent-env/bin/activate
cd ms-agent
ms-agent ui
```

First change to the directory where you saved them. Model configuration and sessions persist, so you do not need to enter your API key again. If you installed Node.js through nvm, check `node --version` in the new terminal. If the command is missing, run `source "$HOME/.nvm/nvm.sh"` first.

For everyday use after this first reply, see the [WebUI guide](../docs/en/user-guide/webui.md), [model settings](../docs/en/user-guide/model-settings.md), and [skills and MCP](../docs/en/user-guide/skills-mcp.md). If a request fails, see [Troubleshooting](../docs/en/user-guide/troubleshooting.md).

## Add input during a task

Keep typing, attaching files or selecting skills while the agent works. New
messages **queue by default** and run in order after the current task finishes.
In **Settings → Personalization → Conversation behavior**, select **Steer** to
add new messages to the current task after its current model response or started
tool operations finish. Changing this setting only affects new submissions.

Pending messages appear above the input box, where you can edit or withdraw
them. Once processing starts, they appear as ordinary messages in the conversation.
Refreshing the page or switching sessions keeps the task running.

While a task runs, the input's action button shows **Stop** when the draft is
empty and switches to **Send** when you type, attach files or select a skill.
Clearing or successfully sending the draft brings back **Stop** if the task is
still running.

**Stop** cancels the current task and holds pending messages. **Continue sending**
releases those messages as new tasks; it does not resume cancelled operations.
You can also send a new task while earlier messages remain on hold. After a server
restart, pending messages stay on hold until you resume them.

## Branch a conversation

Click **Branch** beside the copy button below a completed reply to
continue in a new session, named `Original title (2)`, then `(3)`, and so on.
The new session keeps the history through that reply, including tool results
and saved summaries. A divider links back to the original conversation.

You can branch from an earlier reply while the original session is still
running. Interrupted or unfinished turns cannot be selected. The new session
starts with the original session's selected model and an empty input box;
opening it does not change your default model. The original input draft stays
in that browser tab when you return, but is not saved across a page refresh.

Sessions have independent histories and share the project's current files,
settings and memory. Branching does not copy or roll back the workspace.

<a id="model-capabilities-and-context"></a>

## Models and context

### Catalog updates

WebUI uses the models.dev snapshot bundled with the SDK to look up model
capabilities, context limits and prices. Models missing from the catalog can
still be added manually. Access depends on your provider account and endpoint.

| Installation | Default update behavior |
| --- | --- |
| Source checkout, including `pip install -e .` | Check at WebUI startup; reuse a successful check for 24 hours and retry a failed check after 15 minutes |
| Wheel or image | Use bundled data or a newer compatible local cache |
| Either installation | Choose **Settings → Models → Update catalog** to download data, then restart the service to apply it |

Update requests have an 8-second timeout. Downloads go to
`$MS_AGENT_HOME/cache/models.dev/v1`; failed updates leave the current local data
available. Settings shows the active catalog and any version awaiting a restart.
On restart, the SDK selects the newer compatible bundle or cache.

`MS_AGENT_MODEL_CATALOG` controls updates:

| Value | Behavior |
| --- | --- |
| `auto` (default) | Apply the installation-specific defaults above |
| `local` | Skip startup checks; allow manual updates |
| `bundled` | Use only the bundled snapshot; disable updates |

`ms-agent ui --skip-install` also skips automatic catalog checks. Installing with
pip, querying metadata and building packages do not download a catalog. TUI
update controls are not available yet.

### Thinking and images

Choose a reasoning setting in model settings or beside the chat model selector.
Each conversation remembers the choice for each model. Changing it also updates
the default for new conversations; returning to an existing conversation restores
its saved choice. Only supported settings are listed. Native thinking parameters
in Advanced JSON take priority and disable the shortcut.

Image understanding supports **Auto / On / Off**. Auto reads the catalog and is
off for unknown models. Existing On/Off choices are preserved; select Auto to
restore detection. When image understanding is off, WebUI warns and passes file
paths rather than image pixels. Use On for a custom deployment known to support
images. Catalog audio, video and PDF labels describe model capabilities; those
native upload formats are not supported by this interface.

### Context usage and compression

The circle to the left of the attachment button shows estimated usage for the
last assembled request. Click it to view system prompt, tool definition and
message usage, or choose **Compress context**. Output reservation is shown
separately. Changing the model or configuration clears the old estimate until
the next request.

The context limit in model settings can reduce a known model's window or provide
a limit for an unknown model. Clear it to restore defaults. Automatic compression
normally starts near 85% of the effective window, or earlier when input limits
and output reservation require it.

Manual and automatic compression use the same SDK operation as `/compact`.
WebUI does not yet route slash commands. Compression runs without adding a user
message, continues if you leave the page, and can be cancelled with Stop. On
completion, the history shows the trigger and estimated token counts before and
after compression. Original messages remain in the session log.

If summarization fails, the previous context is retained. When that context is
too large to send, **Retry compression and continue** resumes the saved request
without adding a duplicate message. If the latest input alone is too large,
shorten it or choose a larger model/window.

### Memory and usage records

When project memory is enabled, compression can first extract durable facts.
An ordinary memory failure retains the previous memory and retry sources while
allowing a valid summary to commit. System instructions are reloaded before the
next request. Summaries use a separate, lower-cost reasoning setting and may
omit details; keep important evidence in project files.

The SDK records response usage independently of successful compaction. Cost
estimates are marked complete, partial or unknown; amounts are not shown in
WebUI. See [Context](../docs/en/core/context.md), [Models](../docs/en/core/models.md),
and [Memory](../docs/en/core/memory.md) for storage, recovery, and pricing details.

## Install and update skills

Open **Settings → MCP & Skills → Skills**, or a project's **Skills** panel. Choose **Add skill → Install from link** and paste a GitHub repository, subdirectory, or ModelScope Skill or collection URL. Select one or more skills and choose a global or project installation.

The open app checks linked skills periodically; **Check for updates** also runs a manual check. Open a card marked **Update available**, review the file changes, and confirm the update. The details menu offers **Restore previous version** afterward. Replacing local changes requires confirmation and keeps one backup. Checks and previews remain available during active tasks; replacing files waits until those tasks finish.

Local imports continue to work. Use **Link source** in an untracked managed skill's details to enable updates. Skills discovered in standard directories remain read-only. See [Skill installation and updates](../docs/en/user-guide/skill-management.md) for source rules and the shared SDK API.

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

Authentication is off by default for local use. Before exposing the service
to a network, enable the built-in login below or place it behind an
authenticated gateway that cannot be bypassed.

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

## Optional login

MS-Agent is a framework for local agent work. Its WebUI listens on
`127.0.0.1` by default and opens directly into chat. To require a login, set
these variables before starting it (or add them to `webui/backend/.env`):

```dotenv
MS_AGENT_WEBUI_AUTH_ENABLED=true
MS_AGENT_WEBUI_USERNAME=admin
MS_AGENT_WEBUI_PASSWORD=replace-with-a-long-unique-password
```

Restart `ms-agent ui`, then sign in with that username and password. This is
one account for the instance; there is no registration. The username defaults
to `admin`, and an enabled instance refuses to start without a password.
Login lasts seven days, including across service restarts. Use **Settings →
Sign out** on a shared browser. Changing either credential and restarting
invalidates existing logins; forgotten credentials can be replaced the same way.

When enabled, login protects both pages and backend APIs, including files,
settings and conversation streams. Cookies are HttpOnly and SameSite=Lax;
HTTPS login also sets Secure. Browser writes must come from the same origin
or an explicit `MS_AGENT_CORS_ORIGINS` entry; wildcard origins are rejected
when authentication is enabled. Use HTTPS when accessing an instance remotely.

Set `MS_AGENT_WEBUI_AUTH_ENABLED=false` (the default) to open chat without
logging in. Disabling login does not restrict API access by itself.
The launcher warns when binding beyond loopback with authentication disabled.
`MS_AGENT_FRONTEND_HOSTED_MODE` changes visible controls, not access control.

## Configuration and data

Models, tools and memory can usually be configured in the interface. Environment
variables such as `OPENAI_API_KEY` and `OPENAI_BASE_URL` are also supported;
`MS_AGENT_LLM_PROVIDER` and `MS_AGENT_LLM_MODEL` provide first-run defaults.

Project settings, sessions and managed skills are stored in `~/.ms_agent` by
default. Set `MS_AGENT_HOME` to use another directory. Project workspace files
remain at their original paths. For source installations, the backend environment
lives in `webui/backend/.venv`, while frontend dependencies and build output live
in `webui/frontend/`, separate from project data.

Saved model and search API keys are encrypted. The instance master key defaults
to the normalized home plus `.secrets/master.key` (normally `~/.ms_agent.secrets/master.key`),
outside the application data directory. Keep it when upgrading or moving your
own deployment; exclude it when sharing a template. Upgrade WebUI, TUI, CLI and
SDK installations sharing configuration together; older versions cannot read
ciphertext. See
[saving and recovering credentials](../docs/en/user-guide/credentials.md) for migration,
external key files and recovery after key loss, and
[credential storage design](../docs/en/development/credential-storage.md) for extension interfaces.

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

Run `pnpm check:skills` in `webui/frontend/` for Skill operation progress,
partial-result and cancellation regression checks. It uses controlled HTTP
responses and does not contact Skill registries or models.

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
  -v ms-agent-secrets:/data.secrets \
  modelscope-registry.us-west-1.cr.aliyuncs.com/modelscope-repo/ms-agent:TAG
```

Open **http://127.0.0.1:9000**. `ms-agent-data` stores application data and
`ms-agent-secrets` stores the default master key; retain both when replacing the
container. Mount project directories separately to work on host files. To change
the access port, change the left side of `9000:8000`. For a platform-provided
read-only key, follow [Deployment](../docs/en/user-guide/deployment.md) instead of
mounting the default key volume.

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

### MCP startup and recovery

MCP tools are optional: if some or all servers fail to start, ordinary chat and
built-in tools remain available. A notice identifies the missing capabilities.
Startup includes connecting, initializing and fetching the first tool list.
The default is 60 seconds per server after it obtains a concurrency slot (up to
8 servers start together), followed by a separate cleanup grace period. Set
`MCP_STARTUP_TIMEOUT`, or a positive `startup_timeout` in a server's JSON entry,
to adjust the startup budget. Ordinary tool calls keep their own timeout.

The initial stdio check only confirms that its command exists and displays
**Connection not verified**. **Test connection** creates an independent connection
and reads its tools; it does not repair an existing conversation. In the card's
menu, **Reconnect sessions next turn** schedules affected conversations to
rebuild before their next idle turn. Current replies continue, and the session
ID and conversation history are retained. Disabled servers stay disabled.
Business tool calls are never replayed automatically.

Automatic remote checks allow up to 6 seconds; a manual connection test allows
up to 45 seconds. A server's smaller `startup_timeout` still applies. Concurrent
checks share work only when their effective budgets match, and one malformed
server configuration does not prevent other health results from being returned.

Startup notices expose controlled error categories and HTTP status codes, not
raw server output, command arguments or connection addresses. Unknown details
are withheld because they may contain credentials. The model receives a fixed
capability notice, without external error details.
Transport library logs also omit raw details within MCP connection tasks;
other requests using those libraries keep their normal logging.

### Python package sources

The image uses the Tsinghua PyPI mirror for runtime `pip`, `uv` and `uvx`
downloads. Runtime npm/npx uses `https://registry.npmmirror.com/`, configured
in npm's global config (`npm config get globalconfig`).

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

File mounts provide container-wide defaults. MCP subprocesses and the agent's
shell also inherit explicitly allowed package settings: `PIP_INDEX_URL`,
`PIP_CONFIG_FILE`, `PIP_CACHE_DIR`, `UV_INDEX_URL`, `UV_DEFAULT_INDEX`,
`UV_CONFIG_FILE`, `UV_CACHE_DIR`, and npm registry/cache/userconfig/globalconfig
variables in upper or lower case. Explicit MCP `env` and tool `shell_env` take
precedence. Other application credentials are not inherited automatically.

Validate actual wheel/tarball downloads in the deployment network, then test
MCP initialization and tool listing with a fresh cache. A reachable index alone
is insufficient. There is no automatic switch to a second registry. Cache
directories must be writable by the runtime user; persistence depends on the
container's volume mounts. Git repositories and model downloads use their own
addresses.

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
