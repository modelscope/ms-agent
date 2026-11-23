# Plugins

Plugins install and assemble skills, commands, agent definitions, hooks, MCP, and related resources as a unit. They are not a universal executor for arbitrary third-party code, nor simply another name for a skill.

## Create a local plugin from scratch

Use an environment with MS-Agent installed. Each management command selects an isolated `MS_AGENT_HOME` and test project path, avoiding everyday project plugins and leaving existing global plugins unchanged.

```bash
DEMO="$(mktemp -d)"
mkdir -p "$DEMO/my-plugin/.claude-plugin" "$DEMO/my-plugin/skills/greeting" "$DEMO/project"
```

Create these two files:

```text
my-plugin/
├── .claude-plugin/plugin.json
└── skills/greeting/SKILL.md
```

`$DEMO/my-plugin/.claude-plugin/plugin.json`:

```json
{"name":"docs-demo","version":"0.1.0","description":"A harmless greeting skill."}
```

`$DEMO/my-plugin/skills/greeting/SKILL.md`:

```markdown
---
name: docs-greeting
description: Greet the user without tools or external services.
---
# Greeting
Reply with: Hello from docs-demo.
Do not run tools, access files, or contact external services.
```

This is a supported Claude-format manifest. `name` supplies the plugin ID, `version` records its version, and the loader discovers resources under `skills/`. A manifest with no loadable resources is not a valid plugin. Inspect every file, especially scripts and MCP settings in third-party packages.

## Install disabled, enable, and verify discovery

```bash
MS_AGENT_HOME="$DEMO/home" ms-agent plugin install "$DEMO/my-plugin" --disabled --project-path "$DEMO/project"
MS_AGENT_HOME="$DEMO/home" ms-agent plugin list --json --project-path "$DEMO/project"
```

Expected: ID `docs-demo`, `enabled: false`, status `disabled`. Installation copies and registers resources; it does not execute the skill.

Save this offline checker as `$DEMO/verify_plugin.py`. It creates a new plugin runtime, attaches resources to the skill catalog, and reads the skill body without model calls, tools, or external services.

```python
import os
from pathlib import Path
import sys
from omegaconf import OmegaConf
from ms_agent.plugins.runtime import PluginRuntime
from ms_agent.skill.catalog import SkillCatalog

config = OmegaConf.create({'skills': {'sources': [], 'auto_discover': False}})
runtime = PluginRuntime(global_root=Path(os.environ['MS_AGENT_HOME']))
runtime.start_sync(sys.argv[1], 'docs-demo-check', config=config)
catalog = SkillCatalog(config=config.skills)
catalog.load_from_config(config.skills)
found = [skill for skill in catalog.get_enabled_skills().values()
         if skill.name == 'docs-greeting']
assert bool(found) == (sys.argv[2] == 'enabled')
if found:
    assert 'Hello from docs-demo.' in found[0].content
    print('docs-greeting discovered with its full content')
else:
    print('docs-greeting not loaded')
```

```bash
MS_AGENT_HOME="$DEMO/home" python "$DEMO/verify_plugin.py" "$DEMO/project" disabled
MS_AGENT_HOME="$DEMO/home" ms-agent plugin toggle docs-demo --enable --project-path "$DEMO/project"
MS_AGENT_HOME="$DEMO/home" ms-agent plugin list --json --project-path "$DEMO/project"
MS_AGENT_HOME="$DEMO/home" python "$DEMO/verify_plugin.py" "$DEMO/project" enabled
```

Expected: `not loaded` before enabling. After enabling, the list reports `enabled: true`; the checker discovers `docs-greeting` with its full content and exits 0. New Agents can use the skill, while model selection still depends on the task and skill policy.

The default scope is global (the isolated `$DEMO/home` here). Project installation uses `--scope project --project-path ...`; keep that scope for later management. `--link` links a local source, so changes affect later loading. `--force` replaces managed copies; back up first.

## Disable and clean up

```bash
MS_AGENT_HOME="$DEMO/home" ms-agent plugin toggle docs-demo --disable --project-path "$DEMO/project"
MS_AGENT_HOME="$DEMO/home" python "$DEMO/verify_plugin.py" "$DEMO/project" disabled
MS_AGENT_HOME="$DEMO/home" ms-agent plugin uninstall docs-demo --purge --project-path "$DEMO/project"
MS_AGENT_HOME="$DEMO/home" ms-agent plugin list --json --project-path "$DEMO/project"
```

Expected: a new runtime no longer discovers the disabled skill; the list is empty after uninstalling. `--purge` removes only the managed `docs-demo` copy in this isolated home. The source and `$DEMO/project` remain. After stopping processes, remove only this example's `$DEMO`, not real projects or global homes.

## Resource assembly

```{mermaid}
flowchart TD
 A[Installation source] --> B[Managed files and configuration]
 B --> C[Select enabled plugins by scope]
 C --> D[Parse resources]
 D --> E[Skills / commands / agents / hooks / MCP]
 E --> F[Attach to SDK runtime]
```

Assembly and execution are separate. Declaring hooks does not implement every executor type. Runtime carries hook source context; global, project, and session overrides must be interpreted by their scope.

## Update and remove

Consult `ms-agent plugin --help` for management commands. Disabling a plugin does not reverse earlier side effects; removing configuration and deleting files have different meanings. CLI management does not refresh runtimes already created in another process. Start a new session/instance after enabling, disabling, or updating, or have the host explicitly reload its runtime and recheck discovery.

Separate current assembly from proposed management UI, signing, and incremental reload in the [Plugins RFC](../development/rfcs/plugins.md).

Next: [Skills](skills.md), [Hooks](hooks.md), [MCP](mcp-client.md). Implementation: `plugins/installer.py`, `config_manager.py`, `registry.py`, `runtime.py`.
