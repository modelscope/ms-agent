# Agent Skills

The **MS-Agent Skills** Module is **Beta Implementation** of [Anthropic-Agent-Skills](https://docs.claude.com/en/docs/agents-and-tools/agent-skills) Protocol.

To empower your AI agents with a modular skill framework that supports dynamic skill discovery, progressive context loading, planning, and task execution.

## Overview

The Agent Skills Framework implements a multi-level progressive context loading mechanism that efficiently manages skill discovery and execution:

1. **Level 1 (Metadata)**: Load all skill names and descriptions
2. **Level 2 (Retrieval)**: Retrieve and load SKILL.md when relevant with the query
3. **Level 3 (Resources)**: Load additional files (references, scripts, resources) only when referenced in SKILL.md
4. **Level 4 (Analysis|Planning|Execution)**: Analyze the loaded skill context, plan the execution steps, and run the necessary scripts

This approach minimizes resource consumption while providing comprehensive skill capabilities.


### Core Components

| Component        | Description                                 |
|------------------|---------------------------------------------|
| `AgentSkill`     | Main agent class implementing pipeline      |
| `SkillLoader`    | Loads and manages skill definitions         |
| `Retriever`      | Finds relevant skills using semantic search |
| `SkillContext`   | Builds execution context for skills         |
| `ScriptExecutor` | Safely executes skill scripts               |
| `SkillSchema`    | Schema for skill definitions                |

## Key Features

- 📜 **Standard Skill Protocol**: Fully compatible with the [Anthropic Skills](https://github.com/anthropics/skills) protocol
- 🧠 **Heuristic Context Loading**: Loads only necessary context—such as `References`, `Resources`, and `Scripts` on demand
- 🤖 **Autonomous Execution**: Agents autonomously analyze, plan, and decide which scripts and resources to execute based on skill definitions
- 🔍 **Skill Management**: Supports batch loading of skills and can automatically retrieve and discover relevant skills based on user input
- 🛡️ **Code Execution Environment**: Optional local direct code execution or secure sandboxed execution via [**ms-enclave**](https://github.com/modelscope/ms-enclave), with automatic dependency installation and environment isolation
- 📁 **Multi-file Type Support**: Supports documentation, scripts, and resource files
- 🧩 **Extensible Design**: The skill data structure is modularized, with implementations such as `SkillSchema` and `SkillContext` provided for easy extension and customization


## Installation

### Prerequisites
- Python 3.10+
- ms-agent >= 1.4.0

### Install from PyPI
```bash
pip install ms-agent -U
```

### Install from Source
```bash
git clone git@github.com:modelscope/ms-agent.git
cd ms-agent
pip install -e .
```

### Environment Variables
```bash
export OPENAI_API_KEY="your-api-key"
export OPENAI_BASE_URL="your-base-url"
```

## Quick Start

### Usage

> The following example demonstrates how to create and run agent skill to generate `flow fields particle` using p5.js

```python
import os
from pathlib import Path

from ms_agent.agent import create_agent_skill

_PATH = Path(__file__).parent.resolve()


def main():
    """
    Main function to create and run an agent with skills.
    """
    work_dir: str = str(_PATH / 'temp_workspace')
    # Refer to `https://github.com/modelscope/ms-agent/tree/main/projects/agent_skills/skills`
    skill_id_or_dir: str = str(_PATH / 'skills')
    use_sandbox: bool = True

    ## Configuration for ModelScope API-Inference, or set your own model with OpenAI API compatible format
    ## Free LLM API inference calls for ModelScope users, refer to [ModelScope API-Inference](https://modelscope.cn/docs/model-service/API-Inference/intro)
    model: str = 'Qwen/Qwen3-235B-A22B-Instruct-2507'
    api_key: str = 'xx-xx'  # For ModelScope users, refer to `https://modelscope.cn/my/myaccesstoken` to get your access token
    base_url: str = 'https://api-inference.modelscope.cn/v1/'

    agent = create_agent_skill(
        skills=skill_id_or_dir,
        model=model,
        api_key=os.getenv('OPENAI_API_KEY', api_key),
        base_url=os.getenv('OPENAI_BASE_URL', base_url),
        stream=True,
        # Note: Make sure the `Docker Daemon` is running if use_sandbox=True
        use_sandbox=use_sandbox,
        work_dir=work_dir,
    )

    user_query: str = ('Create generative art using p5.js with seeded randomness, flow fields, and particle systems, '
                       'please fill in the details and provide the complete code based on the templates.')

    response = agent.run(query=user_query)
    print(f'\n\n** Agent skill results: {response}\n')


if __name__ == '__main__':

    main()
```

- skill_id_or_dir: Path to the local skill directory or skill ID from The ModelScope hub.
  - skill_id_or_dir (str): e.g. 'path/to/skill-directory', 'ms-agent/skill_examples', 'ma-agent/skill_examples/pdf' (in the form of `owner/skill_name` or `owner/skill_name/subfolder`)
  - Refer to [AgentSkillExamples](https://modelscope.cn/models/ms-agent/skill_examples) for more details on skill publishing and sharing.


**Result:**

<div align="center">
  <img src="https://github.com/user-attachments/assets/9d5d78bf-c2db-4280-b780-324eab74a41e" alt="FlowFieldParticles" width="750">
  <p><em>Agent-Skills: Flow Field Particles</em></p>
</div>




## Skill Definition

The Agent Skill Architecture:

<img src="static/skill_architecture.png" alt="Skill-Architecture" style="width: 750px; display: block; margin: 0 auto;" />

For more details on skill structure and definitions, refer to:
[Anthropic Agent-Skills](https://docs.claude.com/en/docs/agents-and-tools/agent-skills)

### Directory Structure
```
skill-name/
├── SKILL.md              # Main skill definition           (Required)
├── reference.md          # Detailed reference material     (Optional)
├── LICENSE.txt           # License information             (Optional)
├── resources/            # Additional resources            (Optional)
│   ├── template.xlsx     # Example files
│   └── data.json         # Data files
└── scripts/              # Executable scripts              (Optional)
    ├── main.py           # Main implementation
    └── helper.py         # Helper functions
```

### SKILL.md Format

```markdown
---
name: "Skill Name"
description: "Brief description of the skill"
tags: ["tag1", "tag2", "tag3"]
author: "Author Name"
version: "1.0.0"
dependencies: ["numpy", "pandas"]
---

# Skill Title

Detailed explanation of what the skill does...

## Key Features

- Feature 1
- Feature 2
- Feature 3

## Usage

Instructions on how to use this skill...

## Examples

```

💡 Tips:
 - Fields in the front matter (YAML section) are mandatory, `name` and `description` are required.
 - The body of the SKILL.md should provide comprehensive details about the skill, including features, usage instructions, references, resources, and examples.

<br>

## Skills Generation & Conversion

Although we can construct our own skills by following Anthropic’s Skills standard protocol, the high complexity poses challenges for manual creation.

Therefore, using AI tools to automatically generate skills becomes an excellent alternative.

Here, we recommend **Skill Seekers** (https://github.com/yusufkaraaslan/Skill_Seekers) for automatically building and converting agent skills.
