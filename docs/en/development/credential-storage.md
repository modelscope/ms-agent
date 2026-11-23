# Credential storage design

The SDK owns credential protection; WebUI, TUI, and configuration managers share it. The goal is to protect encrypted API keys when configuration or project files are copied alone, while retaining readable JSON/YAML structures. For user operations and recovery, see [Saving and recovering credentials](../user-guide/credentials.md).

## Design choices

| Choice | Rationale and boundary |
| --- | --- |
| Fernet field encryption from `cryptography` | Standard symmetric encryption with integrity checking; ciphertext uses an `enc:v1:` prefix |
| One master key per instance | Low local and Docker overhead; created when a nonempty credential first needs encryption |
| Default key in a sibling `.secrets` directory of normalized home | Exporting application home alone excludes the key; exporting its parent does not |
| Ciphertext retained in configuration objects; consumers decrypt as needed | Prevent plaintext write-back when unrelated settings change |
| Registered fields only | Avoid guessing which arbitrary strings are secrets; extensions integrate writes and consumers together |
| New history strips credentials; old history migrates | Reduce new copies and protect retained legacy snapshots |

There is no OS-keychain or KMS integration or automatic master-key rotation. Platforms can inject external keys. The prefix identifies the storage format; it does not implement rotation. Encryption cannot protect a compromised process, another process able to read the key, or disclosure of both data and key.

## Writes and calls

```{mermaid}
flowchart TD
  A["WebUI / TUI<br/>saves"] --> B["SDK encrypts<br/>fields"]
  B --> C["Config retains<br/>ciphertext"]
  C --> D["Status<br/>and mask"]
  C --> E["Decrypt<br/>before use"]
  E --> F[Provider API]
  K["Separate<br/>master key"] --> B
  K --> E
```

`write_managed_config()` reads the old configuration under a file lock, protects the replacement, and writes atomically with fsync. Key creation also uses locking and atomic replacement. Empty values do not create a key; `${...}` references are not resolved into plaintext credentials on disk.

LLMs, model discovery, search and summarization, titles, memory extraction, and embedding consumers decrypt selected credentials before use. Compaction and file memory reuse the main model client. WebUI restores history with current model, tool, and memory settings; the master-key fingerprint participates in runtime cache validation to invalidate stale decrypted state. Management responses and input-validation errors do not echo credentials.

## Migration files and triggers

| File | Handling |
| --- | --- |
| `$MS_AGENT_HOME/settings.json` | Migrate registered fields |
| `<project>/.ms_agent/config.yaml`, `settings.local.json` | Migrate registered fields |
| `<project>/.ms_agent/memory/*.yaml` | Migrate old snapshots; strip credentials before writing new ones |
| Equivalent legacy `.ms-agent/` files and `<project>/.memory/*.yaml` | Apply the same rules |

At WebUI startup, `migrate_home()` enumerates registered projects, including unopened projects and those outside home. Global settings readers perform subsequent migration, and `ConfigResolver` checks global settings and the current project. There is no periodic disk-wide scan; arbitrary source `agent.yaml`, backups, and unregistered fields are not rewritten by this mechanism.

`migrate_file()` uses file contents rather than an old-version marker. Existing ciphertext is not encrypted again. Mixed plaintext/ciphertext files must decrypt their existing ciphertext before replacement. Migration creates no additional plaintext backup and is not an instance-wide transaction: startup continues through other files and reports failures while WebUI keeps management available. SDK parsing raises errors instead.

## Master keys and failures

The default path appends `.secrets/master.key` to resolved home. On Linux/macOS, created directories use `0700` and files `0600`; symlinks at the default key file or its parent are rejected. Home aliases normalize to one key location. Windows ACL behavior requires separate validation.

`MS_AGENT_SECRET_KEY_FILE` and `MS_AGENT_SECRET_KEY` are mutually exclusive. Explicitly empty, missing, or invalid sources must not fall back to the default. External keys are read without copying them into application data. Both variables are removed from Node SSR, shell, and LSP child environments to reduce inheritance; this does not isolate processes with the same filesystem access.

Managed ciphertext blocks automatic creation of a missing default key. Editing non-sensitive metadata or clearing ciphertext does not require a new default key. Decryption failure must not silently use an environment credential. Explicit reset clears registered fields within its managed scope and never replaces an existing master key. See the [recovery guide](../user-guide/credentials.md) for operations and version compatibility.

## Add a credential field

The registry covers provider keys; generic, vendor-specific, and vision LLM keys; search and summarizer keys; and memory extraction and embedding keys. Arbitrary MCP env/headers, messages, logs, and custom fields do not automatically receive complete protection.

Register extensions **before** migration, configuration reads, or saves, then decrypt at the provider call site:

```python
from omegaconf import OmegaConf
from ms_agent.config.secrets import (
    register_secret_field, resolve_secret, write_managed_config,
)

register_secret_field('tools.my_tool.access_token')
# path is a managed configuration file; home is this instance's application home.
write_managed_config(path, config, home=home)
stored = OmegaConf.load(path)
token = resolve_secret(stored.tools.my_tool.access_token, home=home)
# Pass token to the client; do not write it back into stored.
```

Field registration does not expand file discovery. New persisted files also need a migration entry point; new whole-file writes must use protected storage, not just form-level encryption. Verify legacy plaintext, existing ciphertext, missing keys, and unrelated edits without plaintext write-back.

## Export and distribution boundaries

The SDK ms-agent Agent Hub adapter strips registered credentials on import and upload. External exporters must still clear sensitive fields and exclude the actual master-key source. Encryption adds protection; it does not establish that ModelScope Playground or another exporter has implemented filtering. See the [user guide](../user-guide/credentials.md) for backup versus template-sharing behavior.

Distribution builds discover Python packages only under `ms_agent`, exclude temporary scripts, runtime history, application data, master-key directories, and local `.env` files, and clear the previous library build. `.gitignore` alone does not constrain wheel/sdist contents; inspect actual release artifacts before publishing.

Implementation: `ms_agent/config/secrets.py` for encryption, migration, and reset; `llm/credentials.py` for model credentials; `utils/history_secrets.py` for new history stripping. WebUI `bootstrap.py`, `providers.py`, and `runtime.py` handle startup migration, management status, and runtime caching. See [Storage layout](storage.md) for directory responsibilities.
