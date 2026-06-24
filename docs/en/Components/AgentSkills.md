---
slug: AgentSkills
title: Agent Skills
description: MS-Agent Skill Module — a knowledge-driven skill system that extends LLM agents with reusable procedural knowledge through standard tool integration.
---

# Agent Skills

The MS-Agent Skill Module provides a knowledge-driven approach to extending LLM agent capabilities. Instead of building a separate execution pipeline, skills are treated as **procedural knowledge** — they describe *how to do something*, and the model itself executes the steps using its standard tools (code execution, file I/O, web search, etc.).

## Architecture

```
  ┌─────────────┐     ┌──────────────┐     ┌───────────────────┐
  │ Skill Sources│────▶│ SkillCatalog │────▶│PromptInjector     │
  │ local / MS / │     │ load, filter,│     │ always skills:     │
  │ git          │     │ cache        │     │   full body inject │
  └─────────────┘     └──────┬───────┘     │ all skills:        │
                             │             │   name+desc index  │
                             │             └───────────────────┘
                             ▼
                      ┌─────────────┐     ┌──────────────────┐
                      │SkillToolSet │────▶│   ToolManager    │
                      │ skills_list │     │ unified registry │
                      │ skill_view  │     │ (MCP + built-in  │
                      │ skill_manage│     │  + skill tools)  │
                      └─────────────┘     └────────┬─────────┘
                                                   │
                                                   ▼
                                          ┌────────────────┐
                                          │    LLM Agent   │
                                          │    step() loop │
                                          └────────────────┘
```

### How Skills Work

1. **System prompt** includes a lightweight index of all enabled skills (name + description, ~30 tokens each). Skills marked `always: true` have their full body injected.
2. When the model encounters a relevant task, it calls `skill_view(skill_id)` to load the complete instructions.
3. The model follows those instructions using its existing tools (`code_executor`, `web_search`, `file_system`, etc.).
4. All results flow through standard `role: tool` messages — no special routing, no short-circuiting.

### Three-Level Progressive Disclosure

| Level | Content | Cost | Source |
|-------|---------|------|--------|
| L1 | Name + one-line description | ~30 tokens/skill | System prompt (automatic) |
| L2 | Full SKILL.md body | On demand | `skill_view` tool call |
| L3 | Referenced scripts, templates, docs | On demand | `skill_view` with `file_path` |

## Key Features

- **Skill as Knowledge**: Skills guide the model; execution uses existing tools. No separate pipeline, no subprocess isolation needed.
- **Unified Tool Integration**: Skill tools (`skills_list`, `skill_view`, `skill_manage`) are registered through the standard `ToolManager` alongside MCP and built-in tools.
- **Multi-Source Loading**: Load skills from local directories, ModelScope repositories, or Git URLs via `SkillCatalog`.
- **Three-Tier Priority**: Built-in skills < user home skills < workspace skills. Same-name skills at higher tiers override lower ones.
- **Always-Active Skills**: Mark critical skills with `always: true` to inject their full content into the system prompt.
- **Hot Reload**: `SkillCatalog` supports reloading individual skills or full refresh. Changes are immediately visible via tool calls.
- **Runtime Self-Evolution**: When `enable_manage: true`, the model can create, edit, and delete skills during a conversation.
- **Zero Overhead When Disabled**: No `skills:` config → no skill tools registered, no prompt injection, no performance impact.

## Skill Directory Structure

```
my-skill/
├── SKILL.md              # Required: entry point
├── scripts/              # Optional: executable scripts
│   └── search.py
├── references/           # Optional: reference documents
│   └── api-docs.md
├── templates/            # Optional: template files
│   └── report.html
└── assets/               # Optional: static resources
    └── config.yaml
```

### SKILL.md Format

