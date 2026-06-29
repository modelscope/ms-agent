# MS-Agent Skill Module

A knowledge-driven skill system that extends LLM agents with reusable procedural knowledge — skills guide the model on *what tools to use and in what order*, while execution stays within the agent's standard tool-calling loop.

## Design Philosophy

> **Skill = Knowledge, not Executor.** A skill describes *how to do something*; the model itself decides *when and how to act* using its available tools.

This replaces the previous architecture (LLM analysis → DAG → subprocess execution) with a simpler, more composable design where skills are just another source of context for the model.

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        LLMAgent.run_loop                         │
│                                                                  │
│  ┌── System Prompt ──────────────────────────────────────────┐   │
│  │  ...agent instructions...                                 │   │
│  │                                                           │   │
│  │  # Active Skills          ← always skills: full body      │   │
│  │  ## Greeting Guide                                        │   │
│  │  (full SKILL.md content)                                  │   │
│  │                                                           │   │
│  │  # Available Skills       ← all skills: name + desc index │   │
│  │  - **Greeting Guide** (`greeting-guide`): ...             │   │
│  │  - **Data Viz** (`data-viz`): ...                         │   │
│  │  Use `skill_view(id)` to read full instructions.          │   │
│  └───────────────────────────────────────────────────────────┘   │
│                                                                  │
│  while not should_stop:                                          │
│      tools = [                                                   │
│          ...MCP tools...,                                        │
│          ...built-in tools (code_executor, read_file, etc.)...,  │
│          skills_list(),          ← browse skills                 │
│          skill_view(id),         ← read full skill content       │
│          skill_manage(action),   ← create/edit/delete (optional) │
│      ]                                                           │
│      llm.generate(messages, tools) → tool_calls → results       │
│      ← results feed back as role:tool messages → next step       │
└──────────────────────────────────────────────────────────────────┘
```

### How It Works (Simplified Flow)

```
  ┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
  │ Skill Sources│────▶│ SkillCatalog │────▶│SkillPromptInjector│
  │ local / MS / │     │ load, filter,│     │ inject into      │
  │ git          │     │ cache        │     │ system prompt    │
  └─────────────┘     └──────┬───────┘     └─────────────────┘
                             │
                             ▼
                      ┌─────────────┐     ┌──────────────────┐
                      │SkillToolSet │────▶│   ToolManager    │
                      │ skills_list │     │ unified registry │
                      │ skill_view  │     │ (MCP + built-in  │
                      │ skill_manage│     │  + skill tools)  │
                      └─────────────┘     └──────────────────┘
                                                   │
                                                   ▼
                                          ┌────────────────┐
                                          │  LLM Agent     │
                                          │  step() loop   │
                                          │  (standard     │
                                          │   tool calls)  │
                                          └────────────────┘
```

### Three-Level Progressive Disclosure

| Level | What the model sees | Token cost | How |
|-------|-------------------|------------|-----|
| L1 | Name + one-line description | ~30 tokens/skill | System prompt (auto) |
| L2 | Full SKILL.md body | On demand | `skill_view(id)` tool call |
| L3 | Referenced files, scripts, templates | On demand | `skill_view(id, file_path)` tool call |

## Module Structure

```
ms_agent/skill/
├── __init__.py            # Public API
├── schema.py              # SkillSchema, SkillFile, SkillSchemaParser (preserved)
├── loader.py              # SkillLoader — disk parsing (preserved)
├── sources.py             # SkillSource, SkillSourceType, parse_skill_source
├── catalog.py             # SkillCatalog — multi-source loading, cache, hot-reload
├── prompt_injector.py     # SkillPromptInjector — system prompt injection
├── skill_tools.py         # SkillToolSet — skills_list, skill_view, skill_manage
└── README.md              # This file
```

## Core Components

### SkillCatalog

Unified skill directory with three-tier priority loading:

| Priority | Source | Path |
|----------|--------|------|
| 1 (lowest) | Built-in | `ms_agent/skills/` (package) or `<repo>/skills/` (source) |
| 2 | User home | `~/.ms_agent/skills/{installed,custom}/` |
| 3 (highest) | Workspace / config | `CWD/skills/` or `config.skills.path` |

Later-loaded skills override earlier ones with the same `skill_id`.

### SkillPromptInjector

Builds the skill section appended to the system prompt:
- `always: true` skills → full body injected (frontmatter stripped)
- All enabled skills → name + description summary index

### SkillToolSet

A `ToolBase` subclass registered into `ToolManager`:

| Tool | Purpose |
|------|---------|
| `skills_list` | List available skills with optional tag filter |
| `skill_view` | Read full SKILL.md or a specific file within the skill directory |
| `skill_manage` | Create / edit / delete skills at runtime (optional, gated by `enable_manage`) |

## SKILL.md Format

```yaml
---
name: paper-finder                  # required, ≤64 chars
description: "Search academic papers"  # required, ≤1024 chars
version: "1.0.0"                    # optional
author: "team-name"                 # optional
tags: [research, papers]            # optional
always: false                       # optional, true → inject full body into prompt
requires:                           # optional
  tools: [web_search, terminal]
  env: [ARXIV_API_KEY]
