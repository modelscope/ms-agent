
# RFC: Hooks Executor Extensions (HTTP / Prompt / Agent)

> **Status: Draft (proposal)** · Related current state [Hooks](../../core/hooks.md)
>
> Current state: the Hooks events, protocol, decision mapping, matcher, and multi-platform loader are **implemented** (see the Hooks module), but **only the `command` executor has landed**. The `http / prompt / agent` config fields can be parsed but the backends are not registered; `SubagentStop` is configurable but not triggered at runtime.

## Background and motivation

The `command` executor covers the "subprocess policy script" scenario but has limits: a remote policy must bring its own script, a lightweight judgment must spawn a process, and multi-step validation cannot be expressed. The three new executors fill these scenarios while **reusing the same `HookResult` pipeline and `ResponseAdapter` output contract** (see the Hooks module and protocol implementation), adding no new semantics to the upper layer.

## 1. Unified routing

`HookExecutor` registers `command | http | prompt | agent` in parallel according to `hooks.enabled_executors`; a non-enabled type returns `action='error'` (reason: `Hook type '…' not enabled`) at execution time rather than being silently dropped, and `hooks doctor` warns about it. Global YAML additions: `allowed_http_hook_urls` (`undefined` = unrestricted, `[]` = all forbidden, otherwise a glob allowlist), `http_hook_allowed_env_vars`, `default_model` (for prompt/agent).

## 2. `HttpHookExecutor` (P2)

**Purpose**: POST the Canonical event JSON to `handler.url`; the response body goes through the same `ResponseAdapter`.

```json
{
  "type": "http",
  "url": "https://policy.example/v1/pre-tool",
  "timeout": 10,
  "headers": { "Authorization": "Bearer ${POLICY_TOKEN}" },
  "allowedEnvVars": ["POLICY_TOKEN"]
}
```

**Semantics**: URL allowlist check → header env-var interpolation (`allowed_env_vars` ∩ global) → POST (`Content-Type: application/json`, `max_redirects=0`) → 2xx handed to `ResponseAdapter`; non-2xx/network error → `error` (`deny` when `fail_closed`).

**Security**: URL allowlist; SSRF rejects private/link-local addresses (exempted when going through a proxy/sandbox); strip CR/LF/NUL from headers; forbid open redirects. Compared to a raw `curl`: unified timeout/allowlist/SSRF/contract, so an enterprise can allow only URLs without shipping scripts.

## 3. `PromptHookExecutor` (P2)

**Purpose**: a single LLM call (not a full agent loop). Substitute the event JSON into `$ARGUMENTS` / `${ARGUMENTS}`, and require a structured return `{ok: bool, reason?: string}`.

**Semantics**: `ok:true` → `pass` (**not** an automatic `allow`); `ok:false` → `deny` (`block` under a Stop event); parse failure → `error` (unless `fail_closed`).

**Constraints**: does not recursively trigger `UserPromptSubmit`; does not inject the full history by default; no ToolManager. Cursor's `type: prompt` can share this executor. **Open**: skipping the permission prompt requires an explicit `permissionDecision: allow`; if history is injected later, the token cost must be evaluated.

## 4. `AgentHookExecutor` (P3)

**Purpose**: a short-lived sub-agent (with tools) doing multi-step validation, especially for **Stop** events ("did the task really finish?"), or expensive `PreToolUse`.

**Config**: `type: agent`, `prompt`, `model`, `max_turns` (default 20, hard cap 50), `timeout`.

**Semantics**: filter dangerous tools (`agent_tool` / `plan_mode` …); `permission_mode=dontAsk` (only within this hook sub-session); structured `{ok,reason}` → `deny`/`pass`; a Stop `ok:false` → `block`; timeout/no structured output → `error`.

**Security**: a restricted tool surface; forbid spawning further sub-agents / editing hooks / opening a new top-level session; the transcript path is readable subject to the allow rules.

## 5. Others

- **`SubagentStop` runtime triggering**: configurable today but not triggered; add `HookRuntime.run_subagent_stop` and its trigger point.
- **`hooks doctor`**: diagnose non-enabled types, missing allowlists, matcher mismatches, etc.

## Explicitly out of scope

- Hermes in-process Python plugins, OpenClaw TS modules (`api.on()` typed hooks) — beyond the executor security boundary; at most "detect + suggest conversion".
- A dedicated UI rendering block for hook-attached content (`hook_attachments`) (a UI concern, not this RFC).

## Open questions

- How should the default model for the Prompt/Agent executors be sourced (`hooks.default_model` vs the main LLM) and how should a cost cap be set?
- How should the HTTP executor declare its SSRF exemption boundary under an enterprise-proxy scenario?
