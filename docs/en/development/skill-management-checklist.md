# Skill management: manual checklist

Start this branch's WebUI and create an isolated test project without overwriting everyday skills. See the [WebUI guide](../user-guide/webui.md) for startup and [design and implementation](skill-management.md) for the code and execution boundaries.

## Installation and sources

| Done | Action | Expected result |
| --- | --- | --- |
| ☐ | Choose Add skill → Install from link and enter a public GitHub repository/subdirectory | Real candidates, inspectable sources and destination; multiple candidates can be selected |
| ☐ | Enter a ModelScope Skill page | Provenance retains its exact entry ID and commit, visible in details |
| ☐ | Enter `https://modelscope.cn/collections/Gaodekaifangpingtai/gaodekaifangpingtai-skill` | Current collection candidates and repository sources appear; unavailable entries have individual errors |
| ☐ | Select all in a collection with conflicting names, then choose one in a conflict group | Unambiguous candidates are selected; conflicting entries cannot overwrite each other |
| ☐ | Install several candidates, reviewing static findings when required | Per-item progress; successful items appear in the chosen scope; installation executes no packaged scripts |
| ☐ | Inspect the same source again | Installed candidates cannot be selected again; other sources with the same name show conflicts |
| ☐ | Import locally, then link a source in details | Identical content only adds provenance; different content requires explicit backup/replacement confirmation |

## Updates, restore, and execution boundaries

Use a repository you control: publish and install V1, then commit V2. A `SKILL.md` and a plain file containing a version marker are sufficient; no permanent example project is needed. Do not modify third-party repositories.

| Done | Action | Expected result |
| --- | --- | --- |
| ☐ | Check for updates | Changed skill content shows an update; changes to other skills in the repository do not |
| ☐ | Review file changes and confirm an update | Correct text diffs; recognizable binary/permission changes; concise success feedback |
| ☐ | In the next turn of the same conversation, request an actual read of the skill's version marker | A tool reads the new content, visible in its call record |
| ☐ | After using the test skill, update while idle, then send only “continue” | Model input and raw session history contain the internal notice; the model reloads the skill; the user bubble contains only “continue” |
| ☐ | Continue without another edit; then restart the service, edit, and continue | No repeated reminder for unchanged files; new changes remain detectable after restart |
| ☐ | Queue or steer during a reply and attempt an update; stop, update, and resume | Continuous execution blocks updates; stopping permits them; queued skill calls use fresh content and carry a reminder |
| ☐ | Restore the previous version, then check again | V1 is restored and the update becomes available again |
| ☐ | Add a local custom file before updating | Local changes are shown and preserved by default; after confirmed replacement, restore can recover the custom file |
| ☐ | Edit local files after preview, then apply | The old plan expires as stale and requires a new preview |
| ☐ | Update or delete during a model task in the same scope | A task-running error; retry works after completion or stopping |
| ☐ | Repeat updates and restore for one collection member | Only that installation changes; collection membership changes do not add/remove local files |

## Cancellation, failures, and presentation

| Done | Action | Expected result |
| --- | --- | --- |
| ☐ | Cancel during download, then reopen | No partially installed directory or late progress |
| ☐ | Retry a partially failed batch | Successful items stay installed; only unfinished items are retried |
| ☐ | Simulate a list failure, then retry | Existing cards remain; initial failure is not presented as an empty list |
| ☐ | Change global/project scope while loading | Old responses do not replace the new scope |
| ☐ | Disable automatic checks, then check manually | Automatic checks stop; manual checks still work |
| ☐ | Switch languages, light/dark themes, and use a narrow window | Long sources remain readable, no horizontal overflow, usable scrolling and footer actions |

Use automated tests for interrupted transactions, failed message persistence, notice retries after cancellation, malicious archives, credential redirects, and concurrency. Do not inject these faults into an everyday workspace. Verify notices from model input or raw session records, not solely from the model's self-report. Public sources change; check actual membership and commits instead of relying on a fixed candidate count.
