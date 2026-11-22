---
slug: CodeGenesis
title: Code Genesis
description: Ms-Agent Code Genesis Project for software project generation from natural language
---

# Code Genesis

Code Genesis is an open-source multi-agent framework that generates software projects from natural language requirements. It orchestrates specialized AI agents to autonomously deliver end-to-end project generation with frontend, backend, and database integration.

## Overview

### Features

- **End-to-end project generation**: Automatically generates complete projects with frontend, backend, and database integration from natural language descriptions
- **High-quality code**: LSP diagnostics and dependency resolution help check generated code
- **Topology-aware generation**: Generates code in dependency order to reduce cross-file reference errors
- **Automated deployment**: Deploys to EdgeOne Pages automatically with MCP integration
- **Flexible workflows**: Choose between standard (7-stage) or simple (4-stage) pipelines based on project complexity

### Architecture

Code Genesis provides two configurable workflow modes:

#### Standard Workflow

![Standard Workflow](../../../projects/code_genesis/asset/workflow.jpg)

The standard pipeline has seven stages for complex projects that benefit from explicit design and incremental validation:

```
User Story → Architect → File Design → File Order → Install → Coding → Refine
```

**Pipeline Stages**:
1. **User Story Agent**: Parses user requirements into structured user stories
2. **Architect Agent**: Selects technology stack and defines system architecture
3. **File Design Agent**: Generates physical file structure from architectural blueprint
4. **File Order Agent**: Constructs dependency DAG and topological sort for parallel code generation
5. **Install Agent**: Bootstraps environment and resolves dependencies
6. **Coding Agent**: Synthesizes code with LSP validation, following dependency order
7. **Refine Agent**: Performs runtime validation, bug fixing, and automated deployment

Each agent produces structured intermediate outputs, making the design, code, and validation results easier to inspect.

#### Simple Workflow (Rapid Prototyping)

![Simple Workflow](../../../projects/code_genesis/asset/simple_workflow.jpg)

For lightweight projects or quick iterations, the simple workflow condenses the pipeline into 4 core stages:

```
Orchestrator → Install → Coding → Refine
```

**Streamlined Process**:
1. **Orchestrator Agent**: Unified requirement analysis, architecture design, and file planning
2. **Install Agent**: Dependency resolution and environment setup
3. **Coding Agent**: Direct code generation with integrated file ordering
4. **Refine Agent**: Validation and deployment

#### Workflow Comparison

| Aspect | Standard Workflow | Simple Workflow |
|--------|-------------------|-----------------|
| **Agent Stages** | 7 specialized agents | 4 consolidated agents |
| **Architecture Quality** | Explicit, auditable design | Implicit, monolithic design |
| **Generation Time** | Moderate (thorough planning) | Fast (direct execution) |
| **Use Cases** | Production systems, complex apps | Prototypes, demos, simple tools |

## How to Use

### Installation

Clone the repository and prepare the environment:

```bash
git clone https://github.com/modelscope/ms-agent
cd ms-agent
pip install -r requirements/code.txt
pip install -e .
```

Prepare npm environment, following https://nodejs.org/en/download. If you are using Mac, using Homebrew is recommended: https://formulae.brew.sh/formula/node

Make sure your installation is successful:
```bash
npm --version
```

Make sure the npm installation is successful, or the npm install/build/dev will fail.

### Quick Start

Run the standard workflow:

```bash
PYTHONPATH=. openai_api_key=your-api-key openai_base_url=your-api-url \
python ms_agent/cli/cli.py run \
  --config projects/code_genesis \
  --query 'make a demo website' \
  --trust_remote_code true
```

The code will be output to the `output` folder in the current directory by default.

### Advanced Configuration

#### File Editing and Legacy Configuration

The current SDK uses exact `old_string` / `new_string` replacement in `file_system.edit_file`, without a separate editing model. Some legacy CodeGenesis configuration handlers still inspect `tools.file_system.edit_file_config.api_key` to decide whether to expose the edit tool. This compatibility logic does not mean that setting `diff_model` enables Morph or another editing service. Check `coding.yaml`, `refine.yaml`, and their configuration handlers together when updating an existing workflow.

#### Enable Automated Deployment

Add `edgeone-pages-mcp` under `tools` in `refine.yaml` (as an MCP tool):

```yaml
tools:
  edgeone-pages-mcp:
    mcp: true
    command: "npx"
    args: ["edgeone-pages-mcp"]
    env:
      EDGEONE_PAGES_API_TOKEN: your-edgeone-token
```

Get your `EDGEONE_PAGES_API_TOKEN` from https://pages.edgeone.ai/zh/document/pages-mcp
