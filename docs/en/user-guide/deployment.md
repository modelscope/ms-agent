# Deployment and data

Use [Quick start](../get-started/quick-start.md) locally. Remote deployment additionally requires access control, filesystem permissions, lifecycle management, and backups.

## Bind locally

```bash
ms-agent ui --host 127.0.0.1 --port 8080 --no-browser
```

The selected port must be free and differ from the internal API port. The launcher supervises both services and stops the counterpart on failure. `--skip-install` does not skip build-validity checks; `--reload` is not the source hot-reload entry point.

## Remote access

Authentication is off by default for local use. Before exposing the service, enable built-in login or an authenticated gateway that cannot be bypassed, plus HTTPS and network rules. Agents access server files/tools, not browser-local resources. Expose only necessary workspaces.

### Optional single-user login

Set these before starting, or keep them in a private `webui/backend/.env`:

```ini
MS_AGENT_WEBUI_AUTH_ENABLED=true
MS_AGENT_WEBUI_USERNAME=admin
MS_AGENT_WEBUI_PASSWORD=replace-with-a-long-unique-password
```

Restart and sign in with the configured account. Each instance has one account; the username defaults to `admin`. Enabling authentication without a password prevents startup. Login lasts seven days and survives restarts. Use **Settings → Sign out** to log out; changing the username/password and restarting invalidates old sessions.

Authentication protects pages, files, settings, and streaming APIs. Cookies use HttpOnly and SameSite=Lax, with Secure under HTTPS. Writes accept only same-origin requests or explicit `MS_AGENT_CORS_ORIGINS`, not wildcard origins. This is not multi-user authorization: project resources still belong to one instance.

`MS_AGENT_FRONTEND_HOSTED_MODE=1` hides local-path controls unsuitable for hosted use; it does not enforce backend access restrictions.

## Docker

(credential-volumes)=
### Persist data and the master key

Select a published image containing the desired features and replace `TAG`:

```bash
docker run --rm -p 127.0.0.1:9000:8000 \
  -e MS_AGENT_HOME=/data -v ms-agent-data:/data \
  -v ms-agent-secrets:/data.secrets \
  modelscope-registry.us-west-1.cr.aliyuncs.com/modelscope-repo/ms-agent:TAG
```

Open `http://127.0.0.1:9000`. The two volumes preserve application data and the default master key at `/data.secrets/master.key`; mount project files separately. **With encryption enabled, mounting only `/data` loses the default key on container recreation and makes saved credentials unusable.** Packages installed into a running container may also disappear. Declare durable dependencies in a derived image or project environment. Check the selected image's version and release notes for available features.

For non-root deployments, make the runtime user the owner of the mounted `/data` and `/data.secrets` directories and ensure both are writable. The image build does not set the key directory to mode `700`. When the application first creates the default master key, it still sets that directory to `700` and creates the key file with mode `600`, so relaxing directory permissions alone does not replace correct ownership.

### Use a platform-provided master key

If the platform provides a persistent Fernet key file, mount it read-only instead of the default key volume:

```bash
docker run --rm -p 127.0.0.1:9000:8000 \
  -e MS_AGENT_HOME=/data -v ms-agent-data:/data \
  -e MS_AGENT_SECRET_KEY_FILE=/run/secrets/ms-agent-master \
  --mount type=bind,src=/secure/ms-agent-master,dst=/run/secrets/ms-agent-master,readonly \
  modelscope-registry.us-west-1.cr.aliyuncs.com/modelscope-repo/ms-agent:TAG
```

Replace the host path with the actual file and make it readable by the runtime user. It must already contain a valid Fernet master key; use the original matching key for existing encrypted data. Do not also set `MS_AGENT_SECRET_KEY`. For either option, recreate the container and verify that saved credentials still work. Local binding above does not replace authentication and HTTPS for remote deployment.

## Back up and upgrade

1. Stop relevant tasks/services and wait for writes to finish.
2. Back up `MS_AGENT_HOME`, actual workspaces, and the matching master key with separate access controls. Shared templates must clear credentials and exclude the key; do not publish a private backup.
3. Record code/package and dependency versions. Upgrade WebUI, TUI, CLI, and SDK installations sharing a home or project together; older versions cannot read ciphertext.
4. Provide writable configuration and a readable or creatable master key, then start the new version to migrate legacy settings. Verify continued chat, compaction, and memory reads/writes in an existing conversation, followed by files, skills, and MCP, before resuming scheduled tasks.

Backend environments and frontend dependencies/build output are not conversation backups. Copying `webui/frontend/build` does not preserve business data. New terminals still need Python/Node activation.

Management staying available after migration failure does not prove all configuration is encrypted. Repair and complete migration before exporting or sharing. See [Saving and recovering credentials](credentials.md) for key recovery, credential reset, and rollback boundaries.

See the [WebUI maintenance guide](https://github.com/modelscope/ms-agent/blob/main/webui/README.md) for hot reload, runtime images, and environment details, and [Storage](../development/storage.md) for directory responsibilities.
