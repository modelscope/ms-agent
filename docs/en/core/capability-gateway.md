# MCP capability service

Capability Gateway exposes MS-Agent projects, components, and atomic tools over MCP for external agents. This is the opposite of using external tools through the [MCP client](mcp-client.md). The gateway is not automatically injected into every in-process LLMAgent.

## Check and start

```bash
python -m ms_agent.capabilities.mcp_server --check
python -m ms_agent.capabilities.mcp_server
```

The check currently reports 31 registered descriptors and 30 exposed MCP tools. Parent `lsp_code_server` describes the component; its two children are exposed independently. Counts establish discovery, not readiness of every dependency or credential.

Configure the host with the absolute path to the Python environment containing MS-Agent and arguments `-m ms_agent.capabilities.mcp_server`. Stdio protocol traffic uses stdout while Python library output is protected. HTTP/SDK calls do not replace host stdout.

## Long tasks

```{mermaid}
sequenceDiagram
 participant Host as Host agent
 participant MCP as MCP server
 participant Task as Task manager
 Host->>MCP: Submit task
 MCP->>Task: Start work
 MCP-->>Host: task_id
 Host->>MCP: Check progress
 MCP-->>Host: running / completed / failed
 Host->>MCP: Get result
 MCP-->>Host: Result, artifacts, or error
```

Prefer submit/check/get for long operations; synchronous tools can occupy a request for a long time. Task state is mainly in-process. A task ID is not a durable execution handle after server restart; output files and task state are separate assets.

## Dependencies and limits

- Delegation resolves credentials through the selected provider. Missing explicit configuration paths fail rather than silently selecting a default agent.
- Exa accepts `EXA_API_KEY` or `EXA_API_KEYS`; other engines have their own keys. arXiv needs no key.
- TypeScript resolves language servers through npx. Directory LSP calls only index files; empty diagnostics are not proof of correctness. Run incremental diagnostics and final type checks separately.
- Wheel builds package `ms-agent-skills/` at `ms_agent/skills/ms-agent/`.

See the [skill package](https://github.com/modelscope/ms-agent/tree/main/ms-agent-skills) and [host examples](https://github.com/modelscope/ms-agent/tree/main/examples/capability). Skill installation and MCP connection setup are separate steps.

Implementation: `capabilities/mcp_server.py`, `registry.py`, `async_task.py`, wrappers.
