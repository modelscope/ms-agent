---
slug: Tools
title: Tools
description: Ms-Agent Tools
---

# Tools

## Tool List

MS-Agent supports many internal tools:

### split_task

Task splitting tool. LLM can use this tool to split a complex task into several subtasks, each with independent system and query fields. The yaml configuration of subtasks inherits from the parent task by default.

#### split_to_sub_task

Use this method to start multiple subtasks.

Parameters:

- tasks: ``List[Dict[str, str]]``, list length equals the number of subtasks, each subtask contains a Dict with keys system and query

### file_system

A local file read/write tool. By default, paths are confined to `output_dir` (the current working directory, `Path.cwd()`, when unset). With `trust_remote_code` enabled, `allow_read_all_files` can expand read access; calls are also subject to permission rules. It provides 5 methods (`read` / `edit` / `write` are aliases):

#### write_file

Write a file (created if missing; parent directories are created automatically).

Parameters:

- `path`: `str`, the target file path.
- `content`: `str`, the content to write.

#### read_file

Read the content of one or more files.

Parameters:

- `paths`: `list[str]`, the file paths to read; the single-file `path` parameter is also supported.
- `offset` / `limit`: starting line and number of lines for paging.

#### edit_file

Edit a file by exact string replacement.

Parameters:

- `path`: `str`, the target file.
- `old_string`: `str`, the original text to replace (a unique match by default; an empty string creates a file).
- `new_string`: `str`, the replacement content.
- `replace_all`: `bool`, replace all matches; defaults to `false`.

#### grep

Regex search over file contents (ripgrep semantics).

Parameters:

- `pattern`: `str`, the regular expression.
- `path`: `str`, the file or directory to search (optional, defaults to the root).
- `glob`: `str`, filename filter (optional, e.g. `*.py`).
- `output_mode` / `head_limit` / `offset`: output mode and pagination (optional).

#### glob

Find file paths by glob pattern.

Parameters:

- `pattern`: `str` (required), the glob pattern, e.g. `**/*.md`.
- `path`: `str`, the starting directory (optional).

### code_executor

Code execution tool that can run Python code either in a sandboxed environment or directly in the local Python environment. The behavior is controlled by the `tools.code_executor.implementation` field.

