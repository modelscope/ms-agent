# Skill management: design and implementation

The SDK owns installation, updates, and restore; WebUI provides interaction and asynchronous HTTP APIs. See the [user guide](../user-guide/skill-management.md) and [manual checklist](skill-management-checklist.md). TUI retains its independent notifications.

<a id="product-scope"></a>
<a id="interaction-conventions"></a>

## Code map

| Entry | Responsibility |
| --- | --- |
| `ms_agent/skill/management/service.py`, `models.py` | Source snapshots, plans, installation records, file transactions, recovery |
| `providers.py`, `content.py` in that directory | Source resolution, downloads, archive validation, fingerprints, diffs |
| `usage.py`, `io.py`, `operations.py` in that directory | File leases, cancellation safety, bounded concurrency, progress |
| `ms_agent/config/skills_manager.py`, `skill/loader.py` | Existing imports, deletes, and reads share the file boundary |
| `ms_agent/skill/notice.py`, `agent/llm_agent.py` | Change detection and durable turn delivery |
| `webui/backend/app/backends/ms_agent/` | `skill_management.py` adapts management APIs; `chat.py` and `conversations.py` refresh at execution and retain queue leases |
| `webui/frontend/app/components/resources/` | `SkillsFromLinkModal` installs; `SkillCollection` lists; `SkillUpdatePanel` previews, updates, and restores; `SkillUpdateChecks` checks automatically |
| `webui/frontend/app/lib/skillManagement.ts` | Polling, cancellation, late-response isolation, errors |

## Installation data flow

`inspect_source()` resolves and downloads a source into a candidate snapshot. `prepare_install()` fixes the selection, checks conflicts, and scans files. `apply_plan()` validates and commits each item, invalidates indexes, and emits resource events.

`prepare_update()`, `prepare_restore()`, and `prepare_link()` produce plans for the same apply path. `installations(scope)` returns persistent installation IDs; `diff(plan_id, item_id, path)` reads file changes on demand.

## Consistency and execution boundaries

- **Plans:** bind scope, candidate commit, local content, and installation generation for 30 minutes. Apply validates them again and returns `PLAN_STALE` on drift. `local_changes_policy="abort"` is the default; use `"replace"` only after confirmation. Risk review requires `acknowledge_risk=True`, otherwise apply returns `SAFETY_REVIEW_REQUIRED`.
- **Commits:** stage on the same filesystem, back up, rename, and save records. Batches commit per item; retries reuse successful receipts. Unchanged content preserves the backup. Cancellation waits for an in-progress commit to finish or recover. Hosts call `recover(scope)` at startup and `aclose()` at shutdown.
- **Execution:** SDK/WebUI use `SkillUseLease` to block replacement or deletion in active scopes with `SKILL_BUSY`; short read locks protect discovery and reads. Consecutive queues and steering retain the lease until completion or stopping. Other hosts can use `SkillUseLease([manager.tree(scope)])`; direct editor writes bypass it.

WebUI refreshes the catalog and expands skills when a task actually starts, avoiding stale queued content. The SDK compares available skills with the session's `skill_surface.json`, adds a reminder to model input, and advances the baseline only after message persistence. Chat bubbles retain the original text. Unchanged content and remote update availability alone produce no notice.

`skills.update_notice` freezes the skill list in the system prompt. WebUI also enables `skills.update_notice_in_sdk` for SDK delivery. TUI keeps its independent `live_config.py` notices to avoid duplicates.

## Sources and revisions

GitHub resolves real refs, including branch names containing `/`. Branches track commits; tags and commits remain pinned. Anonymous API rate limits trigger a public Git fallback, requiring system `git`.

ModelScope stores the exact `registry_id`, distinguishing native `owner/name` from mirrored `@owner/name`, and downloads by commit. Older records remain supported without switching identities on later checks. Besides page URLs, it accepts `@owner/name` and `modelscope://owner/name[@revision][#subdir]`. Collections are discovery inputs; each installation stores its member source.

Update fingerprints cover relative paths, bytes, and executable bits, including scripts, assets, and binary files, excluding caches such as `.git`. Changes to other skills in the repository do not trigger updates. Fingerprints are not display versions; ordinary list reads do not access the network or calculate them.

Files live in `<MS_AGENT_HOME>/skills` or project `.ms_agent/skills`. Sibling `skill-installs.json` stores provenance; `skill-state/` holds backups and journals. Source snapshots, plans, and receipts live in global `skill-state/`. Existing `skills.json` semantics remain intact.

## Inputs, credentials, and resource limits

Reject source URLs with credentials or query parameters, escaping archive paths, links, device files, and duplicate entries. Send `MODELSCOPE_API_KEY` only to trusted ModelScope APIs, never to redirected download hosts or into records/errors. Installation executes no scripts; static scanning is not a runtime sandbox.

Downloads: 64 MiB. Extraction: 128 MiB / 5,000 entries. Collections: 100 entries/candidates, four concurrent resolutions, 256 MiB retained content, and 30/240-second listing/member timeouts. Text diffs: 256 KiB / 2,000 lines per file.

## SDK example

```python
import asyncio
import uuid

from ms_agent.project.paths import global_home
from ms_agent.skill.management import SkillManagementService, SkillScope


async def main():
    manager = SkillManagementService(str(global_home()))
    scope = SkillScope()  # Use SkillScope("/path/to/project") for a project.
    try:
        preview = await manager.inspect_source(
            scope, "https://github.com/anthropics/skills/tree/main/skills/pdf")
        plan = await manager.prepare_install(
            scope, preview.id, [preview.candidates[0].id])
        # The host presents provenance, file changes, and plan.items[].safety.
        results = await manager.apply_plan(plan.id, request_id=uuid.uuid4().hex)
        for item in results:
            print(item.status, item.error)
        print(await manager.check_updates(scope, force=True))
    finally:
        await manager.aclose()


asyncio.run(main())
```

Before applying a plan, the host presents provenance, file changes, and scan findings and obtains the relevant confirmations.

## HTTP API

All paths start with `/api/skills`. Long-running operations return 202 and an operation ID; clients poll status and per-item results, cancel, or retry.

| Endpoint | Purpose |
| --- | --- |
| `POST /sources/inspect`, `/install-plans` | Discover candidates, prepare installation |
| `POST /update-checks` | Check updates |
| `POST /{skill_id}/update-plans`, `restore-plans`, `link-plans` | Prepare update, restore, source linking |
| `GET /plans/{id}`, `/plans/{id}/diff` | Read plans and file diffs |
| `POST /plans/{id}/apply` | Apply with a request ID and confirmation options |
| `GET /operations/{id}`, `DELETE /operations/{id}` | Inspect or cancel |
| `GET /management-settings`, `PATCH /management-settings` | Automatic-check settings |

## Regression testing

SDK coverage lives in `tests/skill/test_management*.py` and `test_notice_lifecycle.py`; HTTP and conversation coverage in `webui/backend/tests/test_skill_management.py` and `test_skill_notice.py`. Tests generate skills in temporary directories.

See the [WebUI README](https://github.com/modelscope/ms-agent/blob/main/webui/README.md) for development checks. Use the [manual checklist](skill-management-checklist.md) for real models, public sources, and presentation; mocked results do not replace that validation.
