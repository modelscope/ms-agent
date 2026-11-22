# Execution environments

An execution environment determines where code runs and which files it sees. [Permissions](permissions.md) determine whether an operation is authorized. Rules do not replace process, container, or network isolation.

## Local execution

```yaml
output_dir: ./workspace
tools:
  code_executor:
    mcp: false
    implementation: python_env
    include: [python_executor, shell_executor]
```

`python_env` selects local execution. Shell/Python calls and Notebooks have different state models. An independent call cannot rely on a previous shell's `cd` or activation; a Notebook may retain kernel state. Use an absolute interpreter path or activate and execute within the same call.

| Operation | Check |
| --- | --- |
| shell_executor | Working directory, PATH, timeout, network authorization |
| python_executor | Selected interpreter; do not assume variables persist |
| notebook_executor | Notebook dependencies, kernel state, reset behavior |
| reset_executor | Can clear execution context; it is not a read-only probe |
| get_executor_info | Inspect the actual environment |

## Sandboxes and deployment

Sandbox execution requires its dependencies, images, and runtime service. Domain applications may use specific images. Changing an implementation name alone does not establish isolation. Configure mounts, network, and resource limits, then verify with a harmless task.

Agents operate on the WebUI server's filesystem. In a remote deployment, paths refer to the server, not the browser's computer. Do not expose an unauthenticated workspace publicly.

## Artifacts and failures

Work products remain in the workspace; internal indexes, locks, temporary files, and snapshots live under `.ms_agent`. Follow actual returned artifact paths. An in-memory tool document update is not a disk save.

Record interpreter/command, directory, and redacted errors when execution fails. Verify dependencies are installed in the correct environment. On cancellation, clean up processes owned by the task without terminating unrelated users' or services' processes.

Next: [Deployment](../user-guide/deployment.md), [Storage](../development/storage.md). Implementation: `tools/code/code_executor.py`, `local_code_executor.py`, `sandbox_manager.py`.
