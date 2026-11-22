# Configuration

Configuration selects models, tools, working directories, and execution behavior. Identify your entry point first: interface settings, `Config.from_task()`, and the layered resolver do not follow identical loading paths.

## Two loading paths

| API | Use it for | Behavior |
| --- | --- | --- |
| `Config.from_task()` | CLI, standalone scripts, project configurations | Load a local file, directory, or model-repository task; fill fields and process environment values |
| `ConfigResolver` | WebUI and layered application services | Combine framework/interface defaults, global settings, agent configuration, project patches, and session overrides |

Later resolver layers take precedence. MCP, skills, and plugins also have name- and scope-specific merging; do not assume every list is appended.

```{mermaid}
flowchart TD
  A[Framework defaults] --> B[Optional interface defaults]
  B --> C[Global user settings]
  C --> D[Agent configuration]
  D --> E[Project patch]
  E --> F[Session overrides]
  F --> G[Resolve tools, MCP, skills and plugins]
```

## Minimal configuration

Save as `agent.yaml`, set `MODELSCOPE_API_KEY`, and run `ms-agent run --config agent.yaml --query 'Hello'`.

```yaml
llm:
  service: modelscope
  model: Qwen/Qwen3-235B-A22B-Instruct-2507
generation_config:
  stream: false
callbacks: []
max_chat_round: 1
```

Add only what you need. A `tools.<name>` entry without `mcp: false` may be interpreted as an MCP server; mark built-in tools explicitly. `trust_remote_code` permits loading external Python code. It is not a general sandbox for model-generated code.

## Locations and precedence

- Global settings live in `$MS_AGENT_HOME/settings.json`, under `~/.ms_agent` by default.
- Project patches normally live in `.ms_agent/config.yaml` inside the workspace. The older `.ms-agent` directory remains readable for compatibility.
- `ConfigResolver.resolve(session_overrides=...)` applies session values after the project patch.
- CLI argument overrides and dotenv loading are handled by the entry point. Changing a WebUI default does not necessarily override a standalone YAML.

When debugging, check the working directory, `MS_AGENT_HOME`, configuration file, and entry point before inspecting resolved fields. Remove credentials and sensitive URLs before logging configuration.

## Merge programmatically

```python
from omegaconf import OmegaConf
from ms_agent.config.resolver import ConfigResolver

resolver = ConfigResolver(global_dir='./demo-home', project_root='./demo-project')
config = resolver.resolve(
    agent_config=OmegaConf.create({'max_chat_round': 3}),
    session_overrides={'max_chat_round': 1},
)
assert config.max_chat_round == 1
```

This example uses isolated directories to demonstrate precedence; it does not start a model session. See the [field reference](../development/configuration-reference.md) and [models](models.md).

Implementation: `ms_agent/config/config.py`, `ms_agent/config/resolver.py`, `ms_agent/agent/base.py`.
