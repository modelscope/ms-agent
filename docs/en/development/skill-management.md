# Skill management: design and implementation

The SDK owns installation and updates; WebUI adapts requests and status. See [installation and updates](../user-guide/skill-management.md) for user steps and the [manual checklist](skill-management-checklist.md) for acceptance testing.

## Product scope

Users can install from GitHub repositories or subdirectories and ModelScope Skill or collection pages into global or project storage. Each installation records its repository, tracked branch or pinned revision, commit, and content fingerprint. Existing local imports, directory discovery, and enable/disable behavior remain intact.

This release supports multi-select installation, manual and infrequent automatic checks, individual change previews, updates, local-edit protection, restore, and linking existing installations to a source. It does not include store search, unattended replacement, update-all, three-way merging, or multi-version history.

## Interaction conventions

One dialog covers the source URL, destination, candidate selection, and installation. Repository revision details expand on demand; ordinary lists show names, descriptions, sources, and necessary status.

Collections expand into individual repositories and their skills. Unreadable members show separate errors. Users choose one candidate within each conflicting name group; select-all skips unresolved groups. Installed or conflicting local names cannot be overwritten through installation. Each item commits independently and reports installed, installing, queued, or failed; retries retain successful results.

Lists use short labels such as updates, local changes, and check failed. A failed check retains previous results; a failed list request retains existing cards and offers retry. Late responses cannot replace a new scope or revive a cancelled operation.

Update and restore previews appear in the details drawer. Text diffs load on demand; binary and large files show change status. Replacing local edits requires explicit confirmation. Restore keeps the actual files from immediately before replacement, including local customizations.

## Sources and revisions

| Source | Tracking |
| --- | --- |
| GitHub repository / subdirectory | Resolve the default branch or longest matching real ref, including `/` in branch names; download by commit |
| GitHub tag / commit | Pinned revision; does not follow a branch |
| ModelScope Skill | Store the exact `registry_id`; native `owner/name` and mirrored `@owner/name` remain distinct; download by repository commit |
| ModelScope collection | Discovery only; each installation tracks its member repository; membership changes do not alter installed files |
| Existing managed local skill | Explicitly link a source; identical content only adds provenance, different content requires confirmed backup and replacement |
| Standard / explicit external directory | Retain existing discovery; do not upgrade in place |

A changed commit triggers comparison; it does not by itself mean a skill needs updating. Fingerprints cover relative paths, bytes, and executable bits, including scripts, assets, and binary files, while excluding known caches such as `.git`. They are comparison keys, not display versions.

Automatic checks run while the application is open, when entering a project or returning to the app. Successful results are cached for 24 hours; failures have a short backoff. Manual checks can force refresh. Ordinary list reads neither access the network nor calculate fingerprints.

## Consistency and execution boundaries

Previews bind the scope, candidate commit, content fingerprint, and installation generation for 30 minutes. Applying a plan validates them again; changed local files, installation state, or candidate content returns `PLAN_STALE` and requires a new preview.

File commits stage a directory on the same filesystem, retain the old files, rename into place, and save installation records and recovery journals. Startup recovers unfinished commits. Each skill succeeds or fails independently; a batch is not one transaction. An update with no content changes does not consume the backup.

SDK and WebUI turns hold filesystem usage leases. Replacement or deletion in a related scope returns `SKILL_BUSY`. The lease is released while waiting for the next user input and acquired again for the next turn. Short read locks protect discovery and reads from directory-replacement gaps. Cancellation waits for an in-progress file commit to finish or recover before removing its staging files.

Successful changes invalidate the skill index and publish existing resource events. Active turns retain stable files; later turns see new content. External SDK hosts should use `SkillUseLease` around their execution boundaries.

Updates, restores, manual edits, additions, and removals share the existing change-notice semantics. WebUI synchronizes the catalog and expands skill calls when a task actually starts. The SDK compares available skills with the session's `skill_surface.json`, adds an internal reminder to the model input, and advances the baseline only after the user message is persisted. The UI retains the original user text. Unchanged content and remote update availability alone do not generate reminders.

WebUI opts into SDK delivery with `skills.update_notice_in_sdk: true`. The existing `skills.update_notice` still controls notice mode and freezes the skill list in the system prompt. TUI retains its independent `live_config.py` notices and does not enable SDK delivery; its implementation and behavior remain unchanged, avoiding duplicate reminders.

