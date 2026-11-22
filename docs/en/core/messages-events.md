# Messages and events

Messages describe conversation content; events describe what happens during execution. Keeping them separate prevents duplicating full responses in a UI or presenting tool-argument generation as completed execution.

## Different responsibilities

| Data | Typical use | Important distinction |
| --- | --- | --- |
| `Message` | Model input, agent results, session-log conversion | Roles, content, tool calls/results, multimodal data |
| `AgentEvent` | Incremental output for TUI, WebUI, and protocol adapters | `type` discriminates events; `to_dict()` creates serializable data |

Tool results must correspond to preceding calls. Preserve those pairs when transforming context. UI display state is not a replacement for complete conversation records.

## Observe a reply

```{mermaid}
sequenceDiagram
 participant User
 participant Agent
 participant UI
 User->>Agent: Submit request
 Agent-->>UI: turn_started
 Agent-->>UI: content_delta / reasoning_delta
 Agent-->>UI: tool_call_composing
 Note over Agent,UI: Argument generation is not execution
 Agent-->>UI: tool_call_started / tool_call_completed
 Agent-->>UI: content_end
 Agent-->>UI: turn_completed
```

Not every turn produces every event. Failure and cancellation have separate paths; the final text fragment alone is not proof of success.

```python
from ms_agent.ui.events import ContentDelta, TurnCompleted

assert ContentDelta(text='hello').to_dict() == {
    'type': 'content_delta', 'text': 'hello'
}
assert TurnCompleted(turn_id='demo').to_dict()['type'] == 'turn_completed'
```

## Consume streams correctly

The async generator returned by `await agent.run(query, stream=True)` yields message views, not simply text deltas. Track what has already been displayed or use the SDK event contract for a UI. The TUI's `--emit-events` option records events as JSONL for inspecting actual order.

The WebUI adapts SDK events into HTTP streaming responses. Do not bypass that adapter by sending internal Python objects to the browser. Event changes require checking SDK, TUI, ACP translation, and WebUI consumers together.

Next: [Agents](agents.md), [Sessions](sessions.md). Implementation: `llm/utils.py`, `ui/events.py`, `ui/input.py`.
