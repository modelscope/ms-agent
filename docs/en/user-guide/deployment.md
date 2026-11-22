# Deployment and data

Use [Quick start](../get-started/quick-start.md) locally. Remote deployment additionally requires access control, filesystem permissions, lifecycle management, and backups.

## Bind locally

```bash
ms-agent ui --host 127.0.0.1 --port 8080 --no-browser
```

The selected port must be free and differ from the internal API port. The launcher supervises both services and stops the counterpart on failure. `--skip-install` does not skip build-validity checks; `--reload` is not the source hot-reload entry point.

## Remote access

The application has no built-in login. Configure reverse-proxy authentication, TLS, and network rules before considering `--host 0.0.0.0`. Agents access server files/tools, not browser-local resources. Expose only necessary workspaces.

`MS_AGENT_FRONTEND_HOSTED_MODE=1` hides local-path controls unsuitable for hosted use; it does not enforce backend access restrictions.

## Docker

Select a published image containing the desired features and replace `TAG`:

```bash
docker run --rm -p 127.0.0.1:9000:8000 \
  -e MS_AGENT_HOME=/data -v ms-agent-data:/data \
  modelscope-registry.us-west-1.cr.aliyuncs.com/modelscope-repo/ms-agent:TAG
```

Open `http://127.0.0.1:9000`. The volume preserves application data; mount project files separately. Packages installed into a running container may disappear on replacement. Declare durable dependencies in a derived image or project environment. Source availability does not establish that a particular image has been published.

## Back up and upgrade

1. Stop relevant tasks/services and wait for writes to finish.
2. Back up `MS_AGENT_HOME` and actual workspaces, protecting sensitive configuration.
3. Record code/package and dependency versions; validate a test project after updating.
4. Check models, history, files, skills, and MCP before resuming scheduled tasks.

Backend environments and frontend dependencies/build output are not conversation backups. Copying `webui/frontend/build` does not preserve business data. New terminals still need Python/Node activation.

See the [WebUI maintenance guide](https://github.com/modelscope/ms-agent/blob/main/webui/README.md) for hot reload, runtime images, and environment details, and [Storage](../development/storage.md) for directory responsibilities.
