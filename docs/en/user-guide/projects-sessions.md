# Projects and sessions

A project associates a working directory with instructions and selected resources. A session records an ongoing conversation and execution history. One project can have several sessions without duplicating its files.

## Open a project

Create a project or open a directory from the WebUI project area. Review its contents before granting access. On a remote WebUI, paths belong to the server. The Default project is useful for a first test; it is not arbitrary access to the browser computer's files.

Choose a recognizable name and verify the actual workspace before requesting writes. Put reusable conventions in project instructions and the immediate task in a message. See [Skills and MCP](skills-mcp.md) for project resource selection.

## Separate pieces of work

- Use **New conversation** for independent context.
- Expand the project and reopen history to continue.
- Use available naming/management menu actions; inspect deletion scope before confirming.
- In the TUI, `/sessions` lists project sessions, `/resume <number-or-ID>` reopens one, and `/new` starts another.

Changing projects changes workspace and scope, not just the page title. Unsaved editor drafts are not automatically artifacts of another conversation.

## Branch from a completed reply

Click **Branch** beside the copy button below a completed reply to continue in a new conversation with history through that point. Titles advance as `Original title (2)`, `(3)`, and so on. A divider links back to the source. You can branch from an earlier completed reply while the source is running, but not from unfinished or interrupted turns.

The fork inherits tool results, valid summaries, and the source's currently selected model. Opening it does not change the global default model, and its composer starts empty. Conversation records are independent; project files, settings, and memory remain shared. This is not a workspace snapshot or rollback. Unsubmitted source drafts remain when switching back in the same tab, but not after refresh.

## Save and recover

The SDK persists completed messages and session data. Input drafts and unsaved file edits have different lifecycles. Save files before leaving the page. Reopening history after a service restart resumes conversation, not every interrupted external operation.

Inspect existing artifacts before retrying to avoid duplicate writes or external requests. Context compaction preserves original logs, but the model may receive only the compacted view.

## Back up and delete carefully

Back up application-home settings, metadata, and sessions together with the chosen workspace. Deleting conversation records and deleting project files are different operations. Read the confirmation rather than assuming either total deletion or total preservation.

If history is missing, check `MS_AGENT_HOME`, workspace, interface, and whether a message was actually submitted. Do not delete storage directories as a first attempt to reset the UI.

Next: [Session mechanisms](../core/sessions.md), [Storage](../development/storage.md), [Deployment and backups](deployment.md).
