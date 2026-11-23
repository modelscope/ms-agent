# Context management

Context is the message window sent to the model for the current call, not the complete session record or long-term memory. `ContextAssembler` builds a visible window from `SessionLog` and applies strategies in order. Original messages remain in the log.

## How compaction works

```{mermaid}
flowchart TD
  A[Complete session log] --> B[Select visible window]
  B --> C[Optional tool-output pruning]
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
  compression_ratio: 0.85
  strategies:
    - name: tool_output_pruner
      enabled: true
      prune_protect: 40000
    - name: summary_compactor
      enabled: true
```

Summarization is the default strategy. Tool-output pruning is opt-in because it can remove unique evidence. Automatic compaction normally starts at 85% of the effective window; input limits and output reservation can trigger it earlier. `compaction.enabled: false` disables automatic maintenance, not recording, hard-budget checks, or explicit manual compaction.

## Input and output budgets

The effective window takes the smallest valid cap from model metadata, `llm.context_limit`, and legacy `compaction.context_limit` / `session_log.context_limit`. When none is known, it falls back to 128000. A manual cap can tighten a known window, not enlarge what the service supports.

Output reservation follows the final request's `max_tokens`, `max_completion_tokens`, or `max_output_tokens`. Without an explicit value, the default is bounded by 8192, the model's output limit, and one eighth of the window. Input capacity subtracts that reservation. Legacy `reserved_buffer` overrides the ratio-based threshold; it is not the request's output-token parameter.

## Context estimates

Session compaction and legacy `ContextCompressor` share local budget estimates. Without a usable usage anchor, they estimate readable text, tool schemas, and media references. Images use a media allowance, not base64 string length; an attachment and its inline representation are not counted twice.

API usage anchors apply to the historical request they describe; later messages and images still add to the estimate. Replaced prompts, media, or pruned outputs cannot reuse invalidated usage as the new window size. Original usage remains available for cost records. The context ring is a request-budget estimate, not a provider invoice or a precise provider-specific tokenizer count.

Text summaries omit image pixels and explicitly note the omission. They are not substitutes for image evidence; protected latest-image inputs must remain intact.

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

Automatic compaction, SDK `/compact`, and the WebUI button share `LLMAgent.compact_context()`. Manual compaction runs at an input boundary without adding a user message or invoking the main conversation response. The WebUI has no slash-command routing; use the context-ring menu instead.

Summarization protects system messages, the latest input, and complete protected tool-call groups. A complete window and completion event are appended together; replay accepts only validated windows. Original history stays intact. Summary input can be split to fit the budget, and empty, truncated, or non-shrinking results do not replace the window.

With [memory](memory.md) enabled, long-term facts are extracted before committing compaction. Ordinary extraction failure retains old memory and retry sources while allowing a valid summary to commit. Cancellation stops the whole operation.

## Failure and continuation

A failed summary preserves the original context. An unchanged window and budget do not repeat the same failed summary automatically each turn. Explicit manual compaction or changed input/budgets can retry; cancellation does not suppress future attempts. If context still exceeds the hard input budget, the SDK saves the pending request. The WebUI's **Retry compaction and continue** and SDK `ResumeContext` continue it without appending another user message. A new instruction replaces the pending request. If the latest input itself is too large, shorten it or choose a larger-window model rather than trying to compress protected input away.

Next: [Sessions](sessions.md), [Prompt assembly](prompts.md), [Storage](../development/storage.md). Implementation: `session/context_assembler.py`, `session/strategies/`, `llm/token_budget.py`, `LLMAgent._build_compaction_strategies()`.