---

# Paper Finder

## When to Use
...

## Steps
1. Use `web_search` to find papers on arXiv
2. Use `code_executor` to parse results
3. Return analysis to user
```

## Configuration

```yaml
# agent.yaml
skills:
  path:
    # Any of these formats work:
    - ./skills                                                 # local directory
    - /absolute/path/to/skills                                 # absolute path
    - ~/my_skills                                              # home-relative
    - BaiduDrive/baidu-drive                                   # ModelScope skill (owner/name)
    - "@MiniMax-AI/minimax-pdf"                                # ModelScope skill (@-prefix)
    - https://modelscope.cn/skills/BaiduDrive/baidu-drive      # ModelScope skill URL
    - modelscope://owner/repo@v1.0#subdir                      # ModelScope URI with revision
    - https://github.com/user/repo.git                         # Git repository

  auto_discover: true                # scan CWD/skills/ automatically
  enable_manage: false               # enable runtime skill CRUD

  # Filtering (three-value semantics)
  # whitelist: null                  # null = all enabled (default)
  # whitelist: []                    # [] = all disabled
  # whitelist: [paper-finder]        # specific skills only
  disabled: []                       # disable list
```

### Installing Skills from ModelScope

ModelScope Skills can be installed in several ways:

```bash
# Via ModelScope CLI (requires modelscope>=1.35.2)
modelscope skills add @BaiduDrive/baidu-drive @MiniMax-AI/minimax-pdf

# Download a collection of skills
modelscope download --collection MiniMax/MiniMax-Office-skills

# Via the install script
curl -fsSL https://modelscope.cn/skills/install.sh | bash -s -- BaiduDrive/baidu-drive
```

Browse available skills at [modelscope.cn/skills](https://modelscope.cn/skills).

## Comparison with Previous Version

| Aspect | v1 (Old) | v2 (Current) |
|--------|----------|--------------|
| Execution model | Separate pipeline: LLM analysis → DAG → subprocess | Standard agent loop — model uses tools directly |
| Skill dispatch | `do_skill()` short-circuits `run_loop` | No special branch; skills are standard tools |
| Context loading | 4-level progressive analysis via LLM calls | 3-level disclosure: prompt index → `skill_view` → file read |
| Tool coexistence | Skills and MCP tools mutually exclusive | Skills and all tools coexist in same loop |
| Result passing | Required special `_format_skill_result_as_messages` | Standard `role: tool` messages |
| Streaming | Not supported in skill mode | Naturally supported |
| Dependencies | FAISS, Docker, sentence-transformers | None (pure Python) |
| Key components removed | `AutoSkills`, `DAGExecutor`, `SkillAnalyzer`, `SkillContainer`, `Spec` | — |
| Key components added | — | `SkillCatalog`, `SkillPromptInjector`, `SkillToolSet` |

## API Reference

```python
from ms_agent.skill import (
    SkillCatalog,          # Multi-source skill manager
    SkillPromptInjector,   # System prompt builder
    SkillToolSet,          # Tool registration
    SkillSource,           # Source descriptor
    SkillSourceType,       # Enum: LOCAL_DIR, MODELSCOPE, GIT
    parse_skill_source,    # String → SkillSource parser
    SkillLoader,           # Low-level disk loader (preserved)
    SkillSchema,           # Skill data model (preserved)
    SkillSchemaParser,     # SKILL.md parser (preserved)
    SkillFile,             # File descriptor (preserved)
)
```

## License

Apache 2.0 — see [LICENSE](../../LICENSE).
