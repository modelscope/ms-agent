# Credential encryption: design and deployment

[中文](secret_storage_zh.md)

## Purpose and decisions

Managed API keys used to appear as plaintext in settings, project configuration and historical snapshots. MS-Agent now uses **Fernet field encryption with an instance master key stored separately from application data**. Stored values use `enc:v1:`; only credential consumers decrypt them. New history snapshots remove credentials and restore them from current configuration.

This protects encrypted credentials when application or project files are copied without the master key. It does not protect a compromised process, another process with the same file access, or exports containing both data and the key. Authentication, HTTPS and process isolation remain separate requirements.

| Decision | Rationale |
| --- | --- |
| Fernet from `cryptography`, owned by the SDK | Standard authenticated encryption shared by WebUI, TUI and SDK |
| One instance key, created on first nonempty credential save | Minimal user and operational overhead |
| Default key directory beside the normalized home | A data-directory-only export excludes the key |
| Registered field paths; ciphertext retained in config objects | Preserve readable JSON/YAML and prevent plaintext write-back |
| New snapshots strip credentials; old snapshots migrate | Reduce new copies while protecting existing files |
| Explicit failure when the original key is unavailable | Never send ciphertext as a key or silently regenerate a replacement |
| No OS keychain, KMS integration or automatic rotation in this version | Consistent local and Docker behavior; platforms can inject an external key |

Writes use file locks and atomic replacement. Migration creates no additional plaintext backup. The version prefix allows future format changes; it does not implement automatic key rotation.

## Locations and key sources

| Data | Location / behavior |
| --- | --- |
| Application home | `MS_AGENT_HOME`, default `~/.ms_agent` |
| Default master key | Normalized home path plus `.secrets/master.key`, default `~/.ms_agent.secrets/master.key` |
| Global settings | `$MS_AGENT_HOME/settings.json`: registered fields encrypted |
| Project settings | `<project>/.ms_agent/config.yaml` and optional `settings.local.json`: registered fields encrypted |
| History YAML | `<project>/.ms_agent/memory/*.yaml`: old credentials migrated; new snapshots strip credentials |
| Messages | Existing JSON/JSONL content retained; no general message encryption |

Legacy `.ms-agent` and `.memory` directories are supported. Arbitrary source `agent.yaml` files are not automatically rewritten. On Linux/macOS the default key directory is `0700` and key file `0600`; symlinks at the key file or its parent directory are rejected. Home aliases resolve to the same canonical home. Windows ACLs require separate validation.

Choose at most one external source:

- `MS_AGENT_SECRET_KEY_FILE`: a pre-provisioned Fernet key file; read-only mounts are supported and recommended for Docker.
- `MS_AGENT_SECRET_KEY`: the Fernet key value injected by an existing secret-management system.

An explicit empty, missing or invalid source fails without falling back to the default. External keys are not copied into application data. These two variables are removed from Node SSR, shell and LSP child environments; this reduces inheritance but does not isolate processes with the same file permissions.

## User and runtime behavior

Saving a key passes through WebUI/TUI management into the SDK protected writer. Configuration remains encrypted on disk and in the configuration objects. Model, discovery, search, title, extraction and embedding consumers decrypt the selected value immediately before use. Management responses expose only status and masks, never plaintext or ciphertext; validation errors omit submitted key values.

| Operation | Behavior |
| --- | --- |
| First key save | Create the instance key and persist ciphertext; fail without plaintext persistence if creation is impossible |
| Reopen an editor | Never prefill the key; show unset, configured or unavailable |
| Edit unrelated settings | Omitted / `null` key retains the stored value |
| Replace a key | Encrypt the new API key using the existing master key |
| Explicitly clear | Empty string clears; old duplicate model-block keys are removed |
| Resume a conversation | Preserve messages; WebUI uses current model, tool and memory credentials |
| Change / lose the master | Invalidate WebUI runtime reuse and report credential errors |
| TUI / SDK use | Share protected storage, including TUI search settings and model discovery |

Decryption failure does not fall back to an environment credential. Configurations without a saved key continue to follow the SDK's normal environment resolution rules.

## Migration and recovery

WebUI startup checks global settings and every registered project, including unopened projects. SDK resolution checks global settings and the current project; management reads check subsequently imported global settings. Only registered sensitive fields change. Migration is idempotent and preserves other configuration and messages.

