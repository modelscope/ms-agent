# Gemini 上下文: `ms-agent` 项目

本文档旨在全面介绍 `ms-agent` 项目的结构、功能以及如何与其进行交互。

## 项目概述

`ms-agent` 是一个轻量级、可扩展的 Python 框架，旨在赋予 AI 智能体自主探索（Autonomous Exploration）的能力。它提供了一套完整的工具和架构，支持从简单的对话代理到能够执行复杂任务、使用外部工具、进行代码生成和深度研究的自主智能体。

**核心特性:**

*   **自主智能体 (Autonomous Agents):** 构建能够推理、规划、管理记忆并执行复杂任务的智能体。
*   **工具使用 (MCP):** 全面支持模型上下文协议 (Model Context Protocol, MCP)，允许智能体与文件系统、搜索引擎等外部工具无缝集成。
*   **检索增强生成 (RAG):** 内置 `rag` 模块，支持基于文档的知识检索和增强。
*   **记忆管理 (Memory):** 提供灵活的记忆管理机制，支持短期和长期记忆。
*   **沙箱环境 (Sandbox):** 提供代码执行的沙箱环境，确保安全性。
*   **专用子项目:** 包含多个针对特定领域的专用智能体项目：
    *   `Agent Skills`: 展示智能体各种核心技能的实现。
    *   `Deep Research`: 用于对复杂主题进行深度研究和报告生成的智能体。
    *   `Doc Research`: 专注于文档深度分析、摘要和问答。
    *   `Code Scratch`: 一个能够自主构建和管理代码项目的智能体。
    *   `Fin Research`: (新增) 专注于金融领域研究的智能体。
    *   `Singularity Cinema`: (新增) 一个多模态或娱乐相关的智能体项目示例。
*   **可扩展架构:** 采用高度模块化设计，核心组件（LLM、工具、回调、配置）均可自定义。

**核心技术:**

*   **编程语言:** Python (>=3.10)
*   **配置管理:** 使用 `OmegaConf` 进行强大的分层配置管理。
*   **大模型集成:** 通过 `modelscope` 和 `openai` 库连接各种 LLM（如 Qwen, GPT-4, Claude 等）。
*   **Web UI:** 集成 `Gradio`，通过 `ms-agent app` 命令快速启动交互式 Web 界面。
*   **关键依赖:** `mcp`, `dotenv`, `json5`, `markdown`, `pillow`, `numpy`, `fastapi` (用于某些服务组件)。

## 构建与运行

### 安装

你可以从 PyPI 或从源代码安装本项目。

**从 PyPI 安装:**

```bash
# 安装基础功能
pip install ms-agent

# 安装“深度研究”功能
pip install 'ms-agent[research]'

# 安装“代码生成”功能
pip install 'ms-agent[code]'
```

**从源代码安装 (用于开发):**

```bash
git clone https://github.com/modelscope/ms-agent.git
cd ms-agent
pip install -e .
```

### 配置

*   **智能体/工作流配置:** 智能体行为由 `.yaml` 文件定义 (例如 `agent.yaml`)。支持分层配置，可覆盖系统提示、工具列表、LLM 参数等。
*   **环境变量:** 使用 `.env` 文件或环境变量配置敏感信息。
    *   `MODELSCOPE_API_KEY`
    *   `OPENAI_API_KEY`
    *   `OPENAI_BASE_URL`
    *   `DASHSCOPE_API_KEY`
    *   `BING_SEARCH_API_KEY` (用于搜索工具)

### 执行

框架提供了一个名为 `ms-agent` 的统一命令行入口。

**1. 命令行运行 (CLI):**

`ms-agent run` 是运行智能体的主要命令。

```bash
# 基础用法
ms-agent run --config projects/code_scratch --query "创建一个贪吃蛇游戏"

# 常用参数
# --config: 配置文件路径或项目目录 (必需)
# --query:  初始用户指令 (可选，若无则进入交互模式)
# --trust_remote_code: 允许加载远程代码 (安全选项)
# --load_cache: 加载之前的缓存状态 (如果支持)
# --verbose: 显示详细日志
```

**2. 启动 Web UI:**

`ms-agent app` 命令用于启动基于 Gradio 的图形界面。

```bash
# 启动特定项目的 Web UI
ms-agent app --app_type doc_research

# 这将在本地启动一个 Web 服务器，通常可以通过 http://127.0.0.1:7860 访问
```

**3. Python 脚本调用:**

```python
import asyncio
from ms_agent import LLMAgent
from ms_agent.config import Config

async def main():
    # 1. 加载配置
    config = Config.from_task('ms_agent/agent/agent.yaml')

    # 2. 实例化智能体
    # 可选：指定 mcp_server_file 连接外部工具
    llm_agent = LLMAgent(config=config)

    # 3. 运行
    await llm_agent.run('分析一下当前的人工智能发展趋势')

if __name__ == '__main__':
    asyncio.run(main())
```

## 开发规范与项目结构

*   **项目结构:**
    *   `ms_agent/`: 核心框架代码
        *   `agent/`: 智能体核心逻辑 (`LLMAgent`, `CodeAgent`)。
        *   `app/`: Web UI 应用实现 (`Gradio` 界面)。
        *   `callbacks/`: 事件回调系统 (Stream处理, 日志记录)。
        *   `cli/`: 命令行入口 (`cli.py`, `run.py`, `app.py`)。
        *   `config/`: 配置加载与管理。
        *   `llm/`: LLM 接口抽象与实现 (OpenAI, DashScope 等)。
        *   `memory/`: 记忆管理模块。
        *   `rag/`: 检索增强生成模块。
        *   `sandbox/`: 代码执行沙箱。
        *   `skill/`: 技能定义与加载。
        *   `tools/`: 内置工具集 (文件操作, 搜索, MCP 客户端)。
        *   `utils/`: 通用工具函数。
        *   `workflow/`: 工作流编排。
    *   `projects/`: 示例与专用项目
        *   `agent_skills/`: 技能演示。
        *   `code_scratch/`: 代码生成智能体。
        *   `deep_research/`: 深度研究智能体。
        *   `doc_research/`: 文档分析智能体。
        *   `fin_research/`: 金融研究智能体。
        *   `singularity_cinema/`: (示例项目)。
    *   `examples/`: 基础用法示例脚本。
    *   `requirements/`: 依赖清单 (`framework.txt`, `research.txt`, `code.txt`)。

*   **核心类:**
    *   `LLMAgent`: 最通用的智能体类，集成了 LLM、工具、记忆和回调。
    *   `Config`: 处理 YAML 配置加载和合并。
    *   `ToolManager`: 管理工具的注册和调用。

*   **注意事项:**
    *   **异步优先:** 框架核心逻辑深度依赖 `asyncio`，开发新组件时请务必使用 `async/await`。
    *   **类型提示:** 代码库广泛使用 Python 类型提示，请保持这一习惯。
