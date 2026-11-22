# MCP tool connections

As an MCP client, MS-Agent connects to external servers and exposes their tools to the model. This is the opposite direction from exposing MS-Agent as an [MCP capability service](capability-gateway.md).

## Configure a stdio server

Save `mcp.json`, replacing the command with your installed server's interpreter and entry point:

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
ms-agent run --config agent.yaml --mcp_server_file ./mcp.json --query 'List available tools'
```

The TUI uses `--mcp-server-file`. The server must implement MCP initialization and tool calls; an ordinary webpage URL is not an MCP service.

## Transports and configuration sources

The SDK contains stdio, SSE, WebSocket, and streamable HTTP paths. Match type names, headers, timeout fields, and support to the entry point's schema. External YAML tools use `mcp: true`; built-ins need `mcp: false`.

Global/project MCP records normally live in their respective `.ms_agent/mcp.json`. Layered resolution merges by name and retains enabled state. See the [UI guide](../user-guide/skills-mcp.md). Do not assume one interface's file applies to every standalone CLI configuration.

## Probe, execute, close

```{mermaid}
flowchart TD
 A[Load and merge configuration] --> B[Connect and initialize]
 B --> C[List tools]
 C --> D[Invoke by name]
 D --> E[Record result or error]
 E --> F[Close owned connections and processes]
```

Startup includes connecting, initialization, and the first tool list. Each server gets a default 60-second budget after acquiring one of eight concurrency slots, plus a separate cleanup grace period. `MCP_STARTUP_TIMEOUT` sets the default and a positive server JSON `startup_timeout` overrides it. Ordinary calls have independent timeouts.

Failed servers are removed from the available tool surface while other MCP servers, built-ins, and ordinary chat remain usable. Notices expose controlled categories, HTTP statuses, and missing capabilities—not raw external logs, command arguments, or connection URLs that may contain credentials. The model receives a fixed capability notice without external error details.

Management probes use independent connections and do not repair existing sessions. The WebUI can schedule reconnects before the next idle turn, preserving current work and history; see [Skills and MCP](../user-guide/skills-mcp.md). Further independent `MCPRuntime` management extensions are in the [MCP RFC](../development/rfcs/mcp-runtime-api.md).

On failure, check executable paths, cwd, environment, protocol version, and network. Keep stdio server logs off stdout. Connect only to trusted services; tool-returned text is not automatically an instruction to execute.

Implementation: `tools/mcp_client.py`, `config/mcp_manager.py`, `config/mcp_schema.py`, `mcp/`.
