---
slug: tools
title: 工具
description: Ms-Agent 工具：支持多种内置工具和自定义工具扩展
---

# 工具

## 工具列表

MS-Agent支持很多内部工具：

### split_task

任务拆分工具。LLM可以使用该工具将一个复杂任务拆分为若干个子任务，每个子任务都具有独立的system和query字段。子任务的yaml配置默认继承自父任务。

#### split_to_sub_task

使用该方法开启多个子任务。

参数：

- tasks: ``List[Dict[str, str]]``, 列表长度等于子任务数，每个子任务均包含key为system和query两个字段的Dict

### file_system

本地文件读写工具。默认限制在配置的 `output_dir`（未配置时为当前工作目录 `Path.cwd()`）内。在 `trust_remote_code` 启用时，`allow_read_all_files` 可放宽读取范围；实际调用还受权限规则约束。共提供 5 个方法（`read` / `edit` / `write` 为别名）：

#### write_file

写入文件（不存在则创建，父目录自动创建）。

参数：

- `path`: `str`，目标文件路径。
- `content`: `str`，写入内容。

#### read_file

读取一个或多个文件的内容。

参数：

- `paths`: `list[str]`，待读取的文件路径列表；兼容单文件参数 `path`。
- `offset` / `limit`：读取的起始行和行数，用于分页。

#### edit_file

按字符串精确替换编辑文件。

参数：

- `path`: `str`，目标文件。
- `old_string`: `str`，待替换的原文（默认需唯一匹配；空字符串用于创建文件）。
- `new_string`: `str`，替换后的内容。
- `replace_all`: `bool`，是否替换全部匹配，默认 `false`。

#### grep

在文件内容中做正则搜索（ripgrep 语义）。

参数：

- `pattern`: `str`，正则表达式。
- `path`: `str`，搜索的文件或目录（可选，默认根目录）。
- `glob`: `str`，文件名过滤（可选，如 `*.py`）。
- `output_mode` / `head_limit` / `offset`：输出模式与分页（可选）。

#### glob

按 glob 模式查找文件路径。

参数：

- `pattern`: `str`（必填），glob 模式，如 `**/*.md`。
- `path`: `str`，搜索起始目录（可选）。

### code_executor

代码执行工具，支持基于本地 Python 环境执行代码或基于沙箱环境执行代码。可以在 `tools.code_executor` 下通过配置 `implementation` 字段选择执行环境。

