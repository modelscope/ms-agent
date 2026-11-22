# Subagents

Subagents let a primary agent delegate focused work to independent execution contexts and combine the results. This differs from a fixed [workflow](workflows.md) graph and from remote ACP/A2A service calls.

## When to delegate

Choose bounded work that can return an independent result, such as reviewing separate documents or analyzing different modules. Do not blindly parallelize dependent tasks that write the same files.

```{mermaid}
flowchart TD
 A[Primary agent defines tasks] --> B[Task one · independent context]
 A --> C[Task two · independent context]
 B --> D[Results and artifacts]
 C --> D
 D --> E[Primary agent verifies and aggregates]
```

## Configuration and discovery

`AgentTool` supports `agent_tools` and the compatible `split_task` configuration form. Plugins can provide agent definitions too. Tool visibility depends on effective configuration and assembly; inspect the available tool list first.

```yaml
tools:
  split_task:
    mcp: false
```

This is a minimal enabling fragment, not a complete subtask definition. Model, permissions, and execution choices still come from agent/tool configuration. Use the runtime tool schema instead of inventing prompt parameters.

## Supply bounded context

Define the goal, input files, output location, completion checks, and prohibited operations. An independent context does not automatically contain the primary conversation's details. A shared workspace does not make concurrent writes safe.

Verify evidence and artifacts, not just a “done” message. Treat failures, cancellations, timeouts, and partial output separately. Scheduling/task-control mechanisms do not imply that arbitrary background work survives process restarts.

## Local delegation and protocols

- Local subagents use SDK AgentTool and task state.
- [ACP](acp.md)/[A2A](a2a.md) connect to external agents whose services own execution.
- [Capability Gateway](capability-gateway.md) exposes MS-Agent capabilities as MCP tools to a host.

Implementation: `tools/agent_tool.py`, `tools/task_control_tool.py`, and plugin agent assembly.
