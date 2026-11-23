# Saving and recovering credentials

When you save a model or search API key in WebUI, MS-Agent encrypts registered credential fields and decrypts them when calling the provider. Normal use requires no extra password. An **API key** is a provider credential; the **master key** belongs to the instance and encrypts those credentials.

This page describes the current implementation; use a package or image containing the feature. Encryption protects configuration copied without its master key. It does not protect someone with both files, or replace authentication, HTTPS, or process isolation.

## Save and update a key

1. Enter and save the provider key under [Model settings](model-settings.md). The first nonempty credential save creates the default master key. If creation fails, saving fails without falling back to plaintext.
2. Reopening the editor does not prefill the key. It shows unset, configured, or unavailable; management responses contain neither plaintext nor ciphertext.
3. Editing names, endpoints, or model parameters does not require re-entering the key. Replacing an API key reuses the current master key; it does not rotate it.
4. Send a short message to verify access. “Configured” means saved, not that provider permissions and quota are valid.

In management requests, an omitted key or `null` preserves the value; an empty string explicitly clears it. Custom clients must distinguish these cases rather than treating an empty input as “keep unchanged.”

## Upgrade from an older version

Stop services sharing the data and back up before upgrading. Follow [Deployment](deployment.md) to retain data and any existing master key. Migration happens automatically after starting the new WebUI:

| Trigger | Scope |
| --- | --- |
| WebUI backend startup | Global `settings.json` and every registered project, including unopened projects |
| Later configuration reads | Global model/tool settings readers check subsequently imported legacy configuration; SDK resolution checks the current project |
| Configuration saves | Encrypt new credentials before writing; retain existing ciphertext |

Migration changes only registered credential fields, preserves other settings and messages, and creates no additional plaintext backup. A normal upgrade requires neither API-key re-entry nor a vector-store rebuild: chat, compaction, file memory, fact extraction, and embedding consumers recover the original key when needed. Managed configuration must be writable, with either a creatable default key directory or a valid external master key.

**Upgrade WebUI, TUI, CLI, and SDK installations sharing a home or project together.** They default to `~/.ms_agent` for the same OS user; opening another terminal does not isolate settings. Different homes can still share a project. Older versions cannot read ciphertext. Roll back with pre-upgrade data and its matching runtime, not an older runtime writing migrated files.

Migration completes per file. A malformed or unwritable file, or one mixing plaintext with undecryptable ciphertext, remains unchanged while other files can migrate. WebUI logs incomplete migration and keeps management available. **An accessible page does not prove migration completed**; repair and retry before sharing configuration.

## Locate the master key

| Setting | Default or requirement |
| --- | --- |
| `MS_AGENT_HOME` | Application home; defaults to `~/.ms_agent` |
| Default master key | Normalized home path plus `.secrets/master.key`, usually `~/.ms_agent.secrets/master.key` |
| `MS_AGENT_SECRET_KEY_FILE` | Optional pre-provisioned Fernet key file; read-only mounts are supported |
| `MS_AGENT_SECRET_KEY` | Optional Fernet master key value injected by the platform |

Choose at most one external source. An explicitly empty value, missing file, or invalid key produces an error without falling back to the default. External keys are not copied into application data. Docker defaults to `/data`, with its key at `/data.secrets/master.key`; see [deployment examples](deployment.md#credential-volumes) for persistence and external key mounts.

## Back up, export, and share

| Operation | Required handling |
| --- | --- |
| Upgrade, recreate a container, or relocate your service | Retain application data, actual project files, and the same master key; control access separately and restore the matching pair |
| Share a project or template | Clear credentials and exclude the actual master key source; encryption provides additional protection for copied configuration |
| Import a sanitized template | Enter your own API key, using the recipient's existing master key or one created on first save |
| Import ciphertext alone | Restore the original key, or explicitly discard old credentials and reconfigure |

Exporting only application home usually excludes the adjacent default key. Exporting its parent, the entire user home, or a container may include both. Exporters must account for the **actual key source**, not just a fixed filename. External products such as ModelScope Playground own their export integration; encryption does not establish that they clear credentials.

## Recover unavailable credentials

First check the selected home, key source, and file permissions, then restore the original master key. Existing messages remain readable, but calls requiring undecryptable credentials fail. Decryption errors do not trigger environment-key fallback or automatic master-key replacement. Configurations without a saved API key retain their existing environment resolution rules.

If you deliberately want to discard saved credentials, stop services using these directories and run the following, replacing the path with the actual application home:

```bash
python -m ms_agent.config.secrets reset --home /path/to/ms-agent-data --confirm
```

This clears registered fields in global settings and every registered project, preserving provider, model, and project definitions and messages. Add `--project /path/to/project` for an unregistered project. The scope is all specified storage, not just the current conversation.

An existing master key is never replaced. If the default key was lost and old ciphertext has been cleared, the next new credential save creates one. External sources must still be repaired. Reset cannot recover old API keys without their original master key.

## Protection scope

Managed provider, LLM, search, memory extraction, and embedding keys are covered. Registered fields in project `.ms_agent/config.yaml`, `settings.local.json`, and old `memory/*.yaml` files are also handled; new history snapshots strip credentials. `${...}` references retain their resolution semantics.

Arbitrary source `agent.yaml`, dotenv files, MCP env/headers, custom tool fields, message bodies, logs, and existing backups are not comprehensively covered. New fields require integration; see [Credential storage design](../development/credential-storage.md).
