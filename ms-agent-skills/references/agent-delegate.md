# Agent Delegate Capability

## When to Use

Activate this capability when:
- The user asks you to handle a complex multi-step task that benefits from
  a dedicated agent with tool access
- A task requires iterative tool calling
- You want to offload work to a specialized agent while continuing to
  handle other messages

## Sync Mode: `delegate_task`

**Granularity:** Project
**Estimated Duration:** minutes (blocks until complete)

Creates an LLMAgent, runs it on the query, and returns the final response.
The agent can use basic tool components (web search, file system, todo list)
during execution.

### Parameters

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | string | yes | -- | The task description for the agent |
| `system_prompt` | string | no | -- | Custom system prompt |
| `tools` | string | no | -- | Comma-separated basic tool component names (e.g. `web_search,file_system,todo_list`). Alias `filesystem` is accepted for backward compatibility. |
| `max_rounds` | integer | no | 20 | Maximum tool-use rounds |
| `config_path` | string | no | -- | Path to agent YAML config |

### Example

```
delegate_task(
    query="Search for the top 5 Python web frameworks in 2026, compare their performance benchmarks, and write a summary report.",
    tools="web_search",
    max_rounds=15
)
```

### Response

```json
{
  "status": "completed",
  "response": "# Python Web Framework Comparison 2026\n\n..."
}
```

## Async Mode: Submit / Check / Get / Cancel

For long-running tasks, use the async pattern to avoid blocking.

### Tool: `submit_agent_task`

Starts the agent in the background. Same parameters as `delegate_task`.

```
submit_agent_task(
    query="Analyze the codebase at /project and suggest architectural improvements",
    tools="web_search,file_system,todo_list",
    max_rounds=20
)
```

**Returns:**
```json
{
  "task_id": "e5f6a7b8",
  "status": "running",
  "message": "Agent task e5f6a7b8 started. Use check_agent_task..."
}
```

### Tool: `check_agent_task`

| Parameter | Type | Required | Description |
|---|---|---|---|
| `task_id` | string | yes | The task_id from submit_agent_task |

**Returns:**
```json
{
  "task_id": "e5f6a7b8",
  "task_type": "agent_delegate",
  "status": "running",
  "created_at": "2026-03-24T14:30:00"
}
```

Status values: `running`, `completed`, `failed`, `cancelled`.

### Tool: `get_agent_result`

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `task_id` | string | yes | -- | The task_id from submit_agent_task |
| `max_chars` | integer | no | 50000 | Max response length |

**Returns (on completion):**
```json
{
  "task_id": "e5f6a7b8",
  "status": "completed",
  "response": "# Analysis Results\n\n...",
  "truncated": false
}
```

### Tool: `cancel_agent_task`

| Parameter | Type | Required | Description |
|---|---|---|---|
| `task_id` | string | yes | The task_id to cancel |

## SOP: Task Delegation

### Step 1: Assess the Task

Use `delegate_task` (sync) when:
- Task is relatively short (< 5 minutes)
- You need the result immediately

Use `submit_agent_task` (async) when:
- Task may take a long time
- You want to handle other user messages while it runs

### Step 2: Craft the Query

Write a clear, detailed task description. Include:
- What the agent should accomplish
- Any constraints or requirements
- Expected output format

### Step 3: Choose Tools

Available tool names for the `tools` parameter:
- `web_search` — web search access
- `file_system` — file read/write/list
- `todo_list` — todo plan read/write
- `filesystem` — backward-compatible alias for `file_system`

The `tools` parameter selects **basic tool components**, not the higher-level
capability references listed elsewhere in the skill docs. For example,
`file_system` refers to the base primitives such as `write_file`, `read_file`,
and `list_files`; it is separate from the capability-layer editing references
in `filesystem-tools.md`.

Default component configs injected by the wrapper:
- `web_search` → `mcp: false`, `engine: arxiv`
- `file_system` → `mcp: false`, `include: [write_file, read_file, list_files]`
- `todo_list` → `mcp: false`, `include: [todo_write, todo_read]`

Leave `tools` empty to use the agent's default configuration.

### Step 4: Execute

**Sync:**
```
delegate_task(query="...", tools="web_search", max_rounds=15)
```

**Async:**
```
submit_agent_task(query="...", tools="web_search,file_system,todo_list", max_rounds=20)
# ... handle other work ...
check_agent_task(task_id="e5f6a7b8")
# ... when completed ...
get_agent_result(task_id="e5f6a7b8")
```

### Step 5: Present Results

- Summarize the agent's response for the user
- Highlight key findings or actions taken
- Offer to follow up on specific points

## Configuration

By default the delegated agent uses ms-agent's built-in config (`agent.yaml`).
For advanced use, provide a `config_path` pointing to a custom YAML config
that specifies the LLM provider, model, and tool settings.

## Notes

- The delegated agent runs in the same process as the MCP server.
- Each delegation creates a fresh agent instance (no shared state).
- `max_rounds` controls how many tool-use iterations the agent can perform.
  Set it lower (5-10) for simple tasks, higher (20+) for complex ones.
- If a task fails, check the `error` field for details. Common causes:
  missing LLM API keys, tool initialization errors, or max rounds exceeded.
