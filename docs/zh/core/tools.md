# 工具

工具将模型的意图变成有名称、参数和结果的操作。`ToolManager`负责发现、过滤、授权、超时及执行；技能说明不能替代工具实现。

## 启用并限制范围

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

内置工具写 `mcp: false`；`include`与`exclude`不能同时使用。文件工具实际名称包括 `read_file/write_file/edit_file/glob/grep`，不是旧文档的create_directory/list_files。工作目录由 `output_dir`决定，默认当前目录；权限规则仍会限制具体路径。

## 能力目录

| 工具或工具组 | 职责 |
| --- | --- |
| file_system | 文件读取、精确编辑、搜索与匹配 |
| code_executor | 本地 shell；沙箱中的 Python、Notebook及环境操作 |
| web_search / localsearch | 网络搜索 / 按需本地检索 |
| todo_list / task_control | 任务计划与执行控制 |
| agent_tools / split_task | 子智能体任务拆分与委派 |
| cron | 调度任务管理 |
| lsp_code_server | 代码索引与增量诊断 |
| image_generator / video_generator / financial_data_fetcher | 专项生成与金融数据 |
| image_reader | 为非视觉主模型提供辅助读图 |
| skills / unified_memory | 随技能和记忆运行时装配的工具 |
| ACP / A2A 工具 | 调用远端智能体 |

可用项取决于依赖、配置和动态装配，不是全部默认启用。LSP目录检查当前只索引文件，不能替代类型检查或测试。大结果可能被裁剪/落盘，按返回路径读取，不要求模型重复调用。

使用 Context 搜索时，设置 `CONTEXT_DEV_API_KEY` 并显式配置 `tools.web_search.engine: context`。设置 `fetch_content: false` 可仅搜索并返回 Highlights；启用内容抓取时仍使用现有网页抓取流程。托管搜索设置会加密其 `context_api_key`，现有默认设置保持不变。

## 自定义工具

保存为配置目录中的 `tools/custom_tool.py`：

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

覆盖 `_get_tools_inner()`而非`get_tools()`，并在初始化时读取过滤配置。配置文件与 `tools/` 目录同级：

```yaml
tools:
  plugins: [tools/custom_tool]
  custom_tool:
    mcp: false
    include: [echo]
```

`tools.plugins` 是加载 Python 工具的字段，与顶层 [Plugins](plugins.md) 资源系统不同。使用配置加载器设置 `local_dir`，加载外部代码需 `--trust_remote_code true`；仅信任经过审查的来源。

## 执行与失败

经管理器调用的工具经过安全/权限/Hook管线；直接调用工具对象不自动获得同等保护。`tool_call_timeout`默认120秒，默认上限`tool_call_timeout_max`为600秒。取消后清理自己持有的子进程和连接，不把超时当作操作已撤销。

下一步：[执行环境](execution-environments.md)、[MCP客户端](mcp-client.md)、[权限](permissions.md)。实现：`tools/base.py`、`tools/tool_manager.py`。
