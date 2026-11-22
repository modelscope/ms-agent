# Personalization and project instructions

Personalization files describe how an agent should work with you; project instructions capture workspace conventions. Neither is a synonym for long-term memory or a complete description of the current task.

## File responsibilities

| File | Useful content |
| --- | --- |
| `SOUL.md` | Assistant behavior and collaboration style |
| `AGENTS.md` | Project structure, conventions, checks, and boundaries |
| `PROFILE.md` | Preferred name, communication preferences, reusable user context |

Global-home and workspace files participate according to resolver rules. Do not assume every same-named file in every ancestor directory is loaded. Template sidecars track framework defaults so template upgrades do not overwrite user-edited content.

## Enable in custom configuration

```yaml
personalization:
  enabled: true
```

The bundled general agent enables personalization; parser defaults and individual interfaces may differ. Disable it explicitly for self-contained tasks. See [Prompt assembly](prompts.md) for how it interacts with the base system prompt.

For example, put these conventions in a project's `AGENTS.md`:

```markdown
# Project conventions

- Explain which files will be affected before changing them.
- Report test results and identify checks that were not run.
- Do not read credential files or write real secrets to logs.
```

These guide the model; they do not replace tool permissions or access controls.

## Update and diagnose

1. Check the active workspace and `MS_AGENT_HOME`.
2. Edit the resolved files directly or through WebUI personalization settings.
3. Save and check visibility in the next turn/session. Model compliance alone is not proof of loading.
4. Check empty content, stripped frontmatter/comments, and size limits when text is missing.

Workspace-file injection is currently capped at 20,000 characters per file. Longer files may be truncated. Keep secrets out of these files because their content may be sent to the model.

Next: [Memory management](../user-guide/memory.md), [Storage](../development/storage.md). Implementation: `personalization/`, `prompting/workspace_files.py`, `prompting/file_resolver.py`.