Consecutive queued tasks retain the lease; steering continues the active task and creates no update window. Management can replace files after the queue finishes or is stopped. Retained queued messages use the current skills when resumed. Direct editor writes do not participate in leases and should be made while idle.

## Inputs, credentials, and resource limits

Only supported GitHub and ModelScope sources are accepted. Installation URLs containing credentials or query parameters are rejected. ModelScope tokens come from the process environment and are sent only to trusted ModelScope APIs; download redirects do not forward them to object storage. Provenance, receipts, and errors do not store tokens or raw request headers.

Archive paths must be relative and stay inside the destination. Links, device files, and duplicate paths are rejected. Downloads are limited to 64 MiB; extraction to 128 MiB and 5,000 entries. Collections allow 100 entries/candidates, four concurrent resolutions, and 256 MiB of retained content. Listing has a 30-second timeout and member resolution a 240-second timeout. Text diffs are limited to 256 KiB and 2,000 lines per file.

Static scans identify content requiring review. Installation writes files without executing packaged scripts; scanning is neither a runtime sandbox nor a guarantee of source trust.

## Code map

| Location | Responsibility |
| --- | --- |
| `ms_agent/skill/management/models.py` | Scope, source, candidate, plan, per-item result, and safe error contracts |
| `providers.py` | GitHub refs, exact ModelScope identities, collection pagination, commit downloads, credential boundaries |
| `content.py` | Bounded extraction, path validation, fingerprints including binary files and permissions, diffs |
| `service.py` | Discovery, preview, checks, install, update, link, restore, records, crash recovery |
| `usage.py` / `io.py` | Cross-process usage leases, short read/write locks, cancellation-safe file work |
| `operations.py` | Bounded operations, per-item progress, receipts, cancellation, interrupted status after restart |
| `ms_agent/config/skills_manager.py` | Existing local imports and deletes participate in the same write boundary |
| `ms_agent/skill/loader.py` | Managed directory discovery and reading use short read locks |
| `ms_agent/skill/notice.py` | Existing change detection and reminder wording, compatible session baselines |
| `ms_agent/agent/llm_agent.py` / `callbacks/input_callback.py` | Acquire leases during execution; release while waiting for input or exiting |
| `webui/backend/app/backends/ms_agent/chat.py` / `conversations.py` | Refresh and expand skills at execution; retain leases across queued turns |
| `webui/backend/app/backends/ms_agent/skill_management.py` | HTTP scope mapping, metadata, operations, index invalidation, resource events |
| `webui/backend/app/api/skills.py` / `schemas/skill.py` | Routes and validation without another download or transaction implementation |
| `webui/frontend/app/lib/skillManagement.ts` | Polling, cancellation, late-response isolation, business error messages |
| `SkillsFromLinkModal.tsx` | Repository/collection candidates, multi-selection, static review, per-item installation |
| `SkillCollection.tsx` / `SkillUpdatePanel.tsx` | Lists, filters, retry, change previews, updates, restore |
| `SkillUpdateChecks.tsx` | Infrequent checks driven by application visibility and scope changes |

## Installation data flow

1. `inspect_source(scope, source)` resolves a source and commit, downloads to staging, discovers candidates, and stores a source snapshot. Each collection candidate carries its own `source`; failed members carry safe errors.
2. `prepare_install(scope, snapshot_id, candidate_ids)` fixes the selection into a plan, checks names, copies candidates, and scans them. Repository and collection snapshots share `_candidate_source()`; the collection itself is not saved as an installed source.
3. `apply_plan()` validates the preview, review decisions, and scope lease, then commits files. Success records installation ID, runtime ID, provenance, fingerprint, and generation. Retries reuse successful receipts.
4. The adapter invalidates indexes and emits resource events; lists and later turns refresh.

Updates inspect the upstream commit, then compare the target skill's content, excluding changes elsewhere in the repository. `prepare_update()` and `prepare_restore()` share replacement plans. Restore retains one generation of actual pre-replacement files. `prepare_link()` adds provenance for managed local directories without guessing their original version.

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

