# syntax=docker/dockerfile:1
# Context: verified packages, service/shell dependency locks and release.json.
FROM node:22-bookworm-slim AS node

FROM python:3.12-slim-bookworm AS base
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
# Keep bookworm security updates; releases preserve and reuse the built image.
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git libstdc++6 tini \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && npm install --global pnpm@10.17.1 \
    && npm cache clean --force \
    && pip install --no-cache-dir uv==0.12.8

FROM base AS dependencies
WORKDIR /tmp/release
COPY runtime-requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv /opt/venv \
    && uv pip install --python /opt/venv/bin/python --require-hashes --no-deps -r runtime-requirements.txt
COPY *.whl ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --python /opt/venv/bin/python --no-deps ./*.whl \
    && uv pip check --python /opt/venv/bin/python

FROM base AS runtime
ARG SDK_VERSION
ARG SDK_SHA
ARG WHEEL_SHA256
LABEL org.opencontainers.image.title="MS-Agent WebUI" \
      org.opencontainers.image.source="https://github.com/modelscope/ms-agent" \
      org.opencontainers.image.version="${SDK_VERSION}" \
      org.opencontainers.image.revision="${SDK_SHA}" \
      com.modelscope.ms-agent.wheel-sha256="${WHEEL_SHA256}"
ENV MS_AGENT_SHELL_PATH="${PATH}" \
    PATH="/opt/venv/bin:${PATH}" \
    NODE_ENV=production \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUTF8=1 \
    MS_AGENT_HOME=/data \
    MS_AGENT_WEBUI_CACHE=/opt/ms-agent-webui-cache
COPY --from=dependencies /opt/venv /opt/venv
COPY release.json /opt/ms-agent-release/release.json
# Keep task libraries in the system Python; never expose service site-packages
# to the agent's shell. The same immutable inputs also record this lockfile.
COPY shell-requirements.txt /opt/ms-agent-release/shell-requirements.txt
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --python /usr/local/bin/python --require-hashes --no-deps \
        -r /opt/ms-agent-release/shell-requirements.txt
# Create the persistent data directory and the preloaded WebUI dependency cache.
RUN mkdir -p /data /opt/ms-agent-webui-cache
WORKDIR /app
# This uses the installed wheel and the final runtime's Node version. No source
# checkout or frontend compilation is performed inside the image.
#
# MS_AGENT_WEBUI_TRACE_RUNTIME keeps only the dependency closure the SSR entries
# can actually reach: `pnpm install --prod` lands ~430 MB in the cache against a
# real closure of ~51 MB, the waste sitting inside the packages rather than in a
# list of unneeded ones. Tracing imports `tsx` and `@vercel/nft`, both
# devDependencies, so the install it runs on is a full one -- transient, and
# discarded within this single RUN, so no layer retains it. The tracer boots the
# closure and renders a page before the full tree goes away, which is why a
# dependency it could not see fails HERE instead of a request in production.
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    MS_AGENT_WEBUI_TRACE_RUNTIME=1 ms-agent ui --prepare-only --no-browser
# Runtime defaults also apply to agent subprocesses with filtered environments.
# Mount replacement files at these paths to use another package index.
RUN <<'EOF'
mkdir -p /etc/uv
printf '%s\n' '[global]' \
    'index-url = https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple' > /etc/pip.conf
printf '%s\n' '[[index]]' \
    'url = "https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple"' \
    'default = true' > /etc/uv/uv.toml
EOF
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD ["curl", "--noproxy", "*", "--fail", "--silent", "http://127.0.0.1:8000/api/health"]
ENTRYPOINT ["tini", "--", "ms-agent", "ui"]
CMD ["--host", "0.0.0.0", "--port", "8000", "--backend-port", "8001", "--no-browser", "--skip-install"]
