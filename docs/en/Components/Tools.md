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

A basic local file CRUD tool. This tool reads the `output` field in the yaml configuration (defaults to the `output` folder in the current directory), and all CRUD operations are performed based on the directory specified by output as the root directory.

#### create_directory

Create a folder

Parameters:

- path: `str`, the directory to be created, based on the `output` field in the yaml configuration.

#### write_file

Write to a specific file.

Parameters:

- path: `str`, the specific file to write to, directory based on the `output` field in the yaml configuration.
- content: `str`: content to write.

#### read_file

Read file content

Parameters:

- path: `str`, the specific file to read, directory based on the `output` field in the yaml configuration.

#### list_files

List files in a directory

Parameters:

- path: `str`, relative directory based on the `output` in yaml configuration. If empty, lists all files in the root directory.


### MCP Tools

Supports passing external MCP tools, just write the configuration required by the mcp tool into the field, and make sure to configure `mcp: true`.

```yaml
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

Additional tools can be added in tools within yaml. Refer to [Configuration and Parameters](./Config.md#Tool%20Configuration)

### Writing new tools

```python
from ms_agent.llm.utils import Tool
from ms_agent.tools.base import ToolBase


# Can be changed to other names
class CustomTool(ToolBase):
    """A file system operation tool

    TODO: This tool now is a simple implementation, sandbox or mcp TBD.
    """

    def __init__(self, config):
        super(CustomTool, self).__init__(config)
        self.exclude_func(getattr(config.tools, 'custom_tool', None))
        ...

    async def connect(self):
        ...

    async def cleanup(self):
        ...

    async def get_tools(self):
        tools = {
            'custom_tool': [
                Tool(
                    tool_name='foo',
                    server_name='custom_tool',
                    description='foo function',
                    parameters={
                        'type': 'object',
                        'properties': {
                            'path': {
                                'type': 'string',
                                'description': 'This is the only argument needed by foo, it\'s used to ...',
                            }
                        },
                        'required': ['foo_arg1'],
                        'additionalProperties': False
                    }),
                Tool(
                    tool_name='bar',
                    server_name='custom_tool',
                    description='bar function',
                    parameters={
                        'type': 'object',
                        'properties': {
                            'path': {
                                'type': 'string',
                                'description': 'This is the only argument needed by bar, it\'s used to ...',
                            },
                        },
                        'required': ['bar_arg1'],
                        'additionalProperties': False
                    }),
            ]
        }
        return {
            'custom_tool': [
                t for t in tools['custom_tool']
                if t['tool_name'] not in self.exclude_functions
            ]
        }

    async def foo(self, foo_arg1) -> str:
        ...

    async def bar(self, bar_arg1) -> str:
        ...
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
