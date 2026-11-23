# MCP 工具接入

MS-Agent作为MCP客户端时，连接外部服务并把其工具提供给模型。这与将MS-Agent自身作为[MCP能力服务](capability-gateway.md)暴露给别人是两个方向。

## 配置一个stdio服务

保存 `mcp.json`，将命令替换为已安装服务的实际解释器和入口：

```json
{
  "mcpServers": {
    "local-tools": {
      "command": "/path/to/python",
      "args": ["/path/to/server.py"],
      "env": {},
      "startup_timeout": 60
    }
  }
}
```

```bash
ms-agent run --config agent.yaml --mcp_server_file ./mcp.json --query '列出可用工具'
```

TUI的对应参数是 `--mcp-server-file`。服务必须遵循MCP握手与工具协议；不要把普通HTTP网页放入服务URL。

## 传输与配置来源

SDK客户端包含stdio、SSE、WebSocket和streamable HTTP连接路径；具体type名称、headers、超时及运行支持以所用入口schema为准。YAML的外部工具设置 `mcp: true`；内置工具必须 `mcp: false`。

全局和项目MCP配置通常在各自 `.ms_agent/mcp.json`，分层解析时同名项覆盖并保留enabled状态。WebUI操作见[技能与MCP教程](../user-guide/skills-mcp.md)。不要把某个入口的MCP文件自动认为对所有独立CLI配置生效。

## 探测、执行、关闭

```{mermaid}
flowchart TD
 A[加载并合并配置] --> B[建立连接与握手]
 B --> C[枚举工具]
 C --> D[按名称调用]
 D --> E[记录结果或错误]
 E --> F[关闭拥有的连接/子进程]
```

启动包括连接、握手和首次枚举工具。每个服务获得并发名额后默认有 60 秒预算，最多同时启动 8 个；资源清理另有等待上限。`MCP_STARTUP_TIMEOUT` 可设置默认预算，服务 JSON 中正数 `startup_timeout` 可覆盖；普通工具调用使用独立超时。

失败服务从可用工具面中移除，其他 MCP、内置工具和普通聊天继续运行。提示仅包含受控错误类别、HTTP 状态码及缺失能力，不展示外部原始日志、命令参数或连接地址，以免泄露凭据。模型接收固定的能力缺失提示，不接收外部错误详情。

管理探测使用独立连接，不修复现有会话。WebUI 可安排下轮重连，当前执行和历史不受影响，详见[技能与 MCP](../user-guide/skills-mcp.md)。独立 `MCPRuntime` 管理接口的进一步扩展见[MCP RFC](../development/rfcs/mcp-runtime-api.md)。

图片类型的工具结果会保存为工作区附件，模型按协议读取；格式无效的图片会标记为工具错误。存储位置、支持条件与限制见[多模态](multimodal.md)。

检查失败时确认命令可执行、工作目录、环境变量、协议版本和网络。stdio服务的日志必须避开stdout。只连接可信服务，外部工具返回文本也不是应无条件执行的指令。

实现：`tools/mcp_client.py`、`config/mcp_manager.py`、`config/mcp_schema.py`、`mcp/`。
