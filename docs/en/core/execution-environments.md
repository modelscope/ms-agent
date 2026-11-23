# Execution environments

An execution environment determines where code runs and which files it sees. [Permissions](permissions.md) determine whether an operation is authorized. Rules do not replace process, container, or network isolation.

## Local execution

```yaml
output_dir: ./workspace
tools:
  code_executor:
    mcp: false
    implementation: python_env
    shell_timeout: 120
    include: [shell_executor]
```

`python_env` uses the host shell; local Python and Notebook executors are no longer provided. POSIX uses `/bin/sh` and Windows uses `cmd.exe`. Each call starts a separate process and cannot rely on an earlier `cd`, environment activation, or Python variables. Run Python through a project interpreter path, or activate and execute within one shell call.

Local `shell_timeout` defaults to 60 seconds; the example explicitly uses 120. Use `shell_env` for required variables: tools do not automatically inherit every credential from the service process. Docker images can use `MS_AGENT_SHELL_PATH` to separate the agent's tool environment from the service environment; explicit `shell_env` takes precedence.

Remove `python_executor`, `notebook_executor`, `reset_executor`, and `get_executor_info` from old local filter lists. Replace `python_timeout` / `notebook_timeout` with `shell_timeout`, and `kernel_env` with `shell_env`. Those four interfaces remain available in the appropriate sandbox mode.

## Sandboxes and deployment

Docker / Docker Notebook sandboxes provide Python, Notebook, shell, and file operations. Notebook kernels retain variables until reset, and `/data` exposes mounted shared files. Sandbox execution requires its dependencies, images, and runtime service. Domain applications may use specific images. Changing an implementation name alone does not establish isolation. Configure mounts, network, and resource limits, then verify with a harmless task.

Agents operate on the WebUI server's filesystem. In a remote deployment, paths refer to the server, not the browser's computer. Do not expose an unauthenticated workspace publicly.

## Artifacts and failures

Work products remain in the workspace; internal indexes, locks, temporary files, and snapshots live under `.ms_agent`. Follow actual returned artifact paths. An in-memory tool document update is not a disk save.

Record interpreter/command, directory, and redacted errors when execution fails. Verify dependencies are installed in the correct environment. On cancellation, clean up processes owned by the task without terminating unrelated users' or services' processes.

Next: [Deployment](../user-guide/deployment.md), [Storage](../development/storage.md). Implementation: `tools/code/code_executor.py`, `local_code_executor.py`, `sandbox_manager.py`.
