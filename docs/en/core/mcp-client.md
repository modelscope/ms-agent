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
      "env": {}
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

A successful management probe proves that connection attempt, not every later session call. Existing direct-client execution differs from the separate MCPRuntime state machine. Session integration and persistent overrides are described in the [MCP RFC](../development/rfcs/mcp-runtime-api.md).

On failure, check executable paths, cwd, environment, protocol version, and network. Keep stdio server logs off stdout. Connect only to trusted services; tool-returned text is not automatically an instruction to execute.

Implementation: `tools/mcp_client.py`, `config/mcp_manager.py`, `config/mcp_schema.py`, `mcp/`.
