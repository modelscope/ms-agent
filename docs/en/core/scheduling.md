# Scheduling

Scheduling starts tasks at defined times rather than keeping one model conversation running indefinitely. Cron separates job definitions, time calculation, execution records, and notifications. A running scheduler process performs the actual triggers.

## Lifecycle

```{mermaid}
stateDiagram-v2
 [*] --> Enabled: Create or import
 Enabled --> Running: Due or manually triggered
 Running --> Enabled: Complete and calculate next run
 Running --> Failed: Execution fails
 Failed --> Enabled: Continue schedule or intervene
 Enabled --> Paused: Pause
 Paused --> Enabled: Resume
```

These states explain the flow; consult job records for actual persisted fields. One-shot timestamps, intervals, cron expressions, and time zones have different semantics. Check the next execution time before leaving jobs unattended.

## Validate an expression

```python
from ms_agent.cron.parser import parse_schedule

schedule = parse_schedule('every 30m')
assert schedule.kind == 'interval'
assert schedule.interval_seconds == 1800
```

This only parses time; it does not run a task. See [Scheduled tasks](../user-guide/scheduled-tasks.md) for CLI steps.

## Execution and storage

The service reads job records, selects due work, and invokes an executor. Heartbeats and notifications are separate concerns. Creating a job does not start the scheduler; closing a browser does not necessarily stop a background daemon.

Verify restarts, timeouts, concurrency, and artifact persistence independently. Do not assume missed runs are replayed or external operations are idempotent. Periodic jobs need explicit output locations, budgets, and stop procedures.

Model and permission settings must suit unattended execution. Operations needing confirmation may be denied without a handler. Test one harmless job manually and inspect history before scheduling repeats.

Implementation: `cron/parser.py`, `repository.py`, `scheduler.py`, `executor.py`, `service.py`. Next: [Permissions](permissions.md), [Deployment](../user-guide/deployment.md).
