# Agent Skills

A skill packages task instructions with references and scripts loaded when needed. Tools implement operations; skills guide when and how to combine them. Installing a skill does not install every required tool, dependency, or account.

## Structure and discovery

```text
report-helper/
├── SKILL.md
├── references/
└── scripts/
```

```markdown
---
name: report-helper
description: Summarize user-provided material with supporting evidence.
---

Confirm the material's scope, extract evidence, then produce the summary.
```

The directory name determines `skill_id` in MS-Agent; the frontmatter name is not a substitute filesystem ID. Discovery covers built-ins, user/project live trees, and explicit sources. Configuration controls name conflicts and disabled entries.

```yaml
skills:
  sources:
    - type: local
      path: ./skills
  auto_discover: false
  disabled: []
  prompt_injection: all
  update_notice: false
```

`auto_discover` defaults to false but does not disable every live skill tree. Explicit `sources` use structured fields such as type/path. Load external sources only from repositories you trust.

## Progressive loading

```{mermaid}
flowchart TD
 A[Discover skills and metadata] --> B[Filter enabled entries]
 B --> C[Summaries for model selection]
 C --> D[Read SKILL.md for the task]
 D --> E[Read references or invoke scripts as needed]
```

`prompt_injection` accepts `all`, `always_only`, or `none`. `update_notice: true` stabilizes the skill-summary section, not every system-prompt layer. Management and execution depend on enabled tools; instructions alone are not execution evidence.

## Retrieval and safety

Default BM25 retrieval needs no embedding model. Vector/hybrid modes require additional dependencies and models. Scanning, trust policies, and LLM checks are separate controls and do not guarantee safe content. Inspect scripts, destinations, and filesystem scope before using a skill.

`ms-agent-skills` is one capability-gateway skill package, not the collection of all skills or an automatic WebUI installer. See [Capability service](capability-gateway.md).

Next: [Skills and MCP](../user-guide/skills-mcp.md), [Plugins](plugins.md). Implementation: `skill/catalog.py`, `schema.py`, `runtime.py`, `prompt_injector.py`, `config/skills_manager.py`.
