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

Closing a browser does not necessarily stop backend work. Stop the service with Ctrl-C in its terminal; reactivate the environment and run `ms-agent ui` next time. Source changes may trigger a frontend rebuild, while valid existing builds are reused.

This workspace is not a universal launcher for every domain application. Run specialized workflows through their [application guides](../applications/deep-research.md). See [Deployment](deployment.md) for remote access and the lack of built-in login.
