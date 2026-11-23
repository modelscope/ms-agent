# Agents

`LLMAgent` coordinates model calls and tool execution. It is more than a model client: tools, prompts, permissions, skills, sessions, and memory participate in its lifecycle. Start with the [Python SDK](../get-started/python-sdk.md) for a runnable example.

## A task's lifecycle

```{mermaid}
flowchart TD
 A[Prepare model and runtime] --> B[Load tools, permissions, hooks and skills]
 B --> C[Load memory, retrieval and session]
 C --> D[Assemble prompt and context]
 D --> E[Call model]
 E --> F{Tool calls?}
 F -->|Yes| G[Authorize, execute and record]
 G --> D
 F -->|No| H[Save reply and handle new input]
 H --> I{Continue?}
 I -->|Yes| D
 I -->|No| J[Finish and release resources]
```

Cancellation, errors, and round limits also affect completion. Interactive callbacks may wait for another user message; finishing one reply is not necessarily the end of the session.

## Configure and construct

```python
from ms_agent.agent import LLMAgent
from ms_agent.config import Config

config = Config.from_task('agent.yaml')
agent = LLMAgent(config=config)
```

The loader uses `type` to select an agent. `code_file` can load a custom implementation and requires explicit trust in external code. Use the workflow loader for workflow configuration instead of treating it as an ordinary single-agent configuration.

## Results and cancellation

- Non-streaming `await agent.run(query)` returns messages; the last item is not guaranteed to be displayable text.
- Streaming returns an async generator that the consumer must close correctly. See [Messages and events](messages-events.md).
- Clean up owned tool connections in `finally`. Propagate cancellation rather than reporting a partial turn as completed.
- The class default round count and `max_chat_round: 9999` in the bundled YAML are different layers. Set an application-specific budget explicitly.

## Choose an extension point

| Change | Start with |
| --- | --- |
| Available operations | [Tools](tools.md) |
| Python lifecycle behavior | [Callbacks](callbacks.md) |
| Event-driven script checks | [Hooks](hooks.md) |
| Model context or durable knowledge | [Context](context.md), [Memory](memory.md) |
| Task division and dependencies | [Subagents](subagents.md), [Workflows](workflows.md) |

Prefer these interfaces before subclassing the agent. Replacing the execution loop also means owning its cancellation, persistence, and cleanup behavior.

Implementation: `ms_agent/agent/llm_agent.py`, `loader.py`, `runtime.py`.
