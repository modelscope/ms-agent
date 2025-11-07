# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

MS-Agent 是一个轻量级的智能体框架，专门用于赋能智能体自主探索能力。该项目采用模块化设计，支持多种AI应用场景，包括通用对话、深度研究、代码生成等。

## 常用开发命令

### 构建和打包
```bash
# 构建文档
make docs

# 构建wheel包
make whl

# 清理构建文件
make clean

# 同时构建文档和wheel包
make default
```

### 安装和设置
```bash
# 从源码安装（开发模式）
pip install -e .

# 安装基础功能
pip install ms-agent

# 安装包含研究功能的完整版本
pip install 'ms-agent[research]'

# 安装所有功能
pip install 'ms-agent[all]'
```

### 运行和测试
```bash
# 运行CLI
ms-agent --help

# 运行特定项目配置
PYTHONPATH=. python ms_agent/cli/cli.py run --config projects/deep_research --query "your query"

# 运行代码生成项目
PYTHONPATH=. openai_api_key=your-api-key openai_base_url=your-api-url python ms_agent/cli/cli.py run --config projects/code_scratch --query 'Build a comprehensive AI workspace homepage' --trust_remote_code true
```

### 环境变量配置
```bash
# ModelScope API密钥（必需）
export MODELSCOPE_API_KEY={your_modelscope_api_key}

# OpenAI API配置（用于某些功能）
export OPENAI_API_KEY={your_openai_api_key}
export OPENAI_BASE_URL={your_openai_base_url}

# DashScope API密钥（用于Memory功能）
export DASHSCOPE_API_KEY={your_dashscope_api_key}
```

## 核心架构

### 主要目录结构
- `ms_agent/` - 核心框架代码
  - `agent/` - 智能体核心实现
  - `cli/` - 命令行接口
  - `llm/` - 大语言模型集成
  - `tools/` - 工具集（代码、文档、搜索等）
  - `skill/` - 技能系统（Anthropic Agent Skills实现）
  - `memory/` - 记忆系统
  - `workflow/` - 工作流实现

- `projects/` - 项目模块
  - `agent_skills/` - 智能体技能系统
  - `deep_research/` - 深度研究框架
  - `doc_research/` - 文档研究框架
  - `code_scratch/` - 代码生成框架
  - `video_generate/` - 视频生成框架

- `tests/` - 测试文件
- `docs/` - 文档源码
- `examples/` - 示例配置和代码

### 技术栈
- **Python**: 3.8-3.12
- **主要依赖**: ModelScope, OpenAI API, OmegaConf, AsyncIO
- **协议支持**: MCP (Model Context Protocol), Anthropic Agent Skills
- **文档**: Sphinx + Google Style Docstring

## 核心功能模块

### 1. Agent Chat (MCP支持)
- 基于MCP协议的智能体对话
- 支持工具调用和异步处理
- 配置文件: `ms_agent/agent/agent.yaml`

### 2. Agent Skills (Anthropic协议)
- 完整实现Anthropic Agent Skills协议
- 支持技能自主发现和执行
- 位置: `projects/agent_skills/`

### 3. Deep Research
- 自主研究和报告生成
- 多模态处理能力
- 位置: `projects/deep_research/`

### 4. Doc Research
- 文档分析和研究
- 支持多种输出格式
- 位置: `projects/doc_research/`

### 5. Code Scratch
- 复杂代码项目生成
- 三阶段架构（设计、编码、优化）
- 位置: `projects/code_scratch/`

## 配置管理

### 配置文件位置
- 智能体配置: `ms_agent/agent/agent.yaml`
- MCP服务器配置: `examples/agent/mcp.json`
- 项目配置: 各项目目录下的配置文件

### 依赖管理
- 核心依赖: `requirements/framework.txt`
- 研究功能: `requirements/research.txt`
- 代码生成: `requirements/code.txt`
- 文档构建: `requirements/docs.txt`

## 开发注意事项

### 代码规范
- 使用中文注释和文档
- 遵循Google Style Docstring
- 异步编程使用asyncio

### 测试
- 主要测试工具功能和搜索功能
- CI/CD通过GitHub Actions自动化
- 测试配置: `.github/workflows/citest.yaml`

### 记忆功能
- 使用mem0ai实现长期和短期记忆
- 需要额外的DashScope API密钥用于嵌入

### 沙箱执行
- 支持本地直接执行和沙箱安全执行
- 可选集成ms-enclave进行环境隔离

## 文档和资源

### 在线文档
- 英文文档: https://ms-agent-en.readthedocs.io
- 中文文档: https://ms-agent.readthedocs.io/zh-cn
- MCP Playground: https://modelscope.cn/mcp/playground

### 关键示例
- Agent Chat示例: 查看README中的"Agent Chat"部分
- Agent Skills示例: `projects/agent_skills/run.py`
- Deep Research示例: `projects/deep_research/run.py`

## 版本信息

当前版本: 2.0.0 (在 `ms_agent/version.py` 中定义)

## 许可证

Apache License 2.0
