# Plugins

Plugins install and assemble skills, commands, agent definitions, hooks, MCP, and related resources as a unit. They are not a universal executor for arbitrary third-party code, nor simply another name for a skill.

## Install a trusted local plugin

Inspect its files and scripts, then install it disabled:

```bash
ms-agent plugin install ./my-plugin --disabled
ms-agent plugin list --json
```

Confirm the ID and resources before enabling:

```bash
ms-agent plugin toggle PLUGIN_ID --enable
```

Replace `PLUGIN_ID` with the actual ID. Scope defaults to global; use `--scope project --project-path /path/to/project` for project installations. `--link` links a local source, so edits affect consumers. `--force` replaces an existing managed copy; back it up first.

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

Consult `ms-agent plugin --help` for management commands. Disabling a plugin does not reverse earlier side effects; removing configuration and deleting files have different meanings. Active sessions may retain resources, so refresh/restart as required. Full incremental hot reload is not guaranteed.

Separate current assembly from proposed management UI, signing, and incremental reload in the [Plugins RFC](../development/rfcs/plugins.md).

Next: [Skills](skills.md), [Hooks](hooks.md), [MCP](mcp-client.md). Implementation: `plugins/installer.py`, `config_manager.py`, `registry.py`, `runtime.py`.
