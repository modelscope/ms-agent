# Skill installation and updates

WebUI and SDK clients share `ms_agent.skill.management` for managed skill installation, provenance, update checks, replacement, and restore. `SkillCatalog` still handles runtime discovery and loading. Installing a package does not execute its scripts.

## WebUI workflow

1. In Settings or a project's Skills panel, choose **Add skill → Install from link**.
2. Paste a GitHub repository / subdirectory URL or a ModelScope Skill or collection page. Choose a global or project location and select the skills to install. Already installed or conflicting candidates cannot be overwritten through this flow.
3. If the static scan flags risks, review its findings and confirm before installing.
4. Use **Check for updates** or the **Updates** filter. Review changes file by file before confirming an update.
5. To revert, choose **Restore previous version** from the details menu and review the restore preview.

Files that differ from their installed baseline show **Local changes**. Updates and restores back up the actual current files before replacing them. Only the most recent backup is retained; an update with no content changes does not consume it.

Previously imported managed skills support **Link source**. Identical content only needs a provenance record. If content differs, the original version remains unknown and replacing the files requires confirmation. Standard directories and explicit external paths retain their existing discovery behavior and are not upgraded in place.

Collections expand into individually selectable skills. Unavailable entries show their own errors without blocking the rest. For entries with the same runtime name, choose one; **Select all** selects only unambiguous entries. Each installation keeps its own update and restore history. Later membership changes do not add or remove installed skills.

## Sources and versions

Supported sources are public GitHub repositories / subdirectories and ModelScope Skills entries or `/collections/owner/name` collection links. GitHub refs are resolved against the repository, including branch names containing `/`. Branches track new commits; tag and commit links remain pinned. When GitHub's anonymous API is rate limited, the provider attempts a public Git query, which requires an available `git` executable.

ModelScope installations record the Skill repository's commit and download that exact commit. The provider also accepts `@owner/name` and `modelscope://owner/name`, with optional `@revision#subdir` on the latter. When authentication is needed, the backend reads `MODELSCOPE_API_KEY` from its environment; credentials are never stored in provenance records.

Mirrored ModelScope entries typically use `@owner/name`, while directly uploaded entries use `owner/name`. Installation resolves and stores the actual `registry_id`; subsequent checks and downloads stay bound to that entry. Older records retain their mirrored identity. Initial resolution can recover a missing or extra `@`, but an unavailable installed source never silently switches identities. Authenticated installation and updates of privately uploaded entries have also been verified.

A changed commit triggers content comparison. Update availability covers every managed file in the skill, including scripts, assets, binary files, and executable permissions. Changes elsewhere in the repository do not create false updates. Internal content fingerprints are comparison keys, not user-facing version numbers.

The open app checks global skills and the current project on entry and when it becomes visible again, caching successful checks for 24 hours. Automatic checks can be disabled in the Skills panel's **More** menu; manual checks remain available. Failed checks preserve installed files and previous results. No scheduled checks run while the service is closed.

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
