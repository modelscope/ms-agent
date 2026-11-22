# Credential storage in configuration

The WebUI encrypts saved model and search API keys with Fernet. Configuration
retains ciphertext; model, search and memory consumers decrypt selected fields
before calling their services. Management responses contain masks and status
only. A blank form retains the key; explicit clear removes it; a new key replaces it.

## Data and the master key

| Content | Default location |
| --- | --- |
| Application data | `~/.ms_agent`, or `MS_AGENT_HOME` |
| Master key | Append `.secrets/master.key` to the canonical data-directory name; normally `~/.ms_agent.secrets/master.key` |
| Managed configuration | Global `settings.json`; project `.ms_agent/config.yaml`, optional `settings.local.json`, and `.ms_agent/memory/*.yaml` snapshots |

The first nonempty credential write generates a master key. Linux/macOS use
`0700` for its directory and `0600` for the file. Set `MS_AGENT_SECRET_KEY_FILE`
to use an external key file, or `MS_AGENT_SECRET_KEY` to inject a Fernet key.
Set only one. An explicitly configured missing, empty or invalid source never
falls back to the default.

Docker defaults to `/data` and `/data.secrets/master.key`. Persist both
directories separately, as in the WebUI README. Keeping `/data` alone loses
the key when replacing the container. Alternatively mount an external key file
read-only and set `MS_AGENT_SECRET_KEY_FILE`.

## Upgrades, moves and templates

WebUI startup migrates global settings and the listed files in all registered
projects, including unopened projects. Project loading and global management
reads also check for legacy files introduced by external imports. Legacy
`.ms-agent` and `.memory` directories are covered. Migration changes registered
credential fields only, retains metadata and messages, and creates no plaintext
backup. Existing ciphertext is retained. A mixed legacy file containing an
undecryptable credential is left intact with a migration error; repair it before sharing.

Older versions cannot consume the new ciphertext. Upgrade programs sharing
the same home together. Existing backups are outside automatic migration and
must not be assumed protected.

Move your own deployment with its data and original master key. Share templates
with credentials cleared and the master key excluded. The recipient's first
new credential generates a local key, or reuses an existing local key. The
SDK's ms-agent agent-hub upload/import hooks clear registered credential fields.
External playground export should follow the same contract.

Ciphertext copied without its master key cannot authenticate with the old key.
The WebUI displays an unavailable status and discovery/chat report an error.
Ciphertext is never sent as an API key; cleared keys are not restored from
history. Missing keys still allow viewing history and editing non-secret
metadata, but never silently trigger master-key replacement.

Restore the original master key first. To deliberately discard all saved
credentials for this instance, run:

```bash
python -m ms_agent.config.secrets reset --home ~/.ms_agent --confirm
```

This clears credentials in global settings and all registered projects while
retaining provider/model/project definitions and messages. It does not replace
an existing master key. Add `--project /path/to/project` for an unregistered
project. If the local key was lost, the next credential write after clearing
generates a new one. External key configuration still requires repair. The
command also enables reuse of a ciphertext-only template and discards its old credentials.

## Coverage and extensions

Registered fields cover provider keys, generic and service-specific LLM keys,
vision keys, search-engine and summarizer keys, and memory extraction/embedding
keys. Custom tools must register their persistence path and resolve it at use:

```python
from ms_agent.config.secrets import register_secret_field, resolve_secret

register_secret_field('tools.my_tool.access_token')
# Persist through write_managed_config; resolve the selected field at use.
token = resolve_secret(config.tools.my_tool.access_token, config=config)
```

`${...}` references retain their runtime resolution semantics. Arbitrary source
`agent.yaml` files, `.env`, arbitrary MCP environment/header fields, custom
tools, messages and logs are not automatically covered. Register and integrate
their actual persistence and consumer paths; registration cannot discover unknown secrets.

This protects encrypted credentials when application or project files alone
are disclosed. Exporting the master key, the entire user home or the container
filesystem defeats it. A process with the same permissions may read the key or
runtime plaintext. File encryption complements authentication, process isolation
and credential clearing by the export service.