```yaml
---
name: paper-finder                  # required, hyphen-case, ≤64 chars
description: "Search academic papers"  # required, ≤1024 chars
version: "1.0.0"                    # optional
author: "team-name"                 # optional
tags: [research, papers]            # optional, for filtering
always: false                       # optional, true → full body in prompt
requires:                           # optional, dependency declaration
  tools: [web_search, terminal]
  env: [ARXIV_API_KEY]
---

# Paper Finder

## When to Use
Use this skill when asked to find or analyze academic papers.

## Steps
1. Search arXiv using `web_search`
2. Parse results with `code_executor`
3. Summarize findings for the user
```

## Quick Start

### Using LLMAgent

```python
import asyncio
from omegaconf import DictConfig
from ms_agent.agent import LLMAgent

config = DictConfig({
    'llm': {
        'model': 'qwen-max',
        'api_base': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    },
    'tools': {
        'code_executor': {'implementation': 'python_env'},
    },
    'skills': {
        'path': ['./skills'],
        'auto_discover': True,
    },
})

agent = LLMAgent(config, tag='skill-agent')

async def main():
    result = await agent.run('Search for papers on multi-modal RAG')
    print(result[-1].content)

asyncio.run(main())
```

### Programmatic Usage

```python
from ms_agent.skill import SkillCatalog, SkillPromptInjector, SkillToolSet

catalog = SkillCatalog()
catalog.load_from_config(skills_config)

injector = SkillPromptInjector(catalog)
prompt_section = injector.build_skill_prompt_section()

toolset = SkillToolSet(config, catalog, enable_manage=True)
```

## Configuration

```yaml
# agent.yaml
skills:
  # Source paths (local dirs, ModelScope repos, or mixed)
  path:
    - ./skills
    - ms-agent/research_skills

  # Or structured sources
  sources:
    - type: local
      path: ./skills
    - type: modelscope
      repo_id: ms-agent/research_skills
      revision: v1.0

  auto_discover: true       # scan CWD/skills/ automatically
  enable_manage: false       # enable skill_manage tool

  # Filtering (three-value semantics)
  # whitelist: null          # null = all enabled (default)
  # whitelist: []            # [] = all disabled
  # whitelist: [paper-finder]  # specific skills only
  disabled: []               # disable specific skills
```

## Core Components

| Component | Description |
|-----------|-------------|
| `SkillCatalog` | Multi-source skill loader with priority-based override, caching, whitelist/disabled filtering, and hot reload |
| `SkillPromptInjector` | Builds the skill section for system prompt injection (always-skill bodies + summary index) |
| `SkillToolSet` | `ToolBase` subclass providing `skills_list`, `skill_view`, `skill_manage` as registered tools |
| `SkillLoader` | Low-level disk parser for SKILL.md directories (preserved from v1) |
| `SkillSchema` | Data model for a parsed skill (preserved from v1) |

## Comparison with Previous Version (v1)

| Aspect | v1 (AutoSkills pipeline) | v2 (Knowledge + Tools) |
|--------|--------------------------|----------------------|
| Execution | Separate pipeline: LLM analysis → DAG → subprocess | Standard agent loop — model uses tools directly |
| Dispatch | `do_skill()` short-circuits the agent loop | No special branch; skills are standard tools |
| Context | 4-level LLM-driven progressive analysis | 3-level disclosure: prompt → `skill_view` → file |
| Tool coexistence | Skills and MCP tools mutually exclusive | All tools coexist in same loop |
| Streaming | Not supported in skill mode | Naturally supported |
| Dependencies | FAISS, Docker, sentence-transformers | None (pure Python) |
| Removed | `AutoSkills`, `DAGExecutor`, `SkillAnalyzer`, `SkillContainer`, `Spec` | — |
| Added | — | `SkillCatalog`, `SkillPromptInjector`, `SkillToolSet` |

## References

- [Design Document](https://github.com/modelscope/ms-agent/tree/main/ms_agent/skill/README.md)
- [MS-Agent Skill Examples](https://modelscope.cn/models/ms-agent/skill_examples)
