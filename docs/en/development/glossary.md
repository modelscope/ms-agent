# Glossary

| Term | Meaning in these docs | Not equivalent to |
| --- | --- | --- |
| Agent | Runtime coordinating a model, tools, and state | One LLM request |
| Harness | Execution, context, permissions, and feedback around a model | A fixed UI or operating system |
| Provider | Registered model-service connection/capabilities | Model ID or wire protocol |
| Tool | Callable operation with defined input/result | Instructions describing an operation |
| Skill | Task instructions and on-demand resources/scripts | Already installed executable tools |
| Callback | In-process Python lifecycle extension | External script hook |
| Hook | Event-driven script/decision extension | Every plugin capability |
| Plugin | Installation and assembly unit for extension resources | Universal host-code compatibility |
| Session | Task conversation records and recovery state | Global memory |
| Context | Information visible to the current model call | Complete original history |
| Compaction | Budgeted transformation/summarization of model input | Deleting all original records |
| Memory | Cross-task knowledge and its backend | Copying every conversation to a file |
| Workspace | Project files and tool/artifact scope | WebUI dependency directory |
| Workflow | Explicit stages and dependencies | Arbitrary autonomous delegation |
| MCP client/server | Consuming/providing tools | An alias for ACP or A2A |
| RFC | Status-labelled design proposal | A released feature guarantee |

Explain a concept's purpose before its details. See [Core modules](../core/configuration.md) and [Architecture](architecture.md). Historical applications may retain older names; interpret them with the relevant version and implementation.
