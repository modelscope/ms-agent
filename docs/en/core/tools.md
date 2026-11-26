# Tools

Tools turn model intent into named operations with parameters and results. `ToolManager` handles discovery, filtering, authorization, timeouts, and execution. Skill instructions do not replace tool implementations.

## Enable a limited set

```yaml
tools:
  file_system:
    mcp: false
    include: [read_file, glob, grep]
  code_executor:
    mcp: false
    implementation: python_env
    include: [shell_executor]
```

Mark built-ins with `mcp: false`. `include` and `exclude` are mutually exclusive. File operations are `read_file/write_file/edit_file/glob/grep`, not the old create_directory/list_files names. `output_dir` selects the workspace and defaults to the current directory; permission rules still restrict individual paths.

## Capability catalog

| Tool or group | Responsibility |
| --- | --- |
| file_system | Read, precisely edit, search, and match files |
| code_executor | Local shell; sandbox Python, Notebook, and environment operations |
| web_search / localsearch | Web search / on-demand local retrieval |
| todo_list / task_control | Planning and execution control |
| agent_tools / split_task | Subagent delegation and task decomposition |
| cron | Scheduled-task management |
| lsp_code_server | Code indexing and incremental diagnostics |
| image_generator / video_generator / financial_data_fetcher | Generation and financial data |
| image_reader | Auxiliary vision for a text-only main model |
| skills / unified_memory | Tools assembled by skill and memory runtimes |
| ACP / A2A tools | Remote agent calls |

Availability depends on dependencies, configuration, and dynamic assembly. These are not all enabled by default. LSP directory checks currently index files, not a replacement for type checks/tests. Large output may be shortened or spilled to disk; follow returned paths rather than repeatedly calling the tool.

For Context search, set `CONTEXT_DEV_API_KEY` and explicitly configure `tools.web_search.engine: context`. Set `fetch_content: false` for Highlights-only search; enabling content fetching keeps the existing page-fetch pipeline. Managed search settings encrypt its `context_api_key`. Existing defaults do not change.

## Custom tool

Save as `tools/custom_tool.py` beside your configuration:

```python
from ms_agent.llm.utils import Tool
from ms_agent.tools.base import ToolBase

class CustomTool(ToolBase):
    def __init__(self, config):
        super().__init__(config)
        self.exclude_func(getattr(config.tools, 'custom_tool', None))

    async def connect(self):
        pass

    async def _get_tools_inner(self):
        return {'custom_tool': [Tool(
            tool_name='echo', server_name='custom_tool',
            description='Return the supplied text.',
            parameters={'type': 'object',
                        'properties': {'text': {'type': 'string'}},
                        'required': ['text']},
        )]}

    async def call_tool(self, server_name, *, tool_name, tool_args):
        if server_name != 'custom_tool' or tool_name != 'echo':
            raise ValueError('Unknown tool')
        return tool_args['text']
```

Override `_get_tools_inner()`, not `get_tools()`, and load the filtering configuration during initialization. Place this configuration beside the `tools/` directory:

```yaml
tools:
  plugins: [tools/custom_tool]
  custom_tool:
    mcp: false
    include: [echo]
```

`tools.plugins` loads Python tools; it is distinct from the top-level [Plugins](plugins.md) resource system. Use the configuration loader to set `local_dir`. External code requires `--trust_remote_code true`; only trust reviewed sources.

## Execution and failure

Managed calls pass through safety, permission, and hook checks. Calling tool objects directly does not automatically provide the same protection. `tool_call_timeout` defaults to 120 seconds, with a default `tool_call_timeout_max` of 600 seconds. Release owned subprocesses/connections on cancellation. A timeout does not undo completed side effects.

Next: [Execution environments](execution-environments.md), [MCP client](mcp-client.md), [Permissions](permissions.md). Implementation: `tools/base.py`, `tools/tool_manager.py`.
