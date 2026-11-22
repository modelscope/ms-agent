# Context management

Context is the message window sent to the model for the current call, not the complete session record or long-term memory. `ContextAssembler` builds a visible window from `SessionLog` and applies strategies in order. Original messages remain in the log.

## How compaction works

```{mermaid}
flowchart TD
  A[Complete session log] --> B[Select visible window]
  B --> C[Prune tool output]
  C --> D[Summarize history]
  D --> E{Compaction occurred?}
  E -->|Yes| F[Append view and event]
  F --> G[Advance visible boundary]
  E -->|No| H[Convert to model messages]
  G --> H
```

Pruning reduces older large tool results; summarization uses a model to condense history. Compacted views and metadata are appended to the log and survive restarts. Summaries can lose detail: an intact log does not mean the model sees everything in every call.

## Configure built-in strategies

```yaml
session_log:
  enabled: true
compaction:
  enabled: true
  context_limit: 128000
  reserved_buffer: 20000
  strategies:
    - name: tool_output_pruner
      enabled: true
      prune_protect: 40000
    - name: summary_compactor
      enabled: true
```

These are context budgets, not guarantees about every model's actual window. Reserve room for replies; protect recent tool output to avoid repeated reads. Setting `compaction.enabled: false` disables automatic compaction while session recording can remain enabled.

## Implement a strategy object

A strategy follows the `ViewStrategy` contract: `name` and `apply()`. This minimal example preserves the window and tests the extension contract without model calls:

```python
from copy import deepcopy
from ms_agent.session.context_assembler import ViewStrategy

class KeepWindow:
    name = 'keep_window'

    def apply(self, visible, all_msgs, config):
        return deepcopy(visible), None

assert isinstance(KeepWindow(), ViewStrategy)
```

Pass objects to `ContextAssembler(session_log, strategies=[...])`. Returning compaction metadata asks the assembler to record the event and persist the new window. Do not mutate `all_msgs` or remove tool calls while leaving orphaned results.

**The YAML factory currently recognizes only `tool_output_pruner` and `summary_compactor`.** A new name does not automatically import an implementation. Custom objects must be connected at a programming integration point.

## Memory and manual compaction

A pre-compaction callback may flush memory, but asynchronous writing is not guaranteed to finish before summarization. Durable knowledge belongs to the [memory backend](memory.md). Terminal `/compact` manually prunes tool output; it is not identical to the automatic summarization pipeline.

Next: [Sessions](sessions.md), [Prompt assembly](prompts.md), [Storage](../development/storage.md). Implementation: `session/context_assembler.py`, `session/strategies/`, `LLMAgent._build_compaction_strategies()`.
