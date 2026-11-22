---
slug: Installation
title: Installation
description: Ms-Agent Installation Guide
---

# Installation

## Environment Setup

The base SDK, CLI, and TUI require Python 3.10+; WebUI requires Python 3.12+. Python 3.12 is a useful starting point for a new installation. The commands below are for macOS / Linux. For a first-time setup, see the complete [WebUI environment setup](https://github.com/modelscope/ms-agent/blob/main/webui/README.md#first-time-setup).

Check `python3 --version`, then create an environment in the directory where you plan to keep the project:

```bash
python3 -m venv ms-agent-env
source ms-agent-env/bin/activate
```

Activate an existing virtual or Conda environment instead if you already have one. Run subsequent `pip` and `ms-agent` commands in this environment, and activate it again when opening a new terminal.

## Wheel Package Installation

`pip install ms-agent` installs the published 1.6.0 release, with the older WebUI and dependency set. It lacks the current TUI and the `retrieval` and `cinema` extras. Use source installation below for the capabilities documented in the current repository.

**Older release issue:** The Sirchmunk integration in PyPI 1.6.0 loads the undeclared `loguru` dependency when importing `LLMAgent`, causing the import to fail in a clean environment. The current source uses the framework's own logger and no longer depends directly on `loguru`. New users should install from source.

## Source Code Installation

Make sure Git is installed, then run these commands in the activated environment:

```shell
git clone https://github.com/modelscope/ms-agent.git
cd ms-agent
pip install -e .
```

## Optional Dependencies (Extras)

These commands target the **current source checkout**. Run them from the repository root with the Python environment active. Keep the quotes around extras when using macOS zsh.

`pip install -e .` installs a lightweight, **CPU-only** base: conversation, tool calling, MCP, the default `bm25` skill search, local code execution (with plotting), and file-based memory. Heavier capabilities are opt-in via extras, so the base install stays small and free of `torch`/CUDA.

> **Behavior note:** the base install no longer bundles `sentence-transformers`/`faiss` or the audio/video stack. Features such as the `vector`/`hybrid` skill-search backends and the audio/video tools now require the matching extra below — otherwise you will hit a `ModuleNotFoundError`.

| Capability | Install command | Pulls torch |
|------------|-----------------|:-----------:|
| Base: chat / tools / MCP / bm25 skill search / local plotting | `pip install -e .` | No |
| Vector & hybrid skill search | `pip install -e '.[retrieval]'` | Yes |
| DeepResearch / document parsing | `pip install -e '.[research]'` | Yes |
| CodeGenesis / sandbox / mem0 memory | `pip install -e '.[code]'` | Yes |
| Video generation (singularity_cinema) | `pip install -e '.[cinema]'` | No |
| ACP / A2A protocol servers | `pip install -e '.[acp]'` / `pip install -e '.[a2a]'` | No |
| Everything (includes WebUI; Python 3.12+) | `pip install -e '.[all]'` | Yes |

For the new WebUI, follow the [source installation steps below](#webui). DeepResearch / CodeGenesis may require further project-specific dependencies — see the corresponding project README.

> **Tip (CPU-only torch):** on Linux the torch-pulling extras install the default CUDA torch wheel (several GB). For a much smaller CPU-only install, install CPU torch first, then the extra:
> ```shell
> pip install torch --index-url https://download.pytorch.org/whl/cpu
> pip install -e '.[retrieval]'
> ```

## Images

It is recommended to use ModelScope's [official LLM images](https://modelscope.cn/docs/intro/environment-setup#%E6%9C%80%E6%96%B0%E9%95%9C%E5%83%8F).

## Runtime Environment

MS-Agent runs using LLM API, so only a CPU environment is required.

| Environment | Requirements |
|-------------|--------------|
| python      | \>=3.10      |

## WebUI

**Install the new WebUI from source for the latest experience.**
Requires Git, Python 3.12+, Node.js 22.22.0+, pnpm 10.17.1 and uv 0.5+.
Run these commands in an activated Python 3.12+ virtual or Conda environment:

```shell
npm install --global pnpm@10.17.1
git clone https://github.com/modelscope/ms-agent.git
cd ms-agent
pip install uv
pip install -e .
ms-agent ui
```

The first start uses uv to prepare a separate backend environment, installs
frontend dependencies, and builds pages and styles. Keep your network connection
available and wait for the ready URL in the terminal. Later starts reuse valid
build output. See the [WebUI guide](https://github.com/modelscope/ms-agent/blob/main/webui/README.md)
for virtual environment setup and configuration.
