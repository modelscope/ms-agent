# Prompt assembly

A system prompt is more than a role description. MS-Agent assembles base behavior, user/project instructions, runtime capabilities, and skill summaries as separate layers that can be configured and refreshed independently.

## System and task input

`prompt.system` supplies the base system prompt. `prompt.query` supplies an initial task. Setting a system prompt does not start a task or automatically remove user and project instruction layers.

```yaml
prompt:
  system: >-
    You organize research material. Explain the evidence and flag uncertainty.
  query: Summarize the goal of the current task.
personalization:
  enabled: true
```

An explicit system prompt replaces the base layer, not the entire assembled result. A self-contained application should also review personalization, skills, and other extensions.

## Assembly and refresh

```{mermaid}
flowchart TD
 A[Base system prompt] --> E[System content builder]
 B[SOUL / AGENTS / PROFILE] --> E
 C[Runtime and tool instructions] --> E
 D[Skill summaries] --> E
 E --> F[Compare and refresh content]
 F --> G[Current model input]
```

File content is cached and subject to injection limits. Frontmatter and HTML comments may be stripped; a nonempty file is not necessarily transmitted byte for byte.

`skills.update_notice` stabilizes only the skill-summary section and reports skill changes in later messages. It does not freeze SOUL, AGENTS, PROFILE, or the whole system prompt, and it does not guarantee provider cache hits.

## Write useful instructions

Put reusable conventions in personalization/project files and the current task in user input. Explain goals, constraints, and verification steps instead of pasting long logs. History and retrievable material have their own storage.

Model changes, skill synchronization, and file edits can change effective prompts. Diagnose sources and refresh timing rather than one YAML field. Prompts are not authorization boundaries; [permissions](permissions.md) enforce operations.

Next: [Personalization](personalization.md), [Skills](skills.md), [Context](context.md). Implementation: `prompting/`, `LLMAgent._build_system_content()` and refresh logic.
