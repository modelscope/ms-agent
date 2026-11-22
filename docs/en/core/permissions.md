# Permissions

MS-Agent separates tool safety rules, user authorization, and event extensions. These apply to managed tool calls, not a universal OS sandbox. Directly executed external code does not automatically receive equivalent protection.

## Checks around a call

```{mermaid}
flowchart TD
 A[Tool call and arguments] --> B[Tool and MCP availability]
 B --> C[SafetyGuard path and command rules]
 C --> D{Denied?}
 D -->|Yes| X[Return denial]
 D -->|No| E[PreToolUse hook]
 E --> F[PermissionEnforcer decision]
 F --> G{Allowed?}
 G -->|No| X
 G -->|Yes| H[Execute tool]
 H --> I[PostToolUse hook and result]
```

Network commands are default ask rules, not an irrevocable blacklist. Without an interactive handler, operations requiring confirmation are denied. Do not remove all protections to work around a configuration issue.

## Retain default protections

```yaml
permission:
  mode: ask
  allow_network: false
  safety_rules:
    allowed_directories: ["${PROJECT_ROOT}"]
    path_validation:
      read_policy: loose
```

| Mode | Decision on uncertain calls |
| --- | --- |
| `ask` | Ask the user; the TUI default |
| `auto` | Model assessment; `decision_provider` can select the current model or an injected assessment agent |
| `full-access` | Allow ordinary uncertain calls while retaining safety denials and mandatory asks |

Base configuration defaults to `auto`; interfaces can override it. Legacy names remain accepted: `restricted` / `interactive` map to `ask`, `delegate` maps to `auto`, and legacy `strict` maps to `full-access`. Aliases do not preserve every historical behavior. Assessment failure, timeout, or an unresolved decision still requires denial or human fallback rather than automatic authorization.

## Not every list is additive

Explicit `safety_rules.patterns`, `sensitive_paths`, `sensitive_read_paths`, and `dangerous_removal_paths` replace their defaults. Empty lists remove those protections. Omit them unless deliberately customizing. Outer `ask_rules` and inner safety lists have different merging semantics.

Allowed locations also depend on workspace and temporary-directory policy. `allow_temp_dir` allows system temporary workspaces by default. Loose/strict read policy differs from write scope; sensitive-read and sensitive-write rules protect different risks.

## Confirmation and deployment boundaries

Review command, target paths, and scope before approval. “Always allow” may remember authorization for future calls; use it deliberately. Hook scripts, direct tool calls, and operations inside remote MCP services are not equivalent to full local-path validation through this pipeline.

Remote services still need authentication, network isolation, and suitable container boundaries. A UI permission selector is not a reason to expose the server publicly.

Next: [Execution environments](execution-environments.md), [Hooks](hooks.md). Implementation: `permission/config.py`, `safety.py`, `enforcer.py`, `tools/tool_manager.py`.
