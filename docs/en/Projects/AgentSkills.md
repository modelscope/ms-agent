---
slug: AgentSkills
title: Agent Skills
description: Ms-Agent Skills implementation of Anthropic Agent Skills Protocol
---

# Agent Skills


## 1. Motivation

- **Evolutionary Needs of General-Purpose Agents**
  - As model capabilities advance, agents can now interact with complete computational environments (e.g., code execution, file systems) to perform complex, cross-domain tasks.
  - More powerful agents require a modular, scalable, and portable means of injecting domain-specific expertise.


- **Skills as Knowledge Encapsulation**
  - Package human procedural knowledge into reusable, composable "skills," eliminating the need to rebuild custom agents for every scenario.
  - Dynamically load skills as structured folders (containing instructions, scripts, and resources), enabling agents to perform superiorly on specific tasks.


- **Adaptability and Flexibility**
  - Building skills is like writing an onboarding manual—lowering the barrier to specialization and enhancing agent flexibility and adaptability.

<br>

For more details about `Agent Skills`, see: [Anthropic Agent Skills](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/overview)

<br>


## 2. What are Agent Skills?


### 1) Agent Skills Architecture

- The Agent Skill Architecture

![Skill-Architecture](../../resources/skill_architecture.png)


- Skill Directory Structure
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

### 2) SKILL.md Format

The `SKILL.md` file uses YAML front matter to define metadata, followed by markdown content for detailed instructions.

![Skill-MD-File](../../resources/skill_md_file.png)

💡 Tips:
 - Fields in the front matter (YAML section) are mandatory, `name` and `description` are required.
 - The body of the SKILL.md should provide comprehensive details about the skill, including features, usage instructions, references, resources, and examples.

[Example of SKILL.md](https://github.com/anthropics/skills/blob/main/document-skills/pdf/SKILL.md)


### 3) Bundling Additional Content


Additional files can be included in the `SKILL.md` to expand skill capabilities, such as:
- Reference materials (e.g. `reference.md` and `forms.md`)

![Skill-Additional-Content](../../resources/skill_additional_content.png)

- Script materials

![Skill-Additional-Scripts](../../resources/skill_additional_scripts.png)


### 4) Skills & Context

- Context Loading & Limitations
  - Skills can load additional context from files in the skill directory, token limitations are recommended.
  - Agents should prioritize loading essential context to ensure efficient execution.

![Skill-Files-Limitation](../../resources/skill_files_limitation.png)

![Skill-Context-Window](../../resources/skill_context_window.png)

<br>


## 3. Implementation

### 1) Overview

The **MS-Agent Skills** Module is **Implementation** of [Anthropic-Agent-Skills](https://docs.claude.com/en/docs/agents-and-tools/agent-skills) Protocol.

The Agent Skills Framework implements a multi-level progressive context loading mechanism that efficiently manages skill discovery and execution:

1. **Level 1 (Metadata)**: Load all skill names and descriptions
2. **Level 2 (Retrieval)**: Retrieve and load SKILL.md when relevant with the query
3. **Level 3 (Resources)**: Load additional files (references, scripts, resources) only when referenced in SKILL.md
4. **Level 4 (Analysis|Planning|Execution)**: Analyze the loaded skill context, plan the execution steps, and run the necessary scripts

This approach minimizes resource consumption while providing comprehensive skill capabilities.


* Core Components

| Component        | Description                                 |
|------------------|---------------------------------------------|
| `AgentSkill`     | Main agent class implementing pipeline      |
| `SkillLoader`    | Loads and manages skill definitions         |
| `Retriever`      | Finds relevant skills using semantic search |
| `SkillContext`   | Builds execution context for skills         |
| `ScriptExecutor` | Safely executes skill scripts               |
| `SkillSchema`    | Schema for skill definitions                |

### 2) Key Features

- 📜 **Standard Skill Protocol**: Fully compatible with the [Anthropic Skills](https://github.com/anthropics/skills) protocol
- 🧠 **Heuristic Context Loading**: Loads only necessary context—such as `References`, `Resources`, and `Scripts` on demand
- 🤖 **Autonomous Execution**: Agents autonomously analyze, plan, and decide which scripts and resources to execute based on skill definitions
- 🔍 **Skill Management**: Supports batch loading of skills and can automatically retrieve and discover relevant skills based on user input
- 🛡️ **Code Execution Environment**: Optional local direct code execution or secure sandboxed execution via [**ms-enclave**](https://github.com/modelscope/ms-enclave), with automatic dependency installation and environment isolation
- 📁 **Multi-file Type Support**: Supports documentation, scripts, and resource files
- 🧩 **Extensible Design**: The skill data structure is modularized, with implementations such as `SkillSchema` and `SkillContext` provided for easy extension and customization


### 3) Installation

* Install from PyPI
```bash
pip install 'ms-agent>=1.4.0'
```

* Install from Source
```bash
git clone git@github.com:modelscope/ms-agent.git
cd ms-agent
pip install -e .
```

* Configuration
```bash
export OPENAI_API_KEY="your-api-key"
export OPENAI_BASE_URL="your-base-url"
```


### 4) Usage

> The following example demonstrates how to create and run agent skill to generate `flow fields particle` using p5.js

```python
import os
from ms_agent.agent import create_agent_skill


def main():
    """
    Main function to create and run an agent with skills.
    """
    work_dir: str = './temp_workspace'
    # Refer to `https://github.com/modelscope/ms-agent/tree/main/projects/agent_skills/skills`
    skill_id_or_dir: str = './skills'
    use_sandbox: bool = True

    ## Configuration for ModelScope API-Inference, or set your own model with OpenAI API compatible format
    ## Free LLM API inference calls for ModelScope users, refer to [ModelScope API-Inference](https://modelscope.cn/docs/model-service/API-Inference/intro)
    model: str = 'Qwen/Qwen3-235B-A22B-Instruct-2507'
    api_key: str = 'xx-xx'  # For ModelScope users, refer to `https://modelscope.cn/my/myaccesstoken` to get your access token
    base_url: str = 'https://api-inference.modelscope.cn/v1/'

    agent = create_agent_skill(
        # Use a skill from ModelScope Hub by its ID. A list of IDs is also supported. e.g. `ms-agent/skill_examples`
        # To use local skills, provide the path to the directory, e.g., skills='./skills'
        # For more details on skill IDs, see: https://modelscope.cn/models/ms-agent/skill_examples
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



* Local Execution
  - If `use_sandbox=False`, the skill scripts are executed directly in the local environment
  - Ensure you trust the skill scripts, to avoid security risks
  - Ensure that the necessary dependencies are installed in your local Python environment

* Sandboxed Execution
  - If `use_sandbox=True`, the skill scripts are executed in an isolated Docker container using [**ms-enclave**](https://github.com/modelscope/ms-enclave)
  - This provides a secure environment, preventing potential harm to the host system
  - Make sure Docker is installed and the Docker Daemon is running on your machine
  - The required dependencies will be automatically installed in the sandbox environment based on the skill requirements

<br>

**Result:**

![Flow Field Particles](../../resources/skill_algorithmic_art_result.gif)


<br>


## References

* Anthropic Agent Skills Documentation：https://docs.claude.com/en/docs/agents-and-tools/agent-skills
* Anthropic Skills GitHub Repo： https://github.com/anthropics/skills

<br>
