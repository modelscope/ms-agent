---
slug: AgentSkills
title: Agent Skills
description: Ms-Agent Agent Skills Module - A skill discovery, analysis, and execution framework based on the Anthropic Agent Skills protocol.
---

# Agent Skills

The MS-Agent Skill Module is a powerful, extensible skill execution framework that enables LLM agents to automatically discover, analyze, and execute domain-specific skills for complex task completion. It is an implementation of the [Anthropic Agent Skills](https://docs.claude.com/en/docs/agents-and-tools/agent-skills) protocol.

With the Skill Module, agents can handle complex tasks such as:
- "Generate a PDF report for Q4 sales data"
- "Create a presentation about AI trends with charts"
- "Convert this document to PPTX format with custom themes"

## Key Features

- **Intelligent Skill Retrieval**: Hybrid search combining FAISS dense retrieval with BM25 sparse retrieval, plus LLM-based relevance filtering
- **DAG Execution Engine**: Builds execution DAGs based on skill dependencies, supports parallel execution of independent skills, and automatically passes inputs/outputs between skills
- **Progressive Skill Analysis**: Two-phase analysis (plan first, then load resources), incrementally loads scripts/references/resources on demand, optimizing context window usage
- **Secure Execution Environment**: Supports isolated execution via [ms-enclave](https://github.com/modelscope/ms-enclave) Docker sandboxes, or controlled local execution
- **Self-Reflection & Retry**: LLM-based error analysis, automatic code fixes, and configurable retry attempts
- **Standard Protocol Compatibility**: Fully compatible with the [Anthropic Skills](https://github.com/anthropics/skills) protocol

## Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────┐
│                       LLMAgent                          │
│  ┌───────────────────────────────────────────────────┐  │
│  │                   AutoSkills                      │  │
│  │  ┌──────────┐  ┌──────────┐  ┌────────────────┐  │  │
│  │  │  Loader  │  │ Retriever│  │ SkillAnalyzer  │  │  │
│  │  │          │  │ (Hybrid) │  │ (Progressive)  │  │  │
│  │  └────┬─────┘  └────┬─────┘  └───────┬────────┘  │  │
│  │       │              │                │           │  │
│  │       ▼              ▼                ▼           │  │
│  │  ┌───────────────────────────────────────────────┐│  │
│  │  │                DAGExecutor                    ││  │
│  │  │  ┌────────┐  ┌────────┐  ┌────────┐          ││  │
│  │  │  │Skill 1 │→ │Skill 2 │→ │Skill N │          ││  │
│  │  │  └───┬────┘  └───┬────┘  └───┬────┘          ││  │
│  │  │      └────────────┴──────────┘                ││  │
│  │  │                   ↓                           ││  │
│  │  │         SkillContainer (Execution)            ││  │
│  │  └───────────────────────────────────────────────┘│  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
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
│ Progressive     │ ─── Plan → Load → Execute
│ Execution       │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Result          │ ─── Merge outputs, format response
│ Aggregation     │
└─────────────────┘
```

The skill module implements a multi-level progressive context loading mechanism:

1. **Level 1 (Metadata)**: Loads only skill metadata (name, description) for semantic search
2. **Level 2 (Retrieval)**: Retrieves relevant skills and loads the full SKILL.md
3. **Level 3 (Resources)**: Further loads required reference materials and resource files
4. **Level 4 (Analysis|Planning|Execution)**: Analyzes skill context, autonomously creates plans and task lists, loads required resources and runs related scripts

## Skill Directory Structure

Each skill is a self-contained directory:

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

## Quick Start

### Prerequisites

- Python 3.9+
- Docker (for sandbox execution, optional)
- FAISS (for skill retrieval)

### Installation

```bash
pip install 'ms-agent>=1.4.0'

# Or install from source
git clone https://github.com/modelscope/ms-agent.git
cd ms-agent
pip install -e .
```

### Method 1: Using LLMAgent Configuration

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

### Method 2: Using AutoSkills Directly

```python
import asyncio
from ms_agent.skill import AutoSkills
from ms_agent.llm import LLM
from omegaconf import DictConfig

llm_config = DictConfig({
    'llm': {
        'service': 'openai',
        'model': 'gpt-4',
        'openai_api_key': 'your-api-key',
        'openai_base_url': 'https://api.openai.com/v1'
    }
})
llm = LLM.from_config(llm_config)

auto_skills = AutoSkills(
    skills='/path/to/skills',
    llm=llm,
    work_dir='/path/to/workspace',
    use_sandbox=False,
)

async def main():
    result = await auto_skills.run(
        query='Generate a mock PDF report about AI trends'
    )
    print(f"Result: {result.execution_result}")

asyncio.run(main())
```

**Parameter Reference:**

- `skills`: Skill source, supporting the following formats:
  - Single path or list of paths to local skill directories
  - Single or multiple ModelScope skill repository IDs, e.g. `ms-agent/claude_skills` (see [ModelScope Hub](https://modelscope.cn/models/ms-agent/claude_skills))
  - Format: `owner/skill_name` or `owner/skill_name/subfolder`
  - Single or multiple `SkillSchema` objects
- `work_dir`: Working directory for skill execution outputs
- `use_sandbox`: Whether to use Docker sandbox for execution (default `True`); set to `False` for local execution with security checks
- `auto_execute`: Whether to automatically execute skills (default `True`)

## Configuration

Configure the skill module in `agent.yaml`:

```yaml
skills:
  # Required: Path to skills directory or ModelScope repo ID
  path: /path/to/skills

  # Optional: Whether to enable retriever (auto-detect based on skill count if omitted)
  enable_retrieve:

  # Optional: Retriever arguments
  retrieve_args:
    top_k: 3
    min_score: 0.8

  # Optional: Maximum candidate skills to consider (default: 10)
  max_candidate_skills: 10

  # Optional: Maximum retry attempts (default: 3)
  max_retries: 3

  # Optional: Working directory for outputs
  work_dir: /path/to/workspace

  # Optional: Use Docker sandbox for execution (default: True)
  use_sandbox: false

  # Optional: Auto-execute skills (default: True)
  auto_execute: true
```

For general YAML configuration details, see [Config & Parameters](./Config).

## Core Components

| Component | Description |
|-----------|-------------|
| `AutoSkills` | Main entry point for skill execution, coordinating retrieval, analysis and execution |
| `SkillContainer` | Secure skill execution environment (sandbox or local) |
| `SkillAnalyzer` | Progressive skill analyzer with incremental resource loading |
| `DAGExecutor` | DAG executor with dependency management |
| `SkillLoader` | Skill loading and management |
| `Retriever` | Finds relevant skills using semantic search |
| `SkillSchema` | Skill schema definition |

### AutoSkills

```python
class AutoSkills:
    def __init__(
        self,
        skills: Union[str, List[str], List[SkillSchema]],
        llm: LLM,
        enable_retrieve: Optional[bool] = None,
        retrieve_args: Dict[str, Any] = None,
        max_candidate_skills: int = 10,
        max_retries: int = 3,
        work_dir: Optional[str] = None,
        use_sandbox: bool = True,
    ): ...

    async def run(self, query: str, ...) -> SkillDAGResult:
        """Execute skills for a query."""

    async def get_skill_dag(self, query: str) -> SkillDAGResult:
        """Get skill DAG without executing."""
```

### SkillContainer

```python
class SkillContainer:
    def __init__(
        self,
        workspace_dir: Optional[Path] = None,
        use_sandbox: bool = True,
        timeout: int = 300,
        memory_limit: str = "2g",
        enable_security_check: bool = True,
    ): ...

    async def execute_python_code(self, code: str, ...) -> ExecutionOutput:
        """Execute Python code."""

    async def execute_shell(self, command: str, ...) -> ExecutionOutput:
        """Execute shell command."""
```

### SkillAnalyzer

```python
class SkillAnalyzer:
    def __init__(self, llm: LLM): ...

    def analyze_skill_plan(self, skill: SkillSchema, query: str) -> SkillContext:
        """Phase 1: Analyze skill and create execution plan."""

    def load_skill_resources(self, context: SkillContext) -> SkillContext:
        """Phase 2: Load resources based on plan."""

    def generate_execution_commands(self, context: SkillContext) -> List[Dict]:
        """Phase 3: Generate execution commands."""
```

### DAGExecutor

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
    ): ...

    async def execute(
        self,
        dag: Dict[str, List[str]],
        execution_order: List[Union[str, List[str]]],
        stop_on_failure: bool = True,
        query: str = '',
    ) -> DAGExecutionResult:
        """Execute the skill DAG."""
```

## Usage Examples

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
async def create_presentation():
    auto_skills = AutoSkills(
        skills='/path/to/skills',
        llm=llm,
        work_dir='/tmp/presentation'
    )

    # This query might trigger multiple skills working together:
    # 1. data-analysis skill to process data
    # 2. chart-generator skill to create visualizations
    # 3. pptx skill to create the presentation
    result = await auto_skills.run(
        query='Create a presentation about AI market trends with data visualizations'
    )

    print(f"Execution order: {result.execution_order}")

    for skill_id in result.execution_order:
        if isinstance(skill_id, str):
            context = auto_skills.get_skill_context(skill_id)
            if context and context.plan:
                print(f"{skill_id}: {context.plan.plan_summary}")

asyncio.run(create_presentation())
```

### Example 3: Custom Input Execution

```python
from ms_agent.skill.container import ExecutionInput

async def execute_with_custom_input():
    auto_skills = AutoSkills(
        skills='/path/to/skills',
        llm=llm,
        work_dir='/tmp/custom'
    )

    dag_result = await auto_skills.get_skill_dag(
        query='Convert my document to PDF'
    )

    custom_input = ExecutionInput(
        input_files={'document.md': '/path/to/my/document.md'},
        env_vars={'OUTPUT_FORMAT': 'A4', 'MARGINS': '1in'}
    )

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
- Filesystem isolation (only workspace directory mounted)
- Resource limits (memory, CPU)
- No access to host system
- Automatic installation of skill-declared dependencies

### Local Execution

When `use_sandbox=False`, security is enforced through:
- Pattern-based scanning for dangerous code
- Restricted file system access
- Environment variable sanitization

> Make sure you trust the skill scripts before executing them to avoid potential security risks. For local execution, ensure all required dependencies are installed in your Python environment.

## Creating Custom Skills

1. Create a new subdirectory under your skills path
2. Add a `SKILL.md` file with documentation and instructions
3. Add a `META.yaml` file with metadata
4. Add scripts, references, and resources as needed
5. Test with `AutoSkills.get_skill_dag()` to verify the skill can be retrieved correctly

### Best Practices

- Write clear, comprehensive `SKILL.md` that fully describes the skill's capabilities, usage, and parameters
- Explicitly declare all dependencies in `requirements.txt`
- Keep skills self-contained by packaging all necessary resources within the directory
- Handle errors gracefully in scripts
- Use the `SKILL_OUTPUT_DIR` environment variable to specify output directories

## References

- [Anthropic Agent Skills Documentation](https://docs.claude.com/en/docs/agents-and-tools/agent-skills)
- [Anthropic Skills GitHub Repository](https://github.com/anthropics/skills)
- [MS-Agent Skill Examples](https://modelscope.cn/models/ms-agent/skill_examples)
