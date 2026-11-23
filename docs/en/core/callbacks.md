# Callbacks

Callbacks extend the Python execution lifecycle in-process. They receive runtime state and messages directly, making them useful for metrics, input control, and response processing. [Hooks](hooks.md) provide an event/script contract; [plugins](plugins.md) assemble extension resources.

## Lifecycle positions

| Method | Position |
| --- | --- |
| `on_task_begin` | Task begins |
| `on_generate_response` | Before calling the model |
| `on_tool_call` | After model generation, before tool execution |
| `after_tool_call` | After tool execution |
| `on_task_end` | Task ends |

Methods are asynchronous. In particular, `on_generate_response` is not a model-completed notification; follow the actual call position rather than inferring timing from its name.

## Minimal implementation

```python
from ms_agent.callbacks.base import Callback

class TurnCounter(Callback):
    async def on_generate_response(self, runtime, messages):
        self.count = getattr(self, 'count', 0) + 1
```

Defining a class does not register it. After creating `agent` and before calling `run()`, create `counter = TurnCounter(config)` and register it with `agent.register_callback(counter)`. Read `counter.count` after the task. Built-in callbacks can be selected in YAML:

```yaml
callbacks:
  - input_callback
```

`input_callback` waits for more input after a reply. It suits interactive work but can leave a batch process waiting. For an unattended minimal call, use `callbacks: []` and an explicit round limit.

## Boundaries

Callbacks can modify messages in place. Preserve roles, tool-call/result pairs, and context structure. Avoid blocking the event loop, release owned resources on failure as well as completion, and keep credentials and unredacted requests out of logs.

Next: [Agents](agents.md), [Hooks](hooks.md). Implementation: `callbacks/base.py`, `callbacks/utils.py`, `agent/llm_agent.py`.
