#!/usr/bin/env python3
"""Build code_genesis sandbox image via Docker API (Colima / API-compatible daemon).

Avoids requiring the standalone `docker` CLI binary; uses the PyPI `docker` package
(``pip install docker`` / requirements/code.txt) like the rest of ms-agent.
"""
from __future__ import annotations

import sys
from pathlib import Path

IMAGE_NAME = "code-genesis-sandbox"
IMAGE_TAG = "version1"

DOCKERFILE = r"""FROM python:3.12-slim

# Install system dependencies and Node.js
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update -o Acquire::Retries=5 \
    && apt-get install -y --no-install-recommends \
    curl \
    git \
    build-essential \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Configure npm to use a Chinese mirror. Comment out this line if not needed.
RUN npm config set registry https://registry.npmmirror.com/

# Install Jupyter kernel gateway (required by sandbox)
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple --trusted-host mirrors.aliyun.com \
    jupyter_kernel_gateway \
    jupyter_client \
    ipykernel

# Install Python kernel
RUN python -m ipykernel install --sys-prefix --name python3 --display-name "Python 3"

WORKDIR /data

EXPOSE 8888
CMD ["jupyter", "kernelgateway", "--KernelGatewayApp.ip=0.0.0.0", "--KernelGatewayApp.port=8888", "--KernelGatewayApp.allow_origin=*"]
"""


def _repo_root() -> Path:
    # projects/code_genesis/tools/thisfile -> parents[3] == repo root
    return Path(__file__).resolve().parents[3]


def main() -> int:
    try:
        import docker
    except ImportError:
        print(
            "Missing Python package 'docker'. Run: pip install docker\n"
            "or: pip install -r requirements/code.txt",
            file=sys.stderr,
        )
        return 1

    root = _repo_root()
    dockerfile_path = root / "Dockerfile.sandbox"
    dockerfile_path.write_text(DOCKERFILE, encoding="utf-8")
    try:
        client = docker.from_env()
        client.ping()
        print("Pulling python:3.12-slim ...")
        client.images.pull("python:3.12-slim")
        tag = f"{IMAGE_NAME}:{IMAGE_TAG}"
        print(f"Building {tag} (context: {root}) ...")
        stream = client.api.build(
            path=str(root),
            dockerfile="Dockerfile.sandbox",
            tag=tag,
            rm=True,
            forcerm=True,
            decode=True,
        )
        for chunk in stream:
            if not chunk:
                continue
            if "stream" in chunk and chunk["stream"]:
                print(chunk["stream"], end="")
            if "errorDetail" in chunk:
                print(chunk.get("error", chunk["errorDetail"]), file=sys.stderr)
                return 1
        print(f"Done: {tag}")
    finally:
        if dockerfile_path.is_file():
            dockerfile_path.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