- When omitted or set to `sandbox`:
  - Uses an [ms-enclave](https://github.com/modelscope/ms-enclave) based sandbox. The sandbox can be created locally with Docker or via a remote HTTP service.
  - Currently supports two sandbox types: `docker` and `docker_notebook`. The former is suitable for non-interactive/stateless execution; the latter maintains notebook-style state across calls.
  - The configured `output_dir` on the host is mounted into the sandbox at `/data` so code can read and write persistent artifacts there.

- When set to `python_env`:
  - Runs code in the local Python environment. The tool API is aligned with the sandbox version and supports both Jupyter-kernel based execution and plain Python interpreter execution.
  - With `include: [shell_executor]`, no Python/Notebook dependencies are initialized or installed. This is the default WebUI tool scope.
  - Before enabling `python_executor` or `notebook_executor`, prepare their dependencies in the Python environment that runs the SDK. WebUI does not preinstall PyArrow, scikit-learn or seaborn; install them with `pip install pyarrow scikit-learn seaborn`. Notebook execution also needs `pip install ipykernel jupyter-client`. The existing automatic setup attempts to install missing packages at initialization and requires working pip and network access; preinstall them for offline use.

#### notebook_executor

- **Sandbox mode**: Executes code inside a `docker_notebook` sandbox, preserving state (variables, imports, dataframes, etc.) across calls. Files under the mounted data directory are available at `/data/...`, and you can also run simple shell commands from code cells using the standard `!` prefix.
- **Local mode**: Executes code in a local Jupyter kernel, with environment isolation and state persistence across calls. In the notebook environment you can also use simple shell commands via the standard `!` syntax.

**Parameters**:

- **code**: `string` – Python code to execute.
- **description**: `string` – Short description of what the code is doing.
- **timeout**: `integer` – Optional execution timeout in seconds; if omitted, the tool-level default is used.

#### python_executor

- **Sandbox mode**: Executes Python code in a `docker`-type sandbox using the sandbox’s Python interpreter, typically used when you do not need full notebook-style interaction.
- **Local mode**: Executes code with the local Python interpreter in a stateless fashion; each call has its own execution context and does not share variables with previous calls.

**Parameters**:

- **code**: `string` – Python code to execute.
- **description**: `string` – Short description of what the code is doing.
- **timeout**: `integer` – Optional execution timeout in seconds; if omitted, the tool-level default is used.

#### shell_executor

- **Sandbox mode**: Dedicated to `docker`-type sandboxes and executes shell commands inside the sandbox using `bash`, supporting basic operations like `ls`, `cd`, `mkdir`, `rm`, etc., and access to files under `/data`.
- **Local mode**: Executes shell commands using the local `bash` interpreter with the working directory set to `output_dir`; this is convenient for development but generally not recommended for production.

**Parameters**:

- **command**: `string` – Shell command to execute.
- **timeout**: `integer` – Optional execution timeout in seconds; if omitted, the tool-level default is used.

#### file_operation

- **Sandbox mode**: Dedicated to `docker`-type sandboxes and performs basic file operations inside the sandbox (create, read, write, delete, list, exists). Paths are interpreted as sandbox-internal paths; in most cases you should work under `/data/...`.
- **Local mode**: Performs the same basic file operations on the local filesystem but always constrained under `output_dir` to prevent accessing arbitrary locations.

**Parameters**:

- **operation**: `string` – Type of file operation to perform; one of `'create'`, `'read'`, `'write'`, `'delete'`, `'list'`, `'exists'`.
- **file_path**: `string` – File or directory path (sandbox-internal in sandbox mode; relative to or under `output_dir` in local mode).
- **content**: `string` – Optional, content to write when `operation` is `'write'`.
- **encoding**: `string` – Optional file encoding, default `utf-8`.

#### reset_executor

- **Sandbox mode**: Recreates the sandbox (or restarts the notebook kernel) to clear all variables and session state when the environment becomes unstable.
- **Local mode**: Restarts the local Jupyter kernel used by `notebook_executor`, dropping all in-memory state.

#### get_executor_info

- **Sandbox mode**: Returns the current sandbox status and configuration summary (such as memory/CPU limits, available tools, etc.).
- **Local mode**: Returns basic information about the local execution environment (working directory, whether it is initialized, current execution count, uptime, etc.).

### MCP Tools

Supports passing external MCP tools, just write the configuration required by the mcp tool into the field, and make sure to configure `mcp: true`.

```yaml
tools:
  amap-maps:
    mcp: true
    type: sse
    url: https://mcp.api-inference.modelscope.net/xxx/sse
    exclude:
      - map_geo
```

## Custom Tools

### Passing mcp.json

This method can pass an mcp tool list. Has the same effect as configuring the tools field in yaml.

```shell
ms-agent run --config xxx/xxx --mcp_server_file ./mcp.json
```

### Configuring yaml file

Additional tools can be added in tools within yaml. Refer to [Configuration and Parameters](./Config.md) for details.

### Writing new tools

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
        return {
            'custom_tool': [Tool(
                tool_name='echo',
                server_name='custom_tool',
                description='Return the supplied text.',
                parameters={
                    'type': 'object',
                    'properties': {'text': {'type': 'string'}},
                    'required': ['text'],
                    'additionalProperties': False,
                },
            )]
        }

    async def call_tool(self, server_name, *, tool_name, tool_args):
        if server_name != 'custom_tool' or tool_name != 'echo':
            raise ValueError('Unknown tool')
        return tool_args['text']
```

Save the file in a relative directory to `agent.yaml`, such as `tools/custom_tool.py`.

```text
agent.yaml
tools
  |--custom_tool.py
```

Then you can configure it in `agent.yaml` as follows:

```yaml

tools:
  tool1:
    mcp: true
    # Other configurations

  tool2:
    mcp: false
    # Other configurations

  # This is the registered new tool
  plugins:
    - tools/custom_tool
```

We have a [simple example](https://www.modelscope.cn/models/ms-agent/simple_tool_plugin) that you can modify based on this example.
