# Skill installation and updates

Install skills, check their sources for updates, review changes, and restore previous files in the WebUI. Installation downloads files without executing packaged scripts.

## WebUI workflow

1. In Settings or a project's Skills panel, choose **Add skill → Install from link**.
2. Paste a GitHub repository / subdirectory URL or a ModelScope Skill or collection page. Choose a global or project location and select the skills to install. Already installed or conflicting candidates cannot be overwritten through this flow.
3. If the static scan flags risks, review its findings and confirm before installing.
4. Use **Check for updates** or the **Updates** filter. Review changes file by file before confirming an update.
5. To revert, choose **Restore previous version** from the details menu and review the restore preview.

Files that differ from their installed baseline show **Local changes**. Updates and restores back up the actual current files before replacing them. Only the most recent backup is retained; an update with no content changes does not consume it.

Updates are blocked while related tasks or consecutive queued turns are running. Update after execution finishes or is stopped, then continue the same conversation: the model receives an internal change notice on its next turn, instructing it to reload affected skills before using them. You do not need to start a new conversation or announce the update. Steering continues the current task; queued messages retained after stopping use the current version when resumed. Finding an available remote update alone does not notify the model.

Previously imported managed skills support **Link source**. Identical content only needs a provenance record. If content differs, the original version remains unknown and replacing the files requires confirmation. Standard directories and explicit external paths retain their existing discovery behavior and are not upgraded in place.

Collections expand into individually selectable skills. Unavailable entries show their own errors without blocking the rest. For entries with the same runtime name, choose one; **Select all** selects only unambiguous entries. Each installation keeps its own update and restore history. Later membership changes do not add or remove installed skills.

## Sources and versions

Supported sources are public GitHub repositories / subdirectories and ModelScope Skills entries or `/collections/owner/name` collection links. GitHub refs are resolved against the repository, including branch names containing `/`. Branches track new commits; tag and commit links remain pinned. When GitHub's anonymous API is rate limited, the provider attempts a public Git query, which requires an available `git` executable.

ModelScope installations record the Skill repository's commit and download that exact commit. The provider also accepts `@owner/name` and `modelscope://owner/name`, with optional `@revision#subdir` on the latter. When authentication is needed, the backend reads `MODELSCOPE_API_KEY` from its environment; credentials are never stored in provenance records.

Mirrored ModelScope entries typically use `@owner/name`, while directly uploaded entries use `owner/name`. Installation resolves and stores the actual `registry_id`; subsequent checks and downloads stay bound to that entry. Older records retain their mirrored identity. Initial resolution can recover a missing or extra `@`, but an unavailable installed source never silently switches identities.

A changed commit triggers content comparison. Update availability covers every managed file in the skill, including scripts, assets, binary files, and executable permissions. Changes elsewhere in the repository do not create false updates. Internal content fingerprints are comparison keys, not user-facing version numbers.

The open app checks global skills and the current project on entry and when it becomes visible again, caching successful checks for 24 hours. Automatic checks can be disabled in the Skills panel's **More** menu; manual checks remain available. Failed checks preserve installed files and previous results. No scheduled checks run while the service is closed.

See [design and implementation](../development/skill-management.md) for SDK integration and execution boundaries, and the [manual checklist](../development/skill-management-checklist.md) for acceptance testing.
