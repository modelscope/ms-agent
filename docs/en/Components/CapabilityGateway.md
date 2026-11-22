# Capability Gateway

The Capability Gateway packages ms-agent projects, components, and atomic tools
behind a uniform descriptor / registry / async API, and exposes them as **MCP
tools** for external host agents (nanobot, OpenClaw, Hermes, Cursor, Claude
Desktop, …).

It is **not** injected into the in-process `LLMAgent` tool manager. Host agents
discover tools via MCP; usage guidance lives in the skill package
[`ms-agent-skills/`](https://github.com/modelscope/ms-agent/tree/main/ms-agent-skills).

## Surfaces

| Surface | Entry point |
|---------|-------------|
| Python API | `from ms_agent.capabilities import create_registry` |
| MCP server | `python -m ms_agent.capabilities.mcp_server` |
| Health check | `python -m ms_agent.capabilities.mcp_server --check` |
| Skill docs | [`ms-agent-skills/SKILL.md`](https://github.com/modelscope/ms-agent/blob/main/ms-agent-skills/SKILL.md) |

`--check` reports both `registered_total` (31 descriptors) and
`mcp_exposed_total` (30 tools). The parent component `lsp_code_server` is
registered but not advertised as its own MCP tool; its children
`lsp_check_directory` / `lsp_update_and_check` are.

`lsp_check_directory` currently indexes files; empty diagnostics do not mean the project passed validation. Use `lsp_update_and_check` for incremental diagnostics and run project type checks or tests for final verification. TypeScript dependencies are resolved through `npx`, locally or globally. Exa accepts either `EXA_API_KEY` or an `EXA_API_KEYS` key pool.

## Architecture

```
Host agent  --MCP stdio-->  mcp_server.py (FastMCP)
                                |
                          CapabilityRegistry
                           /        |        \
                   in-process   AsyncTaskManager   subprocess
                 (fs/search/lsp/   (submit/check/   (deep_research,
                  delegate/doc)     get/cancel)      fin/code/cinema)
```

Long-running project capabilities prefer the async submit / check / get
pattern. `AsyncTaskManager` is **in-process only**: task IDs are lost if the
MCP server process restarts.

## Skill package

The skill package at repo-root `ms-agent-skills/` documents all 30 MCP tools
and their SOPs. It is:

- Copied into host agent skill trees by
  `examples/capability/*/install_skill.sh`
- Installed into ms-agent’s own skill tree by
  `ms-agent-skills/scripts/install_into_ms_agent.sh`
  (destination: `$MS_AGENT_HOME/skills/ms-agent`, default `~/.ms_agent/skills/ms-agent`)
- Bundled into the wheel at build time under `ms_agent/skills/ms-agent/`
  in distributions built from current source. This does not mean the older PyPI 1.6.0 package already contains these resources.

Validate the Capability Index against the live registry:

```bash
python ms-agent-skills/scripts/validate_capability_index.py
```

## Integration examples

See [`examples/capability/`](https://github.com/modelscope/ms-agent/tree/main/examples/capability) for nanobot,
OpenClaw, and Hermes setup (shared notes in `setup.md`).

## Related

- [Agent Skills](AgentSkills.md) — ms-agent’s in-process skill runtime (progressive disclosure)
- [Tools](Tools.md) — MCP client configuration for LLMAgent
