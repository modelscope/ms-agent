# Scheduled tasks

Verify a task manually before scheduling it. Repeated model/tool calls may incur cost and side effects. Start with small, repeatable work.

## Create and inspect

```bash
ms-agent cron create 'every 30m' 'Inspect project status and summarize it without editing source files' --name status-check --project /path/to/project/agent.yaml --timeout 120
ms-agent cron list --json
```

`--project` accepts a prepared Agent configuration file or a directory resolving to one; use an explicit `agent.yaml` for the first test. A directory also containing `workflow.yaml` may resolve differently. Configure models/tools for unattended execution; the task timeout is in seconds. Record the job ID and check schedule, enabled state, and time zone. Intervals, one-shot times, and cron expressions are supported; see [Scheduling](../core/scheduling.md).

When running a scheduler with a custom workspace, use the same `--workspace` path in commands such as `ms-agent cron status --workspace /path/to/cron` and `ms-agent cron list --workspace /path/to/cron`. An explicit path overrides `MS_AGENT_CRON_WORKSPACE`. The workspace contains scheduler state and is separate from the Agent configuration selected by `--project`.

## Run once manually

Replace `JOB_ID` with the returned ID:

```bash
ms-agent cron run JOB_ID
ms-agent cron history JOB_ID
ms-agent cron output JOB_ID --last
```

Inspect artifacts, errors, and duration. A “done” reply does not prove an output file exists. Operations requiring approval may be denied without an interactive handler.

## Start the scheduler

```bash
ms-agent cron start --foreground
```

Keep the terminal running and check `ms-agent cron status` from another terminal. Supported platforms can run a daemon without `--foreground`; platforms without fork should use foreground execution or a service manager. Closing a browser does not stop Cron.

## Pause and stop

```bash
ms-agent cron pause JOB_ID
ms-agent cron resume JOB_ID
ms-agent cron stop
```

Pausing a job differs from stopping the scheduler. Neither reverses completed side effects. `ms-agent cron remove JOB_ID` removes a job; verify history/artifact backups first. Do not assume every missed run is replayed after a restart.

## Declarative jobs

`ms-agent cron import` reads job declarations. When moving machines, check job storage, workspace, time zone, environment, and credentials. A job ID alone does not reproduce its environment. See [CLI reference](../development/cli-reference.md).
