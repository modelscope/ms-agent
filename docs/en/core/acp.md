# ACP

ACP (Agent Client Protocol) connects editors and other clients to agents. MS-Agent can serve ACP requests and call external ACP agents. It is not another configuration name for [A2A](a2a.md).

## Start a server

Prepare a runnable `agent.yaml` and model credentials in your source-install environment:

```bash
pip install -e '.[acp]'
ms-agent acp --config ./agent.yaml
```

The default transport is stdio, with the client owning the process. Protocol data uses stdout; diagnostics belong on stderr or in a log file. Do not mix ordinary print output into the protocol channel.

```{mermaid}
sequenceDiagram
 participant Client as ACP client
 participant Server as MS-Agent ACP server
 participant Agent as SDK agent
 Client->>Server: initialize / session new
 Client->>Server: prompt
 Server->>Agent: Run task
 Agent-->>Server: Content and tool events
 Server-->>Client: Session updates
 Server->>Client: Permission request
 Client-->>Server: Allow or deny
 Server-->>Client: Turn complete
```

Events depend on the task; not every prompt requests approval. The server maps sessions, messages, events, and permission requests. Disconnects and timeouts require resource cleanup.

## The HTTP extension is not standard stdio ACP

`--serve-http` exposes a project-specific HTTP/SSE API for compatible clients. Bind locally for testing:

```bash
ms-agent acp --config ./agent.yaml --serve-http --host 127.0.0.1 --port 8080
```

Before remote exposure, configure `MS_AGENT_ACP_API_KEY` or the authentication option and network controls. A WebUI API URL is not automatically an ACP endpoint.

## Call external agents

`ACPClientManager` and the ACP tool manage external connections through `acp_agents` configuration. Match parameters to the target process/service. Validate initialization and one small task before complex delegation. Proxy sessions, model selection, and permission mapping depend on the current adapter.

Diagnose dependencies, command/cwd, configuration, protocol initialization, then model calls. A tool authorization failure is not a model failure. See [CLI reference](../development/cli-reference.md). Implementation: `acp/server.py`, `client.py`, `translator.py`, `permissions.py`, `proxy.py`.