`installations(scope)` returns persistent installation IDs. Use `prepare_update(scope, installation_id)` to prepare an update, `prepare_restore(...)` for a restore, and `prepare_link(scope, runtime_skill_id, source_snapshot_id, candidate_id)` to link an existing installation. `diff(plan_id, item_id, path)` returns a changed file's text diff; binary and large files expose status only.

Plans expire after 30 minutes and bind the candidate commit, local content, and installation generation. Apply validates them again and reports `PLAN_STALE` if they changed. The default `local_changes_policy="abort"` preserves local edits; pass `"replace"` only after explicit confirmation. A scan requiring review returns `SAFETY_REVIEW_REQUIRED`; pass `acknowledge_risk=True` after that review. Batch installs return per-item results, and retrying a plan does not repeat successful items.

SDK execution and WebUI turns share filesystem leases that prevent replacement in active scopes. Other hosts can use `SkillUseLease([manager.tree(scope)])` around their execution boundary. Commits use short locks; cancellation waits for an in-progress critical commit to finish or recover. Call `recover(scope)` during host startup and `aclose()` during shutdown.

Installed files remain in `<MS_AGENT_HOME>/skills` or a project's `.ms_agent/skills`. A sibling `skill-installs.json` stores provenance; a sibling `skill-state/` holds backups and recovery journals. Source snapshots, preview plans, and operation receipts are stored centrally in `<MS_AGENT_HOME>/skill-state/`. Existing `skills.json` source ordering and enabled/disabled behavior remain intact.

## HTTP API

| Endpoint, under `/api/skills` | Purpose |
| --- | --- |
| `POST /sources/inspect` | Discover candidates |
| `POST /install-plans` | Prepare selected candidates |
| `POST /update-checks` | Check a scope or installation |
| `POST /{skill_id}/update-plans`, `restore-plans`, `link-plans` | Prepare update, restore, or source linking |
| `GET /plans/{id}`, `/plans/{id}/diff` | Read a plan or file diff |
| `POST /plans/{id}/apply` | Apply with a request ID and explicit replacement/review decisions |
| `GET /operations/{id}`, `DELETE /operations/{id}` | Inspect or cancel an operation |
| `GET /management-settings`, `PATCH /management-settings` | Automatic-check settings |

Long-running work returns 202 and an operation ID. Status is queued, running, succeeded, partial, failed, cancelled, or interrupted. Failures use business error codes without returning upstream exceptions, credentials, or raw responses.

## Regression testing

Tests create skills in `tmp_path`; no committed version fixtures or publishing scripts are required.

| Test entry | Coverage |
| --- | --- |
| `tests/skill/test_management.py` | Install, update, restore, local edits, concurrency, recovery, leases, cancellation, idempotency |
| `tests/skill/test_management_providers.py` | Ref resolution, commit downloads, identity and credential boundaries |
| `tests/skill/test_management_collections.py` | Pagination, deduplication, unavailable members, conflicting names, independent updates, cancellation cleanup |
| `webui/backend/tests/test_skill_management.py` | HTTP lifecycle over real files and scope validation |
| `tests/skill/test_notice_lifecycle.py` | Change detection, session baselines, silent initialization, independent TUI delivery |
| `webui/backend/tests/test_skill_notice.py` | Both chat paths through SDK model input, display history, resume, queue, steering, cancellation, write failures |
| `webui/frontend/scripts/checkSkillOperations.ts` | Progress, partial failures, cancellation, late-response isolation |

Run the SDK suite with the repository's external-model skip level. Validate real model and registry flows separately; mocked results are not real end-to-end evidence:

```bash
MS_AGENT_HOME="$(mktemp -d)" TEST_LEVEL=-1 MS_AGENT_MODEL_CATALOG=local \
  PYTHON_DOTENV_DISABLED=1 MS_AGENT_WEBUI_BACKEND="$PWD/webui/backend" \
  webui/backend/.venv/bin/python -m pytest tests -q --import-mode=importlib
```

From `webui/backend/`, run `.venv/bin/python -m pytest tests -q`. From `webui/frontend/`, run `pnpm check:skills`, `pnpm typecheck`, and `pnpm build`. Real acceptance covers public sources, controlled upstream changes, same-session reads of updated content, cancellation, both languages, and light/dark themes.

Consult the delivery record for actual results, upstream merge status, and unresolved limitations. Do not commit test accounts, machine paths, session IDs, model transcripts, or temporary service URLs.
