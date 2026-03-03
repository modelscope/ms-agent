---
slug: CodeGenesis
title: Code Genesis
description: Ms-Agent Code Genesis Project for production-ready software project generation from natural language
---

# Code Genesis

Code Genesis is an open-source multi-agent framework that generates production-ready software projects from natural language requirements. It orchestrates specialized AI agents to autonomously deliver end-to-end project generation with frontend, backend, and database integration.

## Overview

### Features

- **End-to-end project generation**: Automatically generates complete projects with frontend, backend, and database integration from natural language descriptions
- **High-quality code**: LSP validation and dependency resolution ensure production-ready output
- **Topology-aware generation**: Eliminates reference errors through dependency-driven code generation
- **Automated deployment**: Deploys to EdgeOne Pages automatically with MCP integration
- **Flexible workflows**: Choose between standard (7-stage) or simple (4-stage) pipelines based on project complexity

### Architecture

Code Genesis provides two configurable workflow modes:

#### Standard Workflow (Production-Grade)

![Standard Workflow](../../../projects/code_genesis/asset/workflow.jpg)

The standard pipeline implements a rigorous 7-stage process optimized for complex, production-ready projects:

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

Each agent produces structured intermediate outputs, ensuring engineering rigor throughout the pipeline.

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

#### Enable Diff-Based File Editing

Add `edit_file_config` to both `coding.yaml` and `refine.yaml`:

```yaml
edit_file_config:
  model: morph-v3-fast  # or other compatible models
  api_key: your-api-key
  base_url: https://api.morphllm.com/v1
```

Get your model and API key from https://www.morphllm.com

#### Enable Automated Deployment

Add `edgeone-pages-mcp` configuration to `refine.yaml`:

```yaml
mcp_servers:
  edgeone-pages:
    env:
      EDGEONE_PAGES_API_TOKEN: your-edgeone-token
```

Get your `EDGEONE_PAGES_API_TOKEN` from https://pages.edgeone.ai/zh/document/pages-mcp