- 默认或 `implementation: sandbox` 启动沙箱模式：
  - 基于沙箱环境运行代码，支持通过本地 Docker 或远程 HTTP 服务建立沙箱运行环境，主要支持 `docker` 和 `docker_notebook` 两种环境类型，分别适合于无状态的代码运行和需要在对话内保持上下文状态的代码运行。
  - 工具基于 [ms-enclave](https://github.com/modelscope/ms-enclave) 实现，依赖于本地可用的 Docker 环境。如果代码执行需要的依赖较多，建议预先构建包含所需依赖的镜像。准备好基础镜像后，需要完善本次启动容器的基础配置，如配置所选择的执行环境类型、可用的工具、容器需要挂载的目录等。
  - 默认会将配置中的 `output_dir` 目录挂载到沙箱内的 `/data`，用于读写持久化文件。

- `implementation: python_env` 时启动本地模式：
  - 基于本地 Python 环境执行代码，在工具设计上与沙箱环境保持一致，支持 Jupyter Notebook 和 Python 解释器两种执行方式，分别适合于需要在对话内保持上下文状态的代码运行和无状态的代码运行。
  - 设置 `include: [shell_executor]` 时，不会初始化或安装 Python/Notebook 工具的依赖。WebUI 默认使用这一工具范围。
  - 启用 `python_executor` 或 `notebook_executor` 前，应在启动 SDK 的 Python 环境中准备所需依赖。WebUI 默认不预装 PyArrow、scikit-learn 和 seaborn，可执行 `pip install pyarrow scikit-learn seaborn` 安装；Notebook 执行另外需要 `pip install ipykernel jupyter-client`。现有逻辑会在初始化时尝试补装缺失的包，这要求该环境有可用的 pip 和网络；离线部署应提前安装。

#### notebook_executor

沙箱模式下，该方法对应 `docker_notebook` 类型沙箱环境，可以在 Notebook 内执行代码并保持对话内的上下文；代码可以访问挂载在 `/data` 下的文件，支持在代码中通过`!`前缀执行简单的shell命令。

本地模式下，该方法基于本地 Jupyter Kernel 执行代码，提供对环境变量的隔离，支持对话内的上下文保持，并支持在代码中通过 `!` 前缀执行简单的 shell 命令。相应依赖会在首次运行时自动安装（包括数据分析和代码执行需要的依赖）。

参数：

- code: `str`, 需要执行的代码。
- description: `str`, 代码工作内容的简要描述。
- timeout: `int`, 可选，执行超时时间（秒），不配置时使用工具默认值。

#### python_executor

沙箱模式下，该方法专用于 `docker` 类型沙箱环境，可以使用沙箱内的 Python 解释器运行代码，适合不需要完整 Notebook 交互能力的执行场景。

本地模式下，该方法基于本地 Python 解释器执行代码，每次调用互相独立，不保留上下文。

参数：

- code: `str`, 需要执行的代码。
- description: `str`, 代码工作内容的简要描述。
- timeout: `int`, 可选，执行超时时间（秒），不配置时使用工具默认值。

#### shell_executor

沙箱模式下，该方法专用于 `docker` 类型沙箱环境，该方法使用 bash 在沙箱内执行 shell 命令，支持基本的 shell 操作例如 `ls`、`cd`、`mkdir`、`rm` 等，并可以访问 `/data` 目录下的文件。

本地模式下，该方法使用本地的 bash 解释器执行 shell 命令，工作目录为配置中的 `output_dir`，支持基本的 shell 操作，但不建议在生产环境中使用。

参数：

- command: `str`, 需要执行的 shell 命令。
- timeout: `int`, 可选，执行超时时间（秒），不配置时使用工具默认值。

#### file_operation

沙箱模式下，该方法专用于 `docker` 类型沙箱环境，用于在沙箱内执行基本的文件操作，包括创建、读、写、删除、列出、判断是否存在等。文件路径基于沙箱内部路径，通常建议在挂载目录 `/data` 下进行读写。

本地模式下，该方法用于直接对本地文件系统进行基础操作，但所有路径都会被约束在 `output_dir` 目录内部，以避免越权访问。

参数：

- operation: `str`, 要执行的文件操作类型，可选值为 `'create'`、`'read'`、`'write'`、`'delete'`、`'list'`、`'exists'`。
- file_path: `str`, 要操作的文件或目录路径（沙箱模式下为容器内路径，本地模式下通常为相对于 `output_dir` 的路径，也可以传入受限的绝对路径）。
- content: `str`, 可选，仅在 `write` 操作时需要，写入文件的内容。
- encoding: `str`, 可选，文件编码，默认为 `utf-8`。

#### reset_executor

沙箱模式下，用于在沙箱环境崩溃或 Notebook 内变量状态混乱时重启沙箱环境或重建内核，清空所有状态。

本地模式下，专用于在 Notebook 执行出现问题时对本地 Jupyter Kernel 进行重启，清空当前会话的所有状态。

#### get_executor_info

沙箱模式下，获取当前沙箱状态与环境的基础信息，例如沙箱 ID、运行状态、资源限制配置和可用工具列表等。

本地模式下，用于获取当前本地 Python 执行环境的基本信息，例如工作目录、是否已初始化、当前执行次数以及运行时长等。

### MCP 工具

支持传入外部MCP工具，只需要将mcp工具需要的配置写入字段即可，注意配置`mcp: true`。

```yaml
tools:
  amap-maps:
    mcp: true
    type: sse
    url: https://mcp.api-inference.modelscope.net/xxx/sse
    exclude:
      - map_geo
```

## 自定义工具

### 传入mcp.json

该方式可以传入一个mcp工具列表。作用和配置yaml中的tools字段相同。

```shell
ms-agent run --config xxx/xxx --mcp_server_file ./mcp.json
```

### 配置yaml文件

yaml中可以在tools中添加额外工具。可以参考[配置与参数](./config.md#工具配置)

### 编写新的工具

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

将文件保存在`agent.yaml`的相对目录中，如`tools/custom_tool.py`。

```text
agent.yaml
tools
  |--custom_tool.py
```

之后可以在`agent.yaml`中进行如下配置：

```yaml

tools:
  tool1:
    mcp: true
    # 其他配置

  tool2:
    mcp: false
    # 其他配置

  # 这里是注册的新工具
  plugins:
    - tools/custom_tool
```

我们有一个[简单的例子](https://www.modelscope.cn/models/ms-agent/simple_tool_plugin)，可以基于这个例子进行修改。
