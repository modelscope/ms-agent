# A2A

A2A (Agent-to-Agent) supports remote-agent discovery and task exchange. MS-Agent publishes service information through an Agent Card and delegates execution to the SDK. Its client discovers remote cards and sends messages.

## Run locally

```bash
pip install -e '.[a2a]'
ms-agent a2a --config ./agent.yaml --host 127.0.0.1 --port 5000
```

The configuration must already work with your model. The CLI default is not loopback-only, so this example explicitly binds to 127.0.0.1. Configure access controls before remote exposure.

```{mermaid}
sequenceDiagram
 participant Client as A2A client
 participant Card as Agent Card
 participant Server as A2A server
 participant SDK
 Client->>Card: Discover capabilities and endpoint
 Client->>Server: Send task message
 Server->>SDK: Map and execute task
 SDK-->>Server: Result / status / error
 Server-->>Client: Message or task updates
```

## Call a remote A2A agent

```yaml
a2a_agents:
  helper:
    url: http://127.0.0.1:5000
```

The client selects a configured target, resolves its Agent Card, and sends a message using the A2A SDK. This URL identifies a running A2A service, not a model API. Keep authentication headers and connection caches isolated by service.

## Lifecycle and results

The server limits concurrent tasks and inactivity; the client handles streaming and non-streaming responses. SDK tasks, A2A tasks, and local sessions do not necessarily map one-to-one onto files. Use adapter-provided IDs and states.

Recovery, cancellation, and errors depend on actual server capabilities. An HTTP success is not proof of task completion. Log redacted task information rather than authentication headers.

Compared with [ACP](acp.md), ACP focuses on client-agent interactive sessions, while A2A uses service discovery and remote-task exchange. They have separate adapters and configuration. See [CLI reference](../development/cli-reference.md). Implementation: `a2a/agent_card.py`, `executor.py`, `client.py`, `session_store.py`.
