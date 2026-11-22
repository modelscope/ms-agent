# TUI interaction

The TUI provides ongoing terminal interaction over shared SDK execution and sessions, without a browser frontend. Complete {ref}`terminal installation <terminal>` first.

## Start

```bash
ms-agent --work-dir ./demo-project
```

`ms-agent` without a subcommand opens the TUI; explicit `ms-agent tui` also works. Add `--config ./agent.yaml` for an existing configuration and `--env ./.env` for dotenv input. Create or verify the workspace first. Permissions default to `ask`. `--agent` loads local configuration or an Agent Hub template; review external sources before downloading.

Initial tool setup may take time. Submit a small task when the prompt appears. The bottom bar shows model, tokens, permissions, and session information. Type `/` for completion and use the up arrow for current input history.

## Useful commands

| Command | Purpose |
| --- | --- |
| `/help` | Commands available in this interface |
| `/model` | Model selection/configuration; follow prompts |
| `/tools` | Configured tools |
| `/sessions` | Project session list |
| `/resume <number-or-ID>` | Reopen a session |
| `/new` | Start another session |
| `/context` / `/usage` | Context and usage |
| `/compact` | Compact context through the shared SDK summary operation |
| `/mcp` / `/skills` | Manage connections, imports, and enabled resources |
| `/search` | View or configure the search service |
| `/memory` | Enable or disable memory |
| `/profile` | Locate AGENTS.md and PROFILE.md |
| `/permission ask\|auto\|full-access` | View or switch permission modes |
| `/interject steer\|queue` | Select input behavior during execution |
| `/stop` / `/cancel` | Interrupt the current task, retaining generated content |
| `/quit` | Exit interaction |

Commands depend on the interface and installed extensions. Prefer `/help` over another agent product's shortcut list. Hermes options such as `--tui` or `--continue` are not MS-Agent commands.

## Input, approval, and interruption

Input uses prompt_toolkit by default; multiline/paste shortcuts differ between terminals. Prepare long text in an editor, paste it, and inspect it before sending. Attachment support depends on the parser/model; a path written in a message is not proof that pixels were uploaded.

Inspect commands and targets before approval. Ctrl-C may interrupt input or execution; check actual state and use stop/exit if work remains active. Review generated files after interruption. Cancellation is not rollback.

## Input while running

The input line stays pinned at the bottom while the task runs. Keep editing ordinary text and press Enter to submit. The default `steer` mode adds it to the current task after the current model/tool operation ends. `/interject queue` waits until the task finishes before processing subsequent input; `/interject steer` switches back. The status bar shows the mode and pending count. Ordinary commands queue; priority stop/exit commands do not wait for normal completion.

Ctrl-C requests interruption while running and clears the draft while idle. Tool approvals remain separate. The TUI queue is an in-process buffer, not the WebUI's editable, withdrawable, durable queue. Check unprocessed input before exiting.

## Resume and record events

Restart from the same workspace and use `/sessions` and `/resume`. Session switching happens at lifecycle boundaries; do not modify active logs behind the runtime.

```bash
ms-agent tui --work-dir ./demo-project --emit-events ./events.jsonl
```

Events can contain task/tool data; redact before sharing. Without a TTY, input can fall back to a simpler mode. A successful piped invocation is not a complete interactive test.

Next: [CLI scripting](cli.md), [Sessions](../core/sessions.md), [Permissions](../core/permissions.md).
