# Skill management: manual checklist

Start the service using the [WebUI guide](../user-guide/webui.md) and use an isolated test project. Install V1 of a skill you control, then publish V2, keeping a readable version marker in its files. See [implementation notes](skill-management.md) for boundaries.

## Installation and sources

| Done | Action | Expected result |
| --- | --- | --- |
| ☐ | Install from GitHub and ModelScope Skill URLs into global and project scopes | Inspectable candidates, sources, and commits; correct destination; scan confirmation when required |
| ☐ | Select multiple skills from a [public collection](https://modelscope.cn/collections/Gaodekaifangpingtai/gaodekaifangpingtai-skill), then update one member when an update is available | Individual errors; independent updates and restore; membership changes do not add/remove local files |
| ☐ | Repeat installation, or select all conflicting candidates and then choose one | Installed items cannot be selected again; conflicting names do not overwrite each other |
| ☐ | Import locally, then link a source | Identical content adds provenance; different content requires confirmed backup/replacement |

## Updates, restore, and execution boundaries

| Done | Action | Expected result |
| --- | --- | --- |
| ☐ | Publish V2, check updates, review changes, and confirm | Target skill shows an update; text, binary, and permission changes are recognizable; other skills' changes cause no false update |
| ☐ | After using V1, update while idle and send only “continue” in the same conversation | Internal notice reaches the model; a tool reads V2; the user bubble still contains only “continue” |
| ☐ | Continue without edits; then restart, edit, and continue | No duplicate notice in the first case; new changes detected in the second |
| ☐ | Queue or steer during a reply and attempt update/delete; stop, update, and resume | Continuous execution blocks mutations; stopping permits updates; resumed skill calls use fresh content |
| ☐ | Add a custom local file, update, then restore | Local changes block replacement by default; after confirmation, restore recovers custom files and checks find the update again |
| ☐ | Edit files after preview, then apply | Stale plan rejected; new preview required |

## Cancellation, failures, and presentation

| Done | Action | Expected result |
| --- | --- | --- |
| ☐ | Cancel a download; retry a partially failed batch | No partial installation or late progress; successful items are not repeated |
| ☐ | Switch scope while loading; retry a failed list request | Old responses do not replace the new scope; failures retain cards and do not appear as empty lists |
| ☐ | Disable automatic checks, then check manually | Automatic checks stop; manual checks work |
| ☐ | Switch languages, light/dark themes, and use a narrow window | Readable sources, no page overflow, usable scrolling and action buttons |

Verify notices from model input, tool calls, and session records, not only the model's self-report. Automated tests cover interrupted transactions, failed message writes, malicious archives, credential redirects, and concurrency; do not inject these faults into everyday workspaces.
