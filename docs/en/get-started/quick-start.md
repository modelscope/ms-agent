# Quick start

Choose either the WebUI or terminal path below. Python application developers can finish terminal installation and continue with the [Python SDK](python-sdk.md).

## Choose an interface

| Interface | Requirements | Use it for |
| --- | --- | --- |
| WebUI | Python 3.12+, Node 22.22.0+, pnpm 10.17.1, uv 0.5+, Git | Conversations and project files in your browser |
| TUI / CLI / SDK | Python 3.10+, Git | Terminal interaction, tasks, embedded applications |

Basic API-backed conversations do not require a local GPU. Optional research, vector retrieval, and video tools have additional dependencies. Commands below use a macOS/Linux shell; the Windows activation alternative is noted separately. Platform support and individual dependencies must be checked independently.

(environment)=
## Prepare Python

Check `python3 --version` against your chosen interface; Python 3.12 is recommended for a first installation. In the directory where you want to keep the environment and checkout:

```bash
python3 -m venv ms-agent-env
source ms-agent-env/bin/activate
python --version
pip --version
```

You can activate an existing virtual or Conda environment instead. In Windows PowerShell, use `python -m venv ms-agent-env` and `.\ms-agent-env\Scripts\Activate.ps1`. Run subsequent installation commands inside the activated environment.

````{dropdown} Need Python or Node.js?
Run `git --version` first. On macOS, complete any Command Line Tools installation prompt before continuing.

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
pip install uv
git clone https://github.com/modelscope/ms-agent.git
cd ms-agent
pip install -e .
ms-agent ui
```

The first launch prepares `webui/backend/.venv`, installs frontend dependencies, and builds pages. Stay connected and wait for the ready URL. The launcher selects a free port starting at `http://127.0.0.1:8000`; use the address printed in your terminal.

Do not clone over an existing checkout. Enter that checkout and activate the correct environment instead. Source installation does not require manually installing `ms-agent[webui]`.

### 2. Configure a model

1. Obtain a [ModelScope API key](https://modelscope.cn/my/myaccesstoken).
2. Open **Settings → Model settings → ModelScope → Edit**, enter the key, and save.
3. Choose **Add model** and enter an available model ID, such as `Qwen/Qwen3.8-Flash-Next`.
4. Return to the conversation and select that model below the input. For a custom OpenAI-compatible endpoint, use **Add provider** with its actual Base URL and key.

Saving a key does not add or select a model. Keep real keys out of conversations and screenshots.

### 3. Complete a small task

Start with “Describe in two sentences how you can help me.” After a successful reply, use a project containing only test files and ask: “Read the README and list three key points. Do not change any files.”

Check that replies arrive, tool calls and results are visible, and you can continue after the task ends. Inspect requested operations and paths before approving them. A reachable page alone does not validate model credentials or tools.

Continue with the [WebUI guide](../user-guide/webui.md).

(terminal)=
## Path 2: Terminal

Install source in your activated Python environment:

```bash
git clone https://github.com/modelscope/ms-agent.git
cd ms-agent
pip install -e .
export MODELSCOPE_API_KEY='<your-api-key>'
```

Reuse the checkout if you already installed the WebUI. A local `.env` can supply the key; never commit it. Do not assume a model saved in the WebUI is automatically the default for every CLI invocation.

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
cd ms-agent
ms-agent ui
```

Use `ms-agent tui` for the TUI. If Node was installed through nvm, verify `node --version`, loading `source "$HOME/.nvm/nvm.sh"` if necessary. Saved WebUI models, projects, and conversations remain available. Restarting a process does not automatically resume an interrupted tool operation.

(extras)=
## Add dependencies when needed

Run these in the source root and activated environment. Keep the quotes for shells such as zsh:

| Capability | Command |
| --- | --- |
| Vector/hybrid skill retrieval | `pip install -e '.[retrieval]'` |
| Research and document parsing | `pip install -e '.[research]'` |
| Code applications and integrations | `pip install -e '.[code]'` |
| Video generation | `pip install -e '.[cinema]'` |
| ACP / A2A | `pip install -e '.[acp]'` / `pip install -e '.[a2a]'` |
| All features, Python 3.12+ | `pip install -e '.[all]'` |

The base package does not include torch/CUDA; some extras pull large dependencies. For CPU-only torch on Linux, install `pip install torch --index-url https://download.pytorch.org/whl/cpu` before the relevant extra. Applications may still require accounts, external tools, or model deployments. Installation is not an end-to-end application test.

See [Deployment and data](../user-guide/deployment.md) for Docker and remote access, or [Troubleshooting](../user-guide/troubleshooting.md) for startup, model, and file problems.
