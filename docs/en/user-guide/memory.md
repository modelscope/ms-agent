# Memory management

Memory holds knowledge and preferences worth reusing across sessions, not a complete conversation backup. Use [session history](projects-sessions.md) for original conversations and [context management](../core/context.md) for input length.

## Inspect project memory

Inspect “Memory” on the right of the project overview. Disabled memory and an empty enabled store are distinct states; a loading failure requires checking the backend.

To start with file memory:

1. Open **Settings → Personalization → Memory settings**.
2. Enable memory for new projects and select the “File” default backend. These defaults do not change existing projects.
3. Return to the workspace and create a test project using the plus button beside “Projects”.
4. Confirm that the new project's memory area shows “File” and an edit button.

The global personalization profile is not the same store as project memory. Verify project and scope before editing.

## Edit or remove entries

1. For file memory, click its edit button to open “Edit memory”.
2. Switch to source mode, edit the Markdown into short, specific facts, and save.
3. Inspect the project overview, then refresh to confirm persistence. Remove obsolete notes by editing the corresponding text; preserve unrelated content. Back up before using “Reset”, which is not an ordinary save.
4. File memory is read each turn; saving does not resend an in-flight request. Verify its effect in the next turn. Vector backends manage entries rather than one Markdown document.

Do not store keys, identity documents, complete private files, or large logs. Remote backends may send data to external services; inspect configuration first.

## Choose a backend

File memory suits bounded notes; vector/external backends require additional dependencies, credentials, and persistence. **The WebUI cannot change a project's memory backend after creation.** Global defaults apply to new projects and do not migrate existing data. Back up first, then configure and verify a new project when another backend is needed. Do not move live databases or copy active lock files.

```yaml
memory:
  unified_memory:
    storage:
      backend: file
```

This is a core configuration fragment, not a replacement for UI operations. See [Memory](../core/memory.md) for storage and extension interfaces.

## Missing or stale knowledge

Check enabling, scope, pending background writes, capacity, and whether the selected backend performs automatic extraction. A reply that omits a fact does not prove a failed write; inspect stored content/backend state. Allow necessary writes to finish before shutdown instead of treating scheduled work as saved.

Next: [Personalization](../core/personalization.md), [Storage](../development/storage.md).
