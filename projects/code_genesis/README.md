# Code Genesis

An open-source multi-agent framework that generates production-ready software projects from natural language requirements. It can do:

* End-to-end project generation with frontend, backend, and database integration
* High-quality code with LSP validation and dependency resolution
* Topology-aware code generation that eliminates reference errors
* Automated deployment to EdgeOne Pages
* Flexible workflows: standard (7-stage) or simple (4-stage) pipelines

This project needs to be used together with ms-agent.

## Running Commands

1. Clone this repo:

  ```shell
  git clone https://github.com/modelscope/ms-agent
  cd ms-agent
  ```

2. Prepare python environment (python>=3.10) with conda:

  ```shell
  conda create -n code_genesis python==3.11
  conda activate code_genesis
  pip install -r ./requirements.txt
  ```

3. Prepare npm environment, following https://nodejs.org/en/download. If you are using Mac, using Homebrew is recommended: https://formulae.brew.sh/formula/node

Make sure your installation is successful:

```shell
npm --version
```

Make sure the npm installation is successful, or the npm install/build/dev will fail and cause an infinite loop.

4. Run:

```shell
PYTHONPATH=. openai_api_key=your-api-key openai_base_url=your-api-url python ms_agent/cli/cli.py run --config projects/code_genesis --query 'make a demo website' --trust_remote_code true
```

The code will be output to the `output` folder in the current directory by default.

## Configuration for Advanced Features

To enable diff-based editing and automated deployment, configure the following in your YAML files:

### 1. Enable Diff-Based File Editing

Add `edit_file_config` to both [coding.yaml](coding.yaml) and [refine.yaml](refine.yaml):

```yaml
edit_file_config:
  model: morph-v3-fast  # or other compatible models
  api_key: your-api-key
  base_url: https://api.morphllm.com/v1
```

Get your model and API key from https://www.morphllm.com

### 2. Enable Automated Deployment

Add `edgeone-pages-mcp` configuration to [refine.yaml](refine.yaml):

```yaml
mcp_servers:
  edgeone-pages:
    env:
      EDGEONE_PAGES_API_TOKEN: your-edgeone-token
```

Get your `EDGEONE_PAGES_API_TOKEN` from https://pages.edgeone.ai/zh/document/pages-mcp

## Architecture Principles

The workflow is defined in [workflow.yaml](workflow.yaml) and follows a 7-stage pipeline:

**Standard Workflow:**
1. **User Story Agent** - Parses user requirements into structured user stories
2. **Architect Agent** - Selects technology stack and defines system architecture
3. **File Design Agent** - Generates physical file structure from architectural blueprint
4. **File Order Agent** - Constructs dependency DAG and topological sort for parallel code generation
5. **Install Agent** - Bootstraps environment and resolves dependencies
6. **Coding Agent** - Synthesizes code with LSP validation, following dependency order
7. **Refine Agent** - Performs runtime validation, bug fixing, and automated deployment

Each agent produces structured intermediate outputs, ensuring engineering rigor throughout the pipeline.

## Developer Guide

Function of each module:

- **workflow.yaml** - Entry configuration file defining the 7-stage pipeline. You can customize the workflow sequence here
- **user_story.yaml / architect.yaml / file_design.yaml / file_order.yaml / install.yaml / coding.yaml / refine.yaml** - Configuration files for each agent in the workflow
- **workflow/*.py** - Python implementation for each agent's logic

## Human Evaluation

After all writing and compiling is finished, an input will be shown to enable human feedback:

1. Please run both frontend and backend with `npm run dev` to start the website
2. Check website problems and give error feedback from:
   * The backend console
   * The browser console
   * Page errors
3. After the website runs normally, you can adjust the website, add new features, or refactor something
4. If you find the token cost is huge or there's an infinite loop, stop it at any time.
5. Feel free to optimize the code and bring new ideas
