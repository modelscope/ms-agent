# Skills and MCP

Skills provide task knowledge; MCP connects external tools. Importing a skill does not establish its required service connections, and connecting a server does not enable every skill.

## Use a skill

1. Open **Skill management** or **Settings → MCP & Skills**.
2. Click “Add skill” to [install from a link](skill-management.md), upload a folder, or enter a directory path. Upload reads the browser's machine; a directory path refers to the backend machine. Include `SKILL.md` and required scripts/references. Local import copies the directory rather than continuously synchronizing the source.
3. Check enabled entries and counts in the project/conversation Skills selector.
4. Try a small task matching its description and inspect actual instruction loading and tool execution.

The imported skill appears as a card with an enable switch and a more-actions menu. Later changes to the source directory do not automatically update the copy. Hosted mode may hide local directory-path entry.

Review scripts, dependencies, and access scope first. Runtime skill IDs can derive from directory names rather than display names. Check duplicate names and global/project scope after imports.

## Connect MCP

1. Open **MCP management**. Use “Add MCP” for one server or the JSON configuration editor for the current scope's `mcpServers` object.
2. For stdio, supply an installed executable, arguments, and required environment. For remote servers, use a supported protocol URL and headers. The JSON editor saves the whole scope, so preserve unrelated server entries.
3. Save and click the card's test-connection button. A successful check reports the server as connected; inspect the error/log on failure. A probe is not a tool invocation.
4. Enable the card, verify the project/conversation MCP selector below the composer, then request one small, bounded tool call.

Paths belong to the backend machine. If Python/Node cannot be found, use an absolute executable path. Your interactive terminal PATH may differ from the server's.

## Distinguish three states

| State | Meaning |
| --- | --- |
| Configured/imported | A resource record exists |
| Enabled/selected | The current scope selects it |
| Callable | Connection, dependencies, credentials, and permissions are ready |

The initial stdio check only verifies that the command exists and shows **Connection not verified**. **Test connection** independently connects, initializes, and lists tools. Success proves that diagnostic connection, not an existing session's readiness or a business tool invocation.

## Startup failure and reconnecting

MCP capabilities are optional. If some or all servers fail, ordinary chat and built-in tools remain available with a capability notice. **Reconnect sessions next turn** in the card menu schedules affected sessions to rebuild when idle before the next turn. Current replies continue, session IDs/history remain, disabled servers stay disabled, and business calls are not automatically replayed.

Automatic remote checks allow up to six seconds, manual tests up to 45; a server's shorter startup budget still applies. If the MCP command downloads dependencies, verify actual package downloads before full initialization. An existing command or reachable package index alone does not establish service readiness.

## Diagnose failures

For missing skills, check directory layout and disabled/whitelist settings. For MCP failures, check executable, arguments, connectivity, and authentication. Remove keys, headers, and private paths before sharing logs. External tool output is not automatically a trusted system instruction.

See [Skills](../core/skills.md), [MCP client](../core/mcp-client.md), and [Capability service](../core/capability-gateway.md) for mechanisms and configuration.
