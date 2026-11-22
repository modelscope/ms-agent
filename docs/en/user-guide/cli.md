# CLI tasks and scripts

Use the CLI for terminal tasks and scripts. Choose the [TUI](tui.md) for ongoing interaction and the [CLI reference](../development/cli-reference.md) for exact arguments.

## Run a bounded task

```bash
ms-agent run --config ./agent.yaml --query 'Summarize this material' --output_dir ./results
```

The configuration must point to an accessible model. `--output_dir` is the workspace, not merely an export directory. Test in an empty directory before using a real project.

For scripts, explicitly disable interaction and set a budget:

```yaml
interactive: false
callbacks: []
max_chat_round: 3
```

Supply credentials through environment variables or local dotenv files, not shared scripts. `--env /path/to/.env` selects a file; check entry-point rules for environment/configuration precedence.

## Input and output

`--query` makes the task explicit. Without it, execution may use interactive, configured, or piped input. Automation should provide query, configuration, and workspace instead of depending on an incidental lack of TTY.

Terminal output includes progress and is not a stable JSON API. Use the [Python SDK](../get-started/python-sdk.md) for structured messages/artifacts. Check exit status, logs, and expected files rather than looking only for a “done” string.

## External tools and code

```bash
ms-agent run --config ./agent.yaml --mcp_server_file ./mcp.json --query 'Check available tools'
```

Use `--mcp_server_file` for MCP connections. `--mcp_config` remains declared but should not be recommended without verifying its actual integration. External Python code requires `--trust_remote_code true`; the TUI option with the same name is a boolean flag, with different syntax.

## Interrupt and retry

After Ctrl-C, inspect owned tool/subprocess shutdown and existing artifacts. `--load_cache true` restores project/step caches, not a universal session picker. Check configuration/cache correspondence before retrying.

The default agent may download dependencies initially. Follow progress, and ensure python/pip belong to the intended environment when resolving missing packages.

Next: [Configuration](../core/configuration.md), [Workflows](../core/workflows.md), [Troubleshooting](troubleshooting.md).
