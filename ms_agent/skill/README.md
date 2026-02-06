# MS-Agent Skill Module

A powerful, extensible skill execution framework that enables LLM agents to automatically discover, analyze, and execute domain-specific skills for complex task completion.

## Table of Contents

- [Introduction](#introduction)
- [Key Features](#key-features)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [Skill Directory Structure](#skill-directory-structure)
- [Core Components](#core-components)
- [Configuration](#configuration)
- [Examples](#examples)
- [API Reference](#api-reference)
- [Security](#security)
- [Contributing](#contributing)

## Introduction

Modern LLM agents excel at reasoning and conversation but often struggle with specialized tasks like document generation, data visualization, or code execution. The **Skill Module** bridges this gap by:

1. **Skill Discovery**: Using hybrid retrieval (dense + sparse) to find relevant skills from a skill library
2. **Intelligent Planning**: Leveraging LLM to analyze skills, plan execution, and build dependency DAGs
3. **Secure Execution**: Running skills in isolated Docker sandboxes or controlled local environments
4. **Progressive Analysis**: Incrementally loading skill resources to optimize context window usage

This enables agents to handle complex, multi-step tasks like:
- "Generate a PDF report for Q4 sales data"
- "Create a presentation about AI trends with charts"
- "Convert this document to PPTX format with custom themes"

The **MS-Agent Skill Module** is **Implementation** of [Anthropic-Agent-Skills](https://platform.claude.com/docs/en/agents-and-tools/agent-skills) Protocol.

## Key Features

### 🔍 Intelligent Skill Retrieval
- **Hybrid Search**: Combines FAISS dense retrieval with BM25 sparse retrieval
- **LLM-based Filtering**: Uses LLM to filter and validate skill relevance
- **Query Analysis**: Automatically determines if skills are needed for a query

### 📊 DAG-based Execution
- **Dependency Management**: Builds execution DAG based on skill dependencies
- **Parallel Execution**: Runs independent skills concurrently
- **Input/Output Linking**: Automatically passes outputs between dependent skills

### 🧠 Progressive Skill Analysis
- **Two-phase Analysis**: Plan first, then load resources
- **Incremental Loading**: Only loads required scripts/references/resources
- **Context Optimization**: Minimizes token usage while maximizing understanding
- **Auto Bug Fixing**: Analyzes errors and attempts automatic fixes

### 🔒 Secure Execution Environment
- **Docker Sandbox**: Isolated execution using [ms-enclave](https://github.com/modelscope/ms-enclave) containers
- **Local Execution**: Controlled local execution with RCE prevention
- **Security Checks**: Pattern-based detection of dangerous code

### 🔄 Self-Reflection & Retry
- **Error Analysis**: LLM-based analysis of execution failures
- **Auto-Fix**: Attempts to fix code based on error messages
- **Configurable Retries**: Up to N retry attempts with fixes

## Installation

### Prerequisites

- Python 3.9+
- Docker (for sandbox execution)
- FAISS (for skill retrieval)

### Install from source

```bash
# Clone the repository
git clone https://github.com/modelscope/ms-agent.git
cd ms-agent

# Install dependencies
pip install -e .

# Install skill-specific requirements
pip install -r requirements/framework.txt
```

### Docker Setup (Optional, for sandbox execution)

```text
# Install docker daemon
# Run the daemon service
```

## Quick Start

### Basic Usage with LLMAgent

```python
import asyncio
from omegaconf import DictConfig
from ms_agent.agent import LLMAgent

config = DictConfig({
    'llm': {
        'service': 'openai',
        'model': 'gpt-4',
        'openai_api_key': 'your-api-key',
        'openai_base_url': 'https://api.openai.com/v1'
    },
    'skills': {
        'path': '/path/to/skills',
        'auto_execute': True,
        'work_dir': '/path/to/workspace',
        'use_sandbox': False,
    }
})

agent = LLMAgent(config, tag='skill-agent')

async def main():
    result = await agent.run('Generate a mock PDF report about AI trends')
    print(result)

asyncio.run(main())
```

- Arguments explanation:
  - `skills.path`: Directory containing skill definitions
    - Single path or list of paths to skill directories
    - Single repo_id or list of repo_ids from ModelScope. e.g. skills='ms-agent/claude_skills', refer to `https://modelscope.cn/models/ms-agent/claude_skills`
  - `skills.auto_execute`: Whether to automatically execute skills
  - `skills.work_dir`: Workspace for skill execution outputs
  - `skills.use_sandbox`: Whether to use Docker sandbox for execution, default is True; set to False for local execution with security checks.



### Direct AutoSkills Usage

```python
import asyncio
from ms_agent.skill import AutoSkills
from ms_agent.llm import LLM
from omegaconf import DictConfig

# Initialize LLM
llm_config = DictConfig({
    'llm': {
        'service': 'openai',
        'model': 'gpt-4',
        'openai_api_key': 'your-api-key',
        'openai_base_url': 'https://api.openai.com/v1'
    }
})
llm = LLM.from_config(llm_config)

# Initialize AutoSkills
auto_skills = AutoSkills(
    skills='/path/to/skills',
    llm=llm,
    work_dir='/path/to/workspace',
    use_sandbox=False,
)

async def main():
    # Execute skills
    result = await auto_skills.run(
        query='Generate a mock PDF report about AI trends'
    )

    print(f">>final result: {result.execution_result}")

asyncio.run(main())
```

- Arguments explanation:
  - `skills`: Path to skill directory or list of skill directories
    - Single path or list of paths to skill directories
    - Single repo_id or list of repo_ids from ModelScope. e.g. skills='ms-agent/claude_skills', refer to `https://modelscope.cn/models/ms-agent/claude_skills`
    - Single SkillSchema or list of SkillSchema objects, refer to `ms_agent.skill.schema.SkillSchema`
  - `llm`: LLM instance for planning and analysis
  - `work_dir`: Workspace for skill execution outputs
  - `use_sandbox`: Whether to use Docker sandbox for execution, default is True; set to False for local execution with security checks.


## Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                          LLMAgent                               │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                      AutoSkills                             ││
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  ││
│  │  │   Loader    │  │  Retriever  │  │    SkillAnalyzer    │  ││
│  │  │             │  │  (Hybrid)   │  │   (Progressive)     │  ││
│  │  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘  ││
│  │         │                │                     │            ││
│  │         ▼                ▼                     ▼            ││
│  │  ┌─────────────────────────────────────────────────────────┐││
│  │  │                    DAGExecutor                          │││
│  │  │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌───────────┐   │││
│  │  │  │ Skill 1 │→ │ Skill 2 │→ │ Skill 3 │→ │ Skill N   │   │││
│  │  │  └────┬────┘  └────┬────┘  └────┬────┘  └─────┬─────┘   │││
│  │  │       └────────────┴───────────┴──────────────┘         │││
│  │  │                        ↓                                │││
│  │  │              SkillContainer (Execution)                 │││
│  │  └─────────────────────────────────────────────────────────┘││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

### Execution Flow

```
User Query
    │
    ▼
┌─────────────────┐
│ Query Analysis  │ ─── Is this a skill-related query?
└────────┬────────┘
         │ Yes
         ▼
┌─────────────────┐
│ Skill Retrieval │ ─── Hybrid search (FAISS + BM25)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Skill Filtering │ ─── LLM-based relevance filtering
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  DAG Building   │ ─── Build dependency graph
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Progressive     │ ─── Plan → Load → Execute for each skill
│ Execution       │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Result          │ ─── Merge outputs, format response
│ Aggregation     │
└─────────────────┘
```

## Skill Directory Structure

Each skill is a self-contained directory with the following structure:

```
skill-name/
├── SKILL.md           # Required: Main documentation and instructions
├── META.yaml          # Optional: Metadata (name, description, version, tags)
├── scripts/           # Optional: Executable scripts
│   ├── main.py
│   ├── utils.py
│   └── run.sh
├── references/        # Optional: Reference documents
│   ├── api_docs.md
│   └── examples.json
├── resources/         # Optional: Assets and resources
│   ├── template.html
│   ├── fonts/
│   └── images/
└── requirements.txt   # Optional: Python dependencies
```

### SKILL.md Format

```markdown
# Skill Name

Brief description of what this skill does.

## Capabilities

- Capability 1
- Capability 2

## Usage

Instructions for using this skill...

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| input     | str  | Input data  |
| format    | str  | Output format |

## Examples

Example usage scenarios...
```

### META.yaml Format

```yaml
name: "PDF Generator"
description: "Generates professional PDF documents from markdown or data"
version: "1.0.0"
author: "Your Name"
tags:
  - document
  - pdf
  - report
```

## Core Components

### AutoSkills

The main entry point for skill-based task execution.

```python
class AutoSkills:
    def __init__(
        self,
        skills: Union[str, List[str], List[SkillSchema]],
        llm: LLM,
        enable_retrieve: Optional[bool] = None,  # Auto-detect based on skill count
        retrieve_args: Dict[str, Any] = None,    # {top_k: 3, min_score: 0.8}
        max_candidate_skills: int = 10,
        max_retries: int = 3,
        work_dir: Optional[str] = None,
        use_sandbox: bool = True,
    ):
        ...

    async def run(self, query: str, ...) -> SkillDAGResult:
        """Execute skills for a query."""
        ...

    async def get_skill_dag(self, query: str) -> SkillDAGResult:
        """Get skill DAG without executing."""
        ...
```

### SkillContainer

Secure execution environment for skills.

```python
class SkillContainer:
    def __init__(
        self,
        workspace_dir: Optional[Path] = None,
        use_sandbox: bool = True,
        timeout: int = 300,
        memory_limit: str = "2g",
        enable_security_check: bool = True,
    ):
        ...

    async def execute_python_code(self, code: str, ...) -> ExecutionOutput:
        """Execute Python code."""
        ...

    async def execute_shell(self, command: str, ...) -> ExecutionOutput:
        """Execute shell command."""
        ...
```

### SkillAnalyzer

Progressive skill analysis with incremental resource loading.

```python
class SkillAnalyzer:
    def __init__(self, llm: LLM):
        ...

    def analyze_skill_plan(
        self,
        skill: SkillSchema,
        query: str
    ) -> SkillContext:
        """Phase 1: Analyze skill and create execution plan."""
        ...

    def load_skill_resources(self, context: SkillContext) -> SkillContext:
        """Phase 2: Load resources based on plan."""
        ...

    def generate_execution_commands(
        self,
        context: SkillContext
    ) -> List[Dict[str, Any]]:
        """Phase 3: Generate execution commands."""
        ...
```

### DAGExecutor

Executes skill DAG with dependency management.

```python
class DAGExecutor:
    def __init__(
        self,
        container: SkillContainer,
        skills: Dict[str, SkillSchema],
        llm: LLM = None,
        enable_progressive_analysis: bool = True,
        enable_self_reflection: bool = True,
        max_retries: int = 3,
    ):
        ...

    async def execute(
        self,
        dag: Dict[str, List[str]],
        execution_order: List[Union[str, List[str]]],
        stop_on_failure: bool = True,
        query: str = '',
    ) -> DAGExecutionResult:
        """Execute the skill DAG."""
        ...
```

## Configuration

### LLMAgent Skills Configuration

```python
config = DictConfig({
    'skills': {
        # Required: Path to skills directory
        'path': '/path/to/skills',

        # Optional: Whether to use retriever (auto-detect if None)
        'enable_retrieve': None,

        # Optional: Retriever arguments
        'retrieve_args': {
            'top_k': 3,
            'min_score': 0.8
        },

        # Optional: Maximum candidate skills to consider
        'max_candidate_skills': 10,

        # Optional: Maximum retry attempts
        'max_retries': 3,

        # Optional: Working directory for outputs
        'work_dir': '/path/to/workspace',

        # Optional: Use Docker sandbox (default: True)
        'use_sandbox': False,

        # Optional: Auto-execute skills (default: True)
        'auto_execute': True,
    }
})
```

## Examples

### Example 1: PDF Report Generation

```python
import asyncio
from ms_agent.skill import AutoSkills
from ms_agent.llm import LLM

async def generate_pdf_report():
    llm = LLM.from_config(config)
    auto_skills = AutoSkills(
        skills='/path/to/skills',
        llm=llm,
        work_dir='/tmp/reports'
    )

    result = await auto_skills.run(
        query='Generate a PDF report analyzing Q4 2024 sales data with charts'
    )

    if result.execution_result and result.execution_result.success:
        for skill_id, skill_result in result.execution_result.results.items():
            if skill_result.output.output_files:
                print(f"Generated files: {skill_result.output.output_files}")

asyncio.run(generate_pdf_report())
```

### Example 2: Multi-Skill Pipeline

```python
async def create_presentation_with_charts():
    auto_skills = AutoSkills(
        skills='/path/to/skills',
        llm=llm,
        work_dir='/tmp/presentation'
    )

    # This query might use multiple skills:
    # 1. data-analysis skill to process data
    # 2. chart-generator skill to create visualizations
    # 3. pptx skill to create the presentation
    result = await auto_skills.run(
        query='Create a presentation about AI market trends with data visualizations'
    )

    # Check execution order
    print(f"Execution order: {result.execution_order}")
    # e.g., ['data-analysis@latest', 'chart-generator@latest', 'pptx@latest']

    # Access individual skill contexts
    for skill_id in result.execution_order:
        if isinstance(skill_id, str):
            context = auto_skills.get_skill_context(skill_id)
            if context and context.plan:
                print(f"{skill_id}: {context.plan.plan_summary}")

asyncio.run(create_presentation_with_charts())
```

### Example 3: Custom Skill Execution with Input

```python
from ms_agent.skill.container import ExecutionInput

async def execute_with_custom_input():
    auto_skills = AutoSkills(
        skills='/path/to/skills',
        llm=llm,
        work_dir='/tmp/custom'
    )

    # Get DAG first
    dag_result = await auto_skills.get_skill_dag(
        query='Convert my document to PDF'
    )

    # Provide custom input for execution
    custom_input = ExecutionInput(
        input_files={
            'document.md': '/path/to/my/document.md'
        },
        env_vars={
            'OUTPUT_FORMAT': 'A4',
            'MARGINS': '1in'
        }
    )

    # Execute with custom input
    exec_result = await auto_skills.execute_dag(
        dag_result=dag_result,
        execution_input=custom_input,
        query='Convert my document to PDF'
    )

    print(f"Success: {exec_result.success}")

asyncio.run(execute_with_custom_input())
```


## Security

### Sandbox Execution (Recommended)

When `use_sandbox=True`, skills run in isolated Docker containers with:
- Network isolation (configurable)
- Filesystem isolation (only workspace mounted)
- Resource limits (memory, CPU)
- No access to host system

### Local Execution Security

When `use_sandbox=False`, security is enforced through:
- Pattern-based code scanning for dangerous operations
- Restricted file system access
- Environment variable sanitization

### Dangerous Patterns Detected

```python
DANGEROUS_PATTERNS = [
    r'os\.system\s*\(',           # os.system calls
    r'subprocess.*shell\s*=\s*True',  # Shell injection
    r'rm\s+-rf\s+\/',             # Dangerous rm commands
    r'curl\s+.*\|\s*sh',          # Piped execution
    # ... and more
]
```

## Contributing

### Adding a New Skill

1. Create a new directory under your skills path
2. Add `SKILL.md` with documentation and instructions
3. Add `META.yaml` with metadata
4. Add scripts, references, and resources as needed
5. Test with `AutoSkills.get_skill_dag()` to verify retrieval

### Skill Best Practices

1. **Clear Documentation**: Write comprehensive SKILL.md
2. **Explicit Dependencies**: List all requirements in requirements.txt
3. **Self-Contained**: Include all necessary resources
4. **Error Handling**: Handle errors gracefully in scripts
5. **Output Conventions**: Use `SKILL_OUTPUT_DIR` for outputs

## License

This project is licensed under the Apache 2.0 License - see the [LICENSE](../../LICENSE) file for details.
