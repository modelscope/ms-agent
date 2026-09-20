---
slug: installation
title: 安装
description: Ms-Agent 环境安装
---

# 安装

## 环境准备

基础 SDK、CLI 和 TUI 需要 Python 3.10+；WebUI 需要 Python 3.12+，建议首次安装直接使用 3.12。以下环境命令适用于 macOS / Linux；首次配置的完整流程见 [WebUI 环境准备](https://github.com/modelscope/ms-agent/blob/main/webui/README_ZH.md#首次配置)。

先用 `python3 --version` 确认版本，再在准备存放项目的目录创建环境：

```bash
python3 -m venv ms-agent-env
source ms-agent-env/bin/activate
```

已有虚拟环境或 Conda 环境的用户直接激活即可。后续 `pip` 和 `ms-agent` 命令都在该环境中执行；重新打开终端后需再次激活。

## Wheel包安装

`pip install ms-agent` 安装 PyPI 已发布的 1.6.0，使用旧版 WebUI 和依赖组合。它没有当前源码的 TUI、`retrieval` 或 `cinema` extras。体验当前仓库介绍的功能，请使用下方源码安装。

**旧版安装问题：** PyPI 1.6.0 中的 Sirchmunk 集成会在导入 `LLMAgent` 时加载未声明的 `loguru`，导致干净环境中的导入失败。当前源码已改用框架内置日志，不再直接依赖 `loguru`；新用户请优先从源码安装。

## 源代码安装

确认已安装 Git，并在上面激活的环境中运行：

```shell
git clone https://github.com/modelscope/ms-agent.git
cd ms-agent
pip install -e .
```

## 可选依赖（Extras）

以下命令针对**当前源码**，请在仓库根目录和已激活的 Python 环境中执行。macOS zsh 下需保留 extras 参数的引号。

`pip install -e .` 安装的是轻量、**仅 CPU** 的基础包：对话、工具调用、MCP、默认的 `bm25` skill 检索、本地代码执行（含绘图）、以及基于文件的记忆。更重的能力通过 extras 按需安装，从而让基础包保持精简、不含 `torch`/CUDA。

> **行为变更提示：** 基础包不再捆绑 `sentence-transformers`/`faiss` 及音视频依赖。`vector`/`hybrid` skill 检索后端、以及音视频工具现在需要安装对应的 extra，否则会报 `ModuleNotFoundError`。

| 能力 | 安装命令 | 是否含 torch |
|------|----------|:---:|
| 基础：对话 / 工具 / MCP / bm25 skill 检索 / 本地绘图 | `pip install -e .` | 否 |
| 向量 & 混合 skill 检索 | `pip install -e '.[retrieval]'` | 是 |
| 深度研究 / 文档解析 | `pip install -e '.[research]'` | 是 |
| CodeGenesis / 沙箱 / mem0 记忆 | `pip install -e '.[code]'` | 是 |
| 视频生成（singularity_cinema） | `pip install -e '.[cinema]'` | 否 |
| ACP / A2A 协议服务 | `pip install -e '.[acp]'` / `pip install -e '.[a2a]'` | 否 |
| 全部功能（含 WebUI，需 Python 3.12+） | `pip install -e '.[all]'` | 是 |

新版 WebUI 请按下方 [WebUI 源码安装](#webui) 流程使用。DeepResearch / CodeGenesis 可能还有项目级的额外依赖，请参考对应项目的 README。

> **提示（CPU 版 torch）：** 在 Linux 上，会拉入 torch 的 extra 默认安装 CUDA 版 torch（数 GB）。如需精简的仅 CPU 安装，可先装 CPU 版 torch 再装 extra：
> ```shell
> pip install torch --index-url https://download.pytorch.org/whl/cpu
> pip install -e '.[retrieval]'
> ```

## 镜像

推荐使用魔搭的[官方LLM镜像](https://modelscope.cn/docs/intro/environment-setup#%E6%9C%80%E6%96%B0%E9%95%9C%E5%83%8F)。


## 运行环境

MS-Agent使用LLM API运行，因此仅需要CPU环境即可。

| 环境     | 需求      |
|--------|---------|
| python | \>=3.10 |

## WebUI

**新版 WebUI 请优先从源码安装。** 需要 Git、Python 3.12+、Node.js 22.22.0+、pnpm 10.17.1 和 uv 0.5+。在已激活的 Python 3.12+ 虚拟环境或 Conda 环境中执行：

```shell
npm install --global pnpm@10.17.1
git clone https://github.com/modelscope/ms-agent.git
cd ms-agent
pip install uv
pip install -e .
ms-agent ui
```

首次启动会通过 uv 准备独立后端环境、安装前端依赖并构建页面和样式，请保持网络连接。待终端显示就绪地址后，即可在浏览器中使用；后续启动会复用有效的构建结果。虚拟环境准备与完整配置步骤见 [WebUI 使用指南](https://github.com/modelscope/ms-agent/blob/main/webui/README_ZH.md)。
