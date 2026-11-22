# ACP

ACP（Agent Client Protocol）连接编辑器或其他客户端与智能体。MS-Agent既能作为ACP服务提供执行，也能作为客户端调用外部ACP Agent；它不是[A2A](a2a.md)的另一种配置名。

## 启动服务

在源码安装环境中准备可运行的 `agent.yaml` 和模型凭据：

```bash
pip install -e '.[acp]'
ms-agent acp --config ./agent.yaml
```

默认使用stdio，由ACP客户端启动和管理该进程。协议消息使用标准输出，诊断写到标准错误或指定日志，不能在协议通道混入print输出。

```{mermaid}
sequenceDiagram
 participant Client as ACP客户端
 participant Server as MS-Agent ACP服务
 participant Agent as SDK智能体
 Client->>Server: initialize / session new
 Client->>Server: prompt
 Server->>Agent: 运行用户任务
 Agent-->>Server: 内容与工具事件
 Server-->>Client: session updates
 Server->>Client: 请求操作确认
 Client-->>Server: 允许或拒绝
 Server-->>Client: 本轮完成
```

具体事件视任务而定，不是每次prompt都需要确认。服务管理会话并转换消息、事件和权限请求；客户端断开和超时需释放相关资源。

## HTTP扩展不是标准stdio替代品

`--serve-http`提供项目的非标准HTTP/SSE服务面，只有匹配的客户端才能使用。示例仅监听本机：

```bash
ms-agent acp --config ./agent.yaml --serve-http --host 127.0.0.1 --port 8080
```

对外暴露前配置 `MS_AGENT_ACP_API_KEY` 或相应鉴权选项、网络访问控制。不要将通用WebUI API地址当作ACP端点。

## 调用外部Agent

SDK中的 `ACPClientManager` 和ACP工具负责外部Agent连接，配置入口为 `acp_agents`。连接参数需要对应目标进程/服务；先用目标客户端验证握手和一个小任务，再引入复杂委派。代理的会话、模型选择和权限映射能力以当前适配器为准。

排障依次检查依赖、命令/工作目录、配置、协议握手、模型调用；不把工具权限失败当成模型故障。参数见[CLI参考](../development/cli-reference.md)。实现：`acp/server.py`、`client.py`、`translator.py`、`permissions.py`、`proxy.py`。
