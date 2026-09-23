---
name: update-config
description: "Use this skill to configure the ms-agent harness: long-term memory (MEMORY.md, /memory on), MCP servers (mcp.json, /mcp add), and global vs project scope. Trigger on 配置记忆, 添加 MCP, 怎么开 memory, turn memory on, add an MCP server, or any ask about where config lives. Do not put memory settings in config.yaml — the project memory flag is what injects it. Not for writing the user's application code."
---

# Update Config

Configure **ms-agent itself** (memory, MCP, global vs project). This is the
harness, not the user's application.

Live paths on this machine are already filled in below. Read the target file
before writing. Merge; never replace a whole config file.

## Two scopes

| What | This folder (project) | Every project (global) |
|------|------------------------|------------------------|
| Long-term memory file | `{memory_md}` | Memory is per-project; there is no global MEMORY.md |
| Memory **flag** (what actually injects it) | TUI `/memory on`, or the WebUI project memory toggle | `/memory global on` only sets the default for **newly opened** folders |
| MCP servers | `{project_mcp}` | `{global_mcp}` (WebUI Settings → MCP) |

A server in the global file is not the same as one in the project file. Ask
if scope is unclear.

## Long-term memory

1. Facts live in `{memory_md}`.
2. Creating that file does **nothing** until the **project** memory flag is
   on. TUI: `/memory on` then `/new`. WebUI: the project memory toggle.
3. **Do not** add `memory.unified_memory` (or any memory block) to
   `{work}/.ms_agent/config.yaml` or to agent.yaml. That is not how this
   product enables memory.

Once the flag is on, prefer the session's memory tools for new facts; edit
MEMORY.md directly only when the user asks to inspect or rewrite it.

## MCP servers

TUI slash commands write the same files WebUI uses:

- This folder: `/mcp add NAME project url=...` (omitting scope writes project)
- Every project: `/mcp add NAME global url=...`

If you edit the file yourself, read it first and merge into `mcpServers`.

HTTP:

```json
{
  "mcpServers": {
    "NAME": {
      "type": "streamable_http",
      "url": "https://example.com/mcp"
    }
  }
}
```

stdio:

```json
{
  "mcpServers": {
    "NAME": {
      "command": "npx",
      "args": ["-y", "some-mcp-server"]
    }
  }
}
```

New servers connect this session when possible; otherwise tell the user
`/new` or restart.

## Workflow

1. Clarify global vs project if ambiguous.
2. Read the existing file (it may not exist yet — that is fine).
3. Merge the change; keep unrelated keys.
4. For memory, also tell the user the **project flag** must be on.
5. Confirm the path you wrote and the scope.

## Common mistakes

1. Teaching `config.yaml` / `memory.unified_memory` as the way to turn memory on.
2. Writing MEMORY.md without enabling the project flag.
3. Putting a project MCP server in `{global_mcp}` (or the reverse).
4. Replacing `mcp.json` instead of merging `mcpServers`.