Migration is per file, not an instance-wide transaction. Malformed files, or files mixing plaintext with ciphertext that cannot be decrypted, remain unchanged and produce an error; healthy files can still migrate. WebUI keeps management available and logs incomplete migration. Such an instance must not be treated as fully protected for export. SDK parsing fails explicitly when configuration cannot be handled safely.

If the master key is lost, restore the original first. Messages remain readable. Metadata-only edits and clearing ciphertext do not require generating a missing default key. Existing managed ciphertext blocks automatic default-key creation.

To deliberately discard saved credentials, stop the service and run:

```bash
python -m ms_agent.config.secrets reset --home /path/to/ms-agent-data --confirm
```

This clears registered fields in global settings and all registered projects while preserving definitions and messages. Add `--project /path/to/project` for unregistered projects. It never replaces an existing master key. If the default key was lost, the next new credential save creates one after clearing; external sources must still be repaired. This cannot recover old API keys.

Upgrade WebUI, TUI and SDK sharing a home together. Older versions cannot read ciphertext. Existing backups and manual copies are outside migration. A rollback needs pre-upgrade data and its matching runtime, rather than an old runtime writing the migrated home.

## Docker and export integration

The default Docker home is `/data`; its key is `/data.secrets/master.key`.

**Separate persistent volumes:**

```bash
docker run -d --name ms-agent-ui \
  -p 8000:8000 \
  -e MS_AGENT_HOME=/data \
  -v ms-agent-data:/data \
  -v ms-agent-secrets:/data.secrets \
  YOUR_IMAGE:TAG
```

**Platform-managed, read-only key file:**

```bash
docker run -d --name ms-agent-ui \
  -p 8000:8000 \
  -e MS_AGENT_HOME=/data \
  -e MS_AGENT_SECRET_KEY_FILE=/run/secrets/ms-agent-master \
  -v ms-agent-data:/data \
  --mount type=bind,src=/secure/ms-agent-master,dst=/run/secrets/ms-agent-master,readonly \
  YOUR_IMAGE:TAG
```

Use an image containing this feature; the examples do not assert that a published image already includes it. Provision a valid Fernet key readable by the runtime user for the second option. Follow the [WebUI deployment guide](../webui/README.md) for authentication or a protected gateway, HTTPS, permissions and one API worker.

| Operation | Required agreement |
| --- | --- |
| Restart, upgrade or recreate | Preserve data and the same master key; mounting only `/data` loses the default key on recreation |
| Private backup or relocation | Retain both, control access separately, restore the matching pair |
| Export / share a template | Clear credentials and exclude the actual key source, not merely a particular filename |
| Export only `/data` or a project | Encrypted fields remain protected; exporting a parent directory, whole user home or container may also copy the key |
| Import a sanitized template | Enter new credentials; reuse the recipient's key or create one on first save |
| Import ciphertext without its key | Restore the original key, or explicitly discard old credentials and reconfigure |

The SDK ms-agent Agent Hub adapter clears registered credentials on import and upload. ModelScope playground export is a separate system whose owners must implement the same contract. Encryption reduces the damage of incomplete filtering; it does not certify an external export workflow.

## Coverage and extension

Registered fields include provider API keys; generic, vendor-specific and vision LLM keys; search engine and summarizer keys; memory extraction and embedding keys. `${...}` references retain their existing resolution semantics instead of materializing environment credentials on disk.

Arbitrary source YAML, `.env`, MCP env/headers, custom tool fields, message bodies, logs and existing backups are not comprehensively covered. New history also applies generic secret stripping, which is not a guarantee of detecting every secret.

Register storage paths and integrate their consumers together:

```python
from ms_agent.config.secrets import register_secret_field, resolve_secret

register_secret_field('tools.my_tool.access_token')
# Persist configuration through write_managed_config.
token = resolve_secret(config.tools.my_tool.access_token, config=config)
```

`ms_agent/config/secrets.py` owns encryption, migration and reset; configuration managers own protected writes; `llm/credentials.py` and tool consumers resolve credentials; `utils/history_secrets.py` strips new history. WebUI `bootstrap.py`, `providers.py` and `runtime.py` handle migration, management status and runtime invalidation. New whole-file writers must use the protection layer.

Distribution builds have a separate file boundary: discover Python packages only under `ms_agent`, exclude temporary scripts, runtime history, application data, master-key directories and local `.env` files, and clear the previous library build before rebuilding. `.gitignore` alone does not protect wheel/sdist contents. These exclusions prevent known runtime artifacts from entering releases; credential scanning is still needed before publishing.
