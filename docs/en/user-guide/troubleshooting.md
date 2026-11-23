# Troubleshooting

Check environment, services, model, tools, then state. Change one condition at a time and reproduce with a small task. Do not begin by deleting projects, caches, or all configuration.

## Startup and environment

| Symptom | Check/action |
| --- | --- |
| ms-agent not found | Activate the Python environment used for installation |
| Node/pnpm missing | Load nvm in the new shell; verify Node 22.22.0+ and pnpm 10.17.1 |
| Slow first launch | Inspect dependency/build progress before testing readiness |
| Missing page/CSS | Use normal `ms-agent ui` / `pnpm build`; do not bypass stylesheet generation |
| Port busy | Select a free port instead of killing unrelated processes |

## Models and streaming

If no model is listed, add one first. Check credentials/access for 401/403, endpoint/model for 404, and parameters/content types for 400. Test plain text without attachments or optional tools, then add them individually.

Silence during streaming can mean tool arguments are being composed or approval is pending. Inspect status instead of repeatedly submitting the same task. Review partial artifacts after stopping.

## Files, history, and drafts

- Missing history: verify project, workspace, `MS_AGENT_HOME`, and interface.
- Lost edits: confirm the file was saved; page-local drafts need not survive refresh.
- File conflicts: inspect disk changes before reload or overwrite.
- Default-project recovery prompt: back up first and read which metadata will change.

## Tools and extensions

For MCP failures, check executable paths, network, authentication, and protocol. For missing skills, check structure, enabling, and scope. Resolve permission denials through rules/handlers, not model prompts intended to bypass protection.

An MCP startup notice does not mean the whole conversation failed; ordinary chat and built-in tools remain available. **Connection not verified** only confirms command presence. A successful manual test still requires **Reconnect sessions next turn** to update existing sessions. Reconnection never replays failed business calls automatically; inspect side effects before retrying. See [Skills and MCP](skills-mcp.md).

Local search needs actual roots. LSP indexing is not compiler validation. Install optional vector, parsing, or video dependencies in the environment that actually runs the task.

## Report a reproducible issue

Include entry point, steps/command, version/commit, platform and Python/Node versions, redacted errors, and expected versus actual results. Supply minimal logs/configuration without keys, authentication headers, private files, or complete sensitive requests. Distinguish model-answer quality from framework transport/lifecycle failures.

Next: [Quick start](../get-started/quick-start.md), [Configuration reference](../development/configuration-reference.md), [Contributing](../development/contributing.md).
