# Skill installation and updates

Manage skills from Settings or a project's Skills panel. Installation downloads files without executing packaged scripts.

## WebUI workflow

1. Choose **Add skill → Install from link** and enter a GitHub repository/subdirectory or ModelScope Skill/collection URL.
2. Choose global or project storage and select skills. Review any static scan findings before installing. Choose one candidate per conflicting name; installed skills cannot be overwritten here.
3. Click **Check for updates**, open an item in **Updates**, and review its file changes before confirming.
4. To revert, select **Restore previous version** in the details menu. Only the latest pre-replacement files are retained, including local edits.

**Local changes** require explicit replacement confirmation. Previously imported managed skills support **Link source**: identical content only adds provenance; different content requires confirmed backup and replacement. External directories are not upgraded in place.

Updates are blocked while tasks or queued turns are running. Update after completion or stopping, then continue the same conversation: the model receives an internal notice on its next turn. Retained queued messages also use the new version when resumed. Detecting an available update alone does not notify the model.

## Sources and versions

| Source | Update behavior |
| --- | --- |
| Public GitHub repository / subdirectory | Branches track new commits; tags and commits stay pinned. Only changes to the target skill produce an update |
| ModelScope Skill | Download by repository commit; set `MODELSCOPE_API_KEY` on the backend when authentication is required |
| ModelScope collection | Select multiple members, with individual errors. Installed members update and restore independently; membership changes do not add or remove local files |

Automatic checks cover global and current-project skills when opening the app, entering a project, or returning to the app. Successful results are cached for 24 hours. Disable them in the Skills panel's **More** menu; manual checks remain available. No checks run while the service is closed. Failed checks retain existing files and previous results.

See [design and implementation](../development/skill-management.md) for integration, or the [manual checklist](../development/skill-management-checklist.md) for acceptance testing.
