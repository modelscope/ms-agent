# Storage layout

The workspace holds user artifacts; application home holds global settings and managed state. Source build caches are a third category. Distinguish them before backing up or troubleshooting.

## Directory responsibilities

| Location | Content |
| --- | --- |
| `$MS_AGENT_HOME`, default `~/.ms_agent` | Global settings, skill/MCP configuration, project management, logs |
| `<work_dir>` / `output_dir` | User-selected files and artifacts |
| `<work_dir>/.ms_agent` | Memory, snapshots, indexes, locks, temporary output |
| `$MS_AGENT_HOME/projects/<key>` | SDK sessions grouped by workspace; interfaces can specify finer layouts |
| `webui/backend/.venv` | Source WebUI backend dependencies |
| `webui/frontend/node_modules`, `build` | Frontend dependencies and generated output, not project backups |

Project keys derive from absolute workspace paths. Moving a directory can change default session lookup. Do not infer every WebUI SessionManager record from one directory pattern.

## Resolve paths programmatically

```python
from ms_agent.project.paths import global_home, local_internal_dir, memory_dir

print(global_home())
print(local_internal_dir('./workspace'))
print(memory_dir('./workspace'))
```

These resolve paths without starting a model. Redact personal directories before publishing logs.

## Compatibility and migration

Writes prefer `.ms_agent`; older `.ms-agent`, session, and snapshot locations can remain readable. A new directory existing is not a reason to delete old data indiscriminately.

Stop writes, back up configuration, metadata, conversations, and actual files, and record versions before moving data. Check models, skills/MCP, memory, and sessions after recovery. Active database locks are not ordinary backup data.

## Security

Dotenv, settings, and logs can contain credentials or sensitive tasks. Restrict access and do not publish entire application homes. Confirm build-cache cleanup separately from artifact deletion.

Related: [Projects and sessions](../user-guide/projects-sessions.md), [Deployment](../user-guide/deployment.md). Implementation: `project/paths.py`, `session_manager.py`, `config/resolver.py`.
