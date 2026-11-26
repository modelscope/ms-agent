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

File memory suits bounded notes; vector/external backends require additional dependencies, credentials, and persistence. **The WebUI locks a project's memory backend once memory has been enabled.** Global defaults apply to new projects and do not migrate existing data. Back up first, then configure and verify a new project when another backend is needed. Do not move live databases or copy active lock files.

```yaml
memory:
  unified_memory:
    storage:
      backend: file
```

This is a core configuration fragment, not a replacement for UI operations. See [Memory](../core/memory.md) for storage and extension interfaces.

## Models for vector memory

Vector memory uses two distinct model roles:

| Setting | Responsibility | Selection |
| --- | --- | --- |
| Fact-extraction model | Extract reusable facts from conversation | Follow the conversation model or choose a provider and chat model |
| Embedding model | Encode memories for vector retrieval | Pin a provider and embedding model, or use local offline embeddings |

Set new-project defaults in **Settings → Personalization → Memory settings**, or configure a project when creating it or editing its settings. Choose a suggested model or enter a served ID directly. In [Model settings](model-settings.md), mark its purpose as **Chat / fact extraction** or **Embedding**. Models marked as embedding cannot be used for chat, and the memory configuration check rejects explicitly mismatched purposes. The default recall count is 10 per turn; the UI accepts values from 1 to 50.

**Check memory configuration** checks credentials, endpoints, and model purposes. If valid, it sends small requests to the selected remote embedding service to check the vector dimension; these calls may incur a charge. The project form also runs this check before creating a vector-memory project or saving changed memory model settings. If the check fails, the form does not submit. Local checks can read model metadata; actual first use still needs the model downloaded. Verification neither creates a memory store nor calls the extraction model, so embedding success does not verify the entire memory pipeline. Changing providers or models requires a new check.

Local mode requires `fastembed`. For a PyPI installation, install it in the same Python environment as the WebUI:

```bash
python -m pip install fastembed
```

For source installations, run `uv sync --locked --extra local-embed` in `webui/backend/` instead.

Restart the service and allow the first model download to finish. Remote embeddings use the selected provider's saved or environment credentials. An unusable explicit choice reports an error rather than silently selecting another service.

The embedding model is pinned after the store is built; changing the conversation model does not change an existing store's embedding source. If an explicit embedding-model change causes a mismatch, use **Rebuild** on the project memory card to re-embed existing entries. The old store is backed up, and the replacement is installed only after it is ready. Rebuilding embeddings does not change the memory backend. Global defaults only seed new projects, not existing stores.

## Missing or stale knowledge

Check enabling, scope, pending background writes, capacity, and whether the selected backend performs automatic extraction. Vector-memory status exposes missing credentials, failed embedding checks, and model mismatches. Fix configuration, verify again, and try the next turn. If memory initialization fails, the conversation can continue without silently falling back to file memory. A reply that omits a fact does not prove a failed write; inspect stored content/backend state. Allow necessary writes to finish before shutdown instead of treating scheduled work as saved.

Next: [Personalization](../core/personalization.md), [Storage](../development/storage.md).
