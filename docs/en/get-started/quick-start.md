# Quick start

Install MS-Agent 1.7.0 from PyPI using either the WebUI or terminal path below. Python application developers can finish terminal installation and continue with the [Python SDK](python-sdk.md).

## Choose an interface

| Interface | Requirements | Use it for |
| --- | --- | --- |
| WebUI | Python 3.12+, Node 22.22.0+, pnpm 10.17.1 | Conversations and project files in your browser |
| TUI / CLI / SDK | Python 3.10+ | Terminal interaction, tasks, embedded applications |

Basic API-backed conversations do not require a local GPU. Optional research, vector retrieval, and video tools have additional dependencies. Commands below use a macOS/Linux shell; the Windows activation alternative is noted separately. Platform support and individual dependencies must be checked independently.

(environment)=
## Prepare Python

Check `python3 --version` against your chosen interface; Python 3.12 is recommended for a first installation. In the directory where you want to keep the environment:

```bash
python3 -m venv ms-agent-env
source ms-agent-env/bin/activate
python --version
python -m pip --version
```

You can activate an existing virtual or Conda environment instead. In Windows PowerShell, use `python -m venv ms-agent-env` and `.\ms-agent-env\Scripts\Activate.ps1`. Run subsequent installation commands inside the activated environment.

````{dropdown} Need Python or Node.js?
Prepare Python with uv if you do not already have a suitable environment:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
uv venv --python 3.12 --seed ms-agent-env
source ms-agent-env/bin/activate
```

For the WebUI, Node.js can be installed in your user directory with nvm:
```bash
curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
export NVM_DIR="$HOME/.nvm"
source "$NVM_DIR/nvm.sh"
nvm install 22.22.0
node --version
```
Review downloaded installation scripts and their sources before running them. They change your local tool environment. Avoid installing project dependencies into system Python.
````

(webui)=
## Path 1: WebUI

### 1. Install and start

```bash
npm install --global pnpm@10.17.1
python -m pip install -U "ms-agent[webui]"
ms-agent ui
```

The WebUI runs in the active Python environment. The package includes the built frontend; first launch uses pnpm to install its Node dependencies in a local cache. Stay connected and wait for the ready URL. The launcher selects a free port starting at `http://127.0.0.1:8000`; use the address printed in your terminal.

The base `ms-agent` package does not include WebUI backend dependencies. Use the `[webui]` extra as shown above. Git and uv are only needed for the [source workflow](#install-from-source), not this PyPI installation.

### 2. Configure a model

1. Open **Settings → Models**, select a provider, and click **Edit** to save your API key. ModelScope keys are available on the [access token page](https://modelscope.cn/my/myaccesstoken). If your provider is not listed, follow the [model settings guide](../user-guide/model-settings.md) to add it first.
2. Choose **Add model** and enter a supported model ID, such as `Qwen/Qwen3.8-Flash-Next` for ModelScope.
3. Return to chat and select the model below the message box. Keep permissions set to **Always ask** for your first task.

Saving a key does not add or select a model. Keep real keys out of conversations and screenshots.

### 3. Complete a small task

Start with “Describe in two sentences how you can help me.” After a successful reply, use a project containing only test files and ask: “Read the README and list three key points. Do not change any files.”

Check that replies arrive, tool calls and results are visible, and you can continue after the task ends. Inspect requested operations and paths before approving them. A reachable page alone does not validate model credentials or tools.

Continue with the [WebUI guide](../user-guide/webui.md).

(terminal)=
## Path 2: Terminal

Install the base package in your activated Python environment and set your ModelScope API key:

```bash
python -m pip install -U ms-agent
export MODELSCOPE_API_KEY='<your-api-key>'
```

If you already installed the WebUI, the same environment includes the terminal interfaces and SDK; only configure your key. A local `.env` can supply the key for terminal use; never commit it. Do not assume a model saved in the WebUI is automatically the default for every CLI invocation.

For ongoing interaction:

```bash
ms-agent tui
```

Enter `/help`, try a read-only task, and exit with `/quit`. See the [TUI guide](../user-guide/tui.md) for configuration and recovery. For a single task:

```bash
ms-agent run --query 'Explain an agent in two sentences.'
```

The default agent may download additional dependencies on first initialization. Follow terminal progress. Use an explicit YAML to fix the model, tools, and output directory; see the [CLI guide](../user-guide/cli.md).

(restart)=
## Stop and restart

Stop the WebUI with `Ctrl-C` in its terminal. In a new terminal, enter the directory containing your environment:

```bash
source ms-agent-env/bin/activate
ms-agent ui
```

Use `ms-agent tui` for the TUI, and restore any API key environment variables needed for terminal use. If Node was installed through nvm, verify `node --version`, loading `source "$HOME/.nvm/nvm.sh"` if necessary. Saved WebUI models, projects, and conversations remain available. Restarting a process does not automatically resume an interrupted tool operation.

## Upgrade an existing installation

Stop the service, activate its Python environment, and run `python -m pip install -U "ms-agent[webui]"` again. For a terminal/SDK-only environment, use `python -m pip install -U ms-agent`. These commands also upgrade a 1.7.0 release candidate to the stable release. Keep your application data and credential master key; see [credential storage and recovery](../user-guide/credentials.md).

(extras)=
## Add dependencies when needed

Install extras in the same Python environment. Keep the quotes for shells such as zsh:

| Capability | Command |
| --- | --- |
| Vector/hybrid skill retrieval | `python -m pip install -U "ms-agent[retrieval]"` |
| Research and document parsing | `python -m pip install -U "ms-agent[research]"` |
| Code applications and integrations | `python -m pip install -U "ms-agent[code]"` |
| Video generation | `python -m pip install -U "ms-agent[cinema]"` |
| ACP / A2A | `python -m pip install -U "ms-agent[acp]"` / `python -m pip install -U "ms-agent[a2a]"` |
| All features, Python 3.12+ | `python -m pip install -U "ms-agent[all]"` |

The base package does not include torch/CUDA; some extras pull large dependencies. For CPU-only torch on Linux, install `python -m pip install torch --index-url https://download.pytorch.org/whl/cpu` before the relevant extra. Applications may still require accounts, external tools, or model deployments.

<a id="source-install"></a>

## Install from source

For development or unreleased features, install a checkout in a separate Python environment. This workflow also needs Git:

```bash
git clone https://github.com/modelscope/ms-agent.git
cd ms-agent
python -m pip install -e .
```

For the WebUI, also prepare Node.js and pnpm as listed above, and install uv with `python -m pip install "uv>=0.5"`. Run `ms-agent ui` from the checkout. First launch prepares a separate backend environment in `webui/backend/.venv`, installs frontend dependencies, and builds the frontend. The `[webui]` extra is not needed for this editable source workflow. See [WebUI development](https://github.com/modelscope/ms-agent/blob/release/1.7/webui/README.md#run-from-source-and-develop) for live development commands.

To add extras to an editable installation, use commands such as `python -m pip install -e '.[research]'` from the checkout rather than replacing it with a PyPI package.

See [Deployment and data](../user-guide/deployment.md) for Docker and remote access, or [Troubleshooting](../user-guide/troubleshooting.md) for startup, model, and file problems.
