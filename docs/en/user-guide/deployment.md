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

Select a published image containing the desired features and replace `TAG`:

```bash
docker run --rm -p 127.0.0.1:9000:8000 \
  -e MS_AGENT_HOME=/data -v ms-agent-data:/data \
  modelscope-registry.us-west-1.cr.aliyuncs.com/modelscope-repo/ms-agent:TAG
```

Open `http://127.0.0.1:9000`. The volume preserves application data; mount project files separately. Packages installed into a running container may disappear on replacement. Declare durable dependencies in a derived image or project environment. Available features depend on the selected image tag. Check its version and release notes, and choose an image containing the relevant commits for newer features.

## Back up and upgrade

1. Stop relevant tasks/services and wait for writes to finish.
2. Back up `MS_AGENT_HOME` and actual workspaces, protecting sensitive configuration.
3. Record code/package and dependency versions; validate a test project after updating.
4. Check models, history, files, skills, and MCP before resuming scheduled tasks.

Backend environments and frontend dependencies/build output are not conversation backups. Copying `webui/frontend/build` does not preserve business data. New terminals still need Python/Node activation.

See the [WebUI maintenance guide](https://github.com/modelscope/ms-agent/blob/main/webui/README.md) for hot reload, runtime images, and environment details, and [Storage](../development/storage.md) for directory responsibilities.
