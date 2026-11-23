# WebUI workspace

The WebUI brings conversations, tool activity, and project files into one workspace. Install and configure a model through {ref}`Quick start <webui>`, then use this guide for everyday work.

## Start and continue a conversation

1. Select a project and choose **New chat**. The Default project is suitable for an initial test before opening your own directory.
2. Select a model below the input. Saving a provider is not enough: add a model and select it in the conversation.
3. Enter a task and press Enter. Begin with bounded read-only work before permitting changes.
4. Follow streamed replies and tool activity. Continue after completion or reopen a conversation from project history.

Saved messages remain accessible after refresh; unsent input and editor drafts are not durable records. If a request fails, retain the task, fix model settings, and retry rather than deleting the project first.

## Understand execution

Text, reasoning, and tool calls are distinct display items. A tool whose arguments are still being generated has not executed. Approval requests must be resolved before execution continues. During processing, inspect the current stage rather than equating silence with inactivity. Completed activity may collapse under “Processed”; expand it, the tool group, and an individual call to inspect arguments and results.

The permission selector controls interaction. **Always ask** is a suitable initial choice. Review tool, command, and target paths before approval. Approval offers “Reject”, “Run once”, and “Always run”; prefer one-time approval while learning. During generation, use the stop button beside the composer. You can send another message after interruption. Inspect artifacts after stopping; stop is not undo. Do not grant unrestricted access merely to suppress prompts.

## Add input while a task runs

Keep typing, attaching files, or selecting skills while the agent works. New messages queue by default and start separate tasks in order after normal completion. Choose **Steer** in **Settings → Personalization → Conversation behavior** to add later submissions to the current task after its current model response or dispatched tool batch finishes. Steering does not forcibly interrupt those operations or replace tool approval.

Pending messages appear above the composer and can be edited or withdrawn. Delivered messages move into the conversation and cannot be withdrawn. While running, an empty draft shows **Stop**; typing, attachments, or selected skills switch it to **Send**. Sending or clearing the draft restores **Stop** if the task is still active.

Stopping or task failure holds pending inputs and preserves existing artifacts. **Continue sending** releases them as new tasks, not resumed cancelled operations. You may also send another task while earlier inputs stay on hold. Refreshing, switching sessions, or disconnecting does not stop execution, and accepted inputs persist. A service restart restores pending inputs on hold until resumed. Unsubmitted composer drafts are different: they do not survive refresh.

## Model capabilities and context

Choose supported reasoning levels beside the model name and set image understanding to **Auto / On / Off**; see [Model settings](model-settings.md). Capability information comes from models.dev data bundled with the SDK. Source WebUI installations check for updates at startup; wheels/images use local data by default. **Settings → Models → Update catalog** downloads new data that takes effect after restarting the service. Failed updates preserve valid local data. Use `MS_AGENT_MODEL_CATALOG=local` for offline startup, or `bundled` to pin bundled data and disable updates.

The context ring shows the latest request's estimated input. Expand it for system-prompt, tool-definition, and message usage, or choose **Compact context**. Output reservation is separate; changing model/settings waits for the next request to refresh the estimate. Automatic compaction normally starts at 85% of the effective window. It neither deletes original logs nor adds a user message. Failure preserves old context; **Retry compaction and continue** resumes an oversized pending request. Keep important evidence in project files; see [Context management](../core/context.md).

## Files and attachments

Conversation attachments provide input for a request. Workspace files manage lasting project artifacts. These are separate entry points. Check model/service location before uploading private content.

Open **Workspace** and select a file to preview it. Markdown supports preview/source views. Save source edits with **Cmd/Ctrl+S**. The **Add files** menu offers new files, new folders, file uploads, and folder uploads. Downloads use your browser's download location.

Drafts can remain in the current page when switching files, but save before refreshing or choose **Save all and close** when closing the editor. If another program or agent changes the file, a recheck shows “Changed elsewhere”. Click it and confirm “Reload” to discard the local draft and read the disk version. Saving after a conflict notice may overwrite that disk version; do not repeatedly press save to dismiss the warning.

## Project settings and extensions

Project settings expose workspace, instructions, and skill/MCP scope. Global model, search, and personalization settings serve different purposes. Globally disabling a resource is not equivalent to leaving it unselected for one session.

- [Projects and sessions](projects-sessions.md): directories, history, deletion boundaries.
- [Model settings](model-settings.md): providers, models, defaults.
- [Skills and MCP](skills-mcp.md): installation/connections and enabling.
- [Memory management](memory.md): viewing, editing, and refresh timing.

## Leave the workspace

Closing the browser does not stop accepted session tasks; use **Stop** to interrupt them first. Stop the service with Ctrl-C in its terminal; reactivate the environment and run `ms-agent ui` next time. Source changes may trigger a frontend rebuild, while valid existing builds are reused.

This workspace is not a universal launcher for every domain application. Run specialized workflows through their [application guides](../applications/deep-research.md). See [Projects and sessions](projects-sessions.md) for branching, and [Deployment](deployment.md) for remote access and optional login.
