# A2A

A2A（Agent-to-Agent）面向远端智能体发现和任务交互。MS-Agent通过Agent Card公开服务信息，通过执行器把任务转交SDK；客户端则解析远端Card并发送消息。

## 启动本地服务

```bash
pip install -e '.[a2a]'
ms-agent a2a --config ./agent.yaml --host 127.0.0.1 --port 5000
```

`agent.yaml`必须已能正常调用模型。默认CLI监听地址不是仅本机，因此示例显式指定127.0.0.1。不要在未配置访问控制的情况下直接开放到公网。

```{mermaid}
sequenceDiagram
 participant Client as A2A客户端
 participant Card as Agent Card
 participant Server as A2A服务
 participant SDK as SDK
 Client->>Card: 发现能力与服务地址
 Client->>Server: 发送任务消息
 Server->>SDK: 映射并执行任务
 SDK-->>Server: 结果 / 状态 / 错误
 Server-->>Client: 消息或任务更新
```

## 从MS-Agent调用远端A2A

```yaml
a2a_agents:
  helper:
    url: http://127.0.0.1:5000
```

客户端按配置名选择目标，获取Agent Card，再使用A2A SDK发送消息。URL对应已运行的A2A服务，不是普通模型API。凭据头的配置与缓存需要按目标服务隔离，不能将一个服务的Key发送给另一个。

## 生命周期与结果

服务端有并发任务数和不活动超时限制；客户端可处理流式和非流式消息。SDK任务、A2A task和本地会话不一定是一一对应的文件，使用适配层提供的ID和状态。

恢复、取消和错误必须依据服务端实际能力，不能把HTTP请求成功等同于任务成功。日志应保留脱敏任务信息，不记录认证头。

与[ACP](acp.md)比较：ACP强调客户端与Agent的交互会话；A2A使用服务发现与远端任务交换。它们分别有适配器和配置。参数见[CLI参考](../development/cli-reference.md)。实现：`a2a/agent_card.py`、`executor.py`、`client.py`、`session_store.py`。
