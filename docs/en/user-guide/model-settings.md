# Model settings

Model setup has three steps: configure a provider connection, add a model, and select it for the conversation. A reachable page or “key configured” label does not establish successful model access.

## Built-in providers

1. Open **Settings → Model settings** and select a provider such as ModelScope.
2. Choose **Edit**, enter the API key, and save. Keys are write-only; not seeing plaintext does not mean saving failed.
3. Choose **Add model**, select or search a served model ID, and optionally set a display name. Enter an ID manually if it is not listed.
4. **Auto** image understanding follows model metadata; unknown models default to disabled. Enable it manually after confirming a custom deployment supports images.
5. Return to the conversation and select the provider/model below the input.

The display name is a UI label; the model ID goes to the service. Identically named models from different providers need not accept the same parameters.

## Custom endpoints

**Add provider** requires a unique ID, Base URL, and protocol; the display name is optional. OpenAI-compatible endpoints generally use an API root such as `/v1`; Anthropic endpoints use their actual service root. Do not substitute a dashboard URL or an arbitrary full chat/completions path.

Add a model after saving the provider. Review advanced parameters for the chosen protocol. Built-in URLs may not be editable; use a custom provider for a different endpoint.

## Defaults and session selection

The top of the settings page selects a default provider/model. An explicit selection differs from reopening an existing conversation with a saved selection. Restoring history does not mean resetting global defaults. Check the model displayed below the input before sending.

Configuration can refresh through change notifications across open pages. If a value looks stale, reopen the selector or refresh rather than repeatedly adding duplicate models.

## Reasoning, images, and context

For models with reasoning controls, choose a supported level in settings or beside the model name in chat. Sessions retain per-model selections. Explicit changes also update new-chat defaults; reopening history only reads saved session settings. Native reasoning parameters in advanced JSON override shortcuts, disabling the quick selector.

Image understanding supports **Auto / On / Off** overrides. When disabled, attachments pass only paths, not proof that the main model received image pixels. Audio, video, and PDF capability labels do not imply native upload support for those formats.

The context limit can tighten a known window or cap an unknown model; clear it to restore defaults. See [WebUI workspace](webui.md) for the context ring, manual compaction, and capability-data updates, and [Context management](../core/context.md) for budgets.

## Recover from errors

| Symptom | Check first |
| --- | --- |
| No models listed | Was a model added, not merely a key saved? |
| No model selected | Choose one in the conversation selector |
| 401/403 | Key, account access, model quota |
| 404 | Base URL, model ID, protocol |
| Parameter/image rejection | Advanced settings, supports_vision, service support |
| Timeout | Connectivity, proxy, timeout budget |

Do not include keys in screenshots or prompts. Test one text request without tools, then add attachments/tools to isolate failures.

See [Models](../core/models.md) for provider fields and routing boundaries.
