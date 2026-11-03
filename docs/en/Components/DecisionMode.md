# Decision mode (experimental)

Decision mode adds two helpers for longer tasks: selecting tool outputs when context approaches its limit, and checking evidence when execution appears repetitive or the agent is about to finish. The main model still interprets the task, calls tools and writes the answer. The decision model answers predefined questions; it cannot execute commands or grant permissions.

This is intended for tasks with substantial tool output and verification work. Short conversations usually make no decision calls. It does not guarantee correctness or lower latency: decisions, summaries, cache changes and original-output reads all have a cost.

## Enable it in WebUI

1. Configure a provider and its credentials in **Settings → Models**. For example, Bailian Token Plan uses `https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1` as its base URL.
2. In **Settings → Personalization → Decision model**, select that provider, enter `decision-model-preview`, and save. **Test connection** makes one small paid request; saving or selecting a mode does not call the model.
3. Create a conversation and choose **Decision** above the composer before sending. Select the main chat model separately; a decision model is not a chat model.

An explicit selection updates the default for future conversations. Each conversation locks its mode and policy when the server accepts its first execution, including runs that later fail or are cancelled. Create a new conversation to change modes. Restoring history does not change the global default; branches inherit their source profile. Credential rotation uses the provider's current key without copying it into the execution profile.

## SDK configuration

Configure a provider through the existing `ModelSettingsManager` or WebUI. Decision settings refer to its ID in `MS_AGENT_HOME/settings.json`:

```python
from ms_agent.config.decision import DecisionSettings
from ms_agent.project.paths import global_home

DecisionSettings(global_home()).update(
    decision={"provider": "ath", "model": "decision-model-preview"},
    default_execution_mode="decision",
)
```

For a directly constructed agent, add the following to its existing YAML. Keep the main model in the existing `llm` configuration:

```yaml
execution:
  mode: decision
decision:
  provider: ath
  model: decision-model-preview
  protocol: systemone
  policy_version: v1
  context:
    enabled: true
    trigger_ratio: 0.85
    target_ratio: 0.65
    keep_probability_max: 0.05
  supervision:
    enabled: true
    intervention_threshold: 0.95
session_log:
  enabled: true
compaction:
  enabled: true
  context_limit: 128000
  reserved_buffer: 20000
```

Set `context_limit` to suit the chat model and reserve room for output with `reserved_buffer`. These example values are not discovered model capabilities. Direct SDK/YAML use takes its mode from explicit configuration. WebUI uses the SDK's `SessionManager.prepare_execution()` for session locking. TUI uses the selected session's mode and freezes its decision profile when starting that session.

`DecisionSettings` validates configuration without probing the service. Decision mode requires session logging and reports an error if it is disabled. Supervision can operate independently when context compaction is disabled.

## Input and output

The initial adapter supports Bailian's compatible System One endpoint. It posts JSON to `base_url + /systemone`, without Chat Completions messages, text streaming or tool calls:

```json
{
  "model": "decision-model-preview",
  "state": {"test_result": {"return_code": 1}},
  "questions": {
    "passed": {"type": "noul", "instructions": "Did the test pass?"}
  }
}
```

Answers use the same question IDs, for example `answers.passed = {"type":"noul","noul":0.01}`. `noul` scores a proposition; `choice` returns an option ID and distribution; `score` returns a distribution over ordered criteria and its expected score. These scores have not been calibrated by this project and are not task completion percentages.

`DecisionRequest`, `DecisionResponse` and `DecisionClient` define the shared contract. `SystemOneClient` implements the wire protocol. Future adapters can implement that contract and declare their supported question types and input limits. The current implementation does not emulate this protocol with a chat model.

## Context reduction

The budget covers visible messages, tool definitions, reasoning fields and estimated image input. Without a reliable tokenizer, a conservative estimate is used and checked again before main-model generation. Below the trigger, no decision request is made.

- Preserve system instructions, user requirements, the latest two complete tool groups, unresolved explicit failures, images and signed messages.
- Evaluate the complete contents of other tool outputs. Replace an output with a short preview and source reference only when its full-content retention score is at most 0.05.
- If that candidate meets the target budget, commit it without summarization.
- Otherwise discard the selection candidate and summarize the pre-selection context with the same main model. Invalid answers, timeouts and unavailable services take this path too. Summarization uses at most four fragments by default and requests that reasoning be disabled.
- Commit one transaction only when the candidate reduces context, preserves valid tool exchanges and still matches its source revision. If protected input cannot fit the hard limit, stop explicitly instead of repeatedly compressing the same snapshot or discarding required evidence.

Original logs remain intact. `context---context_read` reads up to 8,000 characters per page using `ctx:<original seq>:<tool_call_id>`, within the current conversation or its valid branch. Standard mode defaults to bounded summaries. The agent's `/compact` command also summarizes; it does not trim old outputs by age.

## Execution review

Code first detects repeated actions, identical outputs or consecutive failures; a semantic check then decides whether to request reflection. Finish checks apply to tasks with tool execution and look for completion claims contradicted by an explicit failure or unmet requirement. Ordinary conversations without tools are not forced to continue.

A user task allows at most six process checks, two finish checks, two process reflections shared with rule-based checks, and one finish correction. Process reflections have a cooldown of three tool groups. Feedback references actual evidence through a fixed template and does not adopt instructions from tool output. User input, honestly reported blockers, cancellation, permission refusals and hard execution limits must remain effective.

Review precedes completion checkpoints, memory ingestion and waiting for input. Internal feedback does not start a new task or reset its budget. `decision_event` records counts, references and timing without duplicating full decision inputs. Default timeouts are two seconds for supervision and five seconds for context selection, with a short cooldown after repeated failures.

## Validation and limits

Offline tests are in `tests/decision/` and `webui/backend/tests/test_decision_mode.py`. Live checks require explicit opt-in and configured credentials:

```bash
MS_AGENT_HOME=/path/to/test-home python examples/capability/decision_model/sdk_smoke.py \
  --run --provider ath --model deepseek-v4.1-flash --output /tmp/decision-smoke.json
```

The script uses synthetic history to check the real protocol, selection or summarization, original-output recovery and finish supervision. It records actual scores and paths; uncertain selection may correctly fall back to a summary. These small cases do not establish speed, cost or success-rate improvements. Performance claims require a controlled comparison of standard mode, rules alone, summaries alone and full decision mode with fixed main-model and cache conditions.
