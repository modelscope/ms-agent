#!/bin/bash

# Build Docker sandbox image for code_genesis
# Includes Python + Node.js for full-stack project support

set -e

IMAGE_NAME="code-genesis-sandbox"
IMAGE_TAG="version1"

echo "Building code-genesis sandbox Docker image..."

docker pull python:3.12-slim

cat > Dockerfile.sandbox << 'EOF'
FROM python:3.12-slim

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
EOF

echo "Building Docker image: ${IMAGE_NAME}:${IMAGE_TAG}"
docker build -f Dockerfile.sandbox -t "${IMAGE_NAME}:${IMAGE_TAG}" .

rm Dockerfile.sandbox

echo "Done: ${IMAGE_NAME}:${IMAGE_TAG}"
echo "Contains: Python 3.12, Node.js 20, npm, git, curl"
