#!/bin/bash

# Build Python sandbox Docker image
# This creates a basic Python environment for sandbox execution

set -e

IMAGE_NAME="jupyter-kernel-gateway"
IMAGE_TAG="version1"

echo "Building Jupyter Kernel Gateway Docker image..."

# Create a temporary Dockerfile
cat > Dockerfile.sandbox << 'EOF'
FROM python:3.12-slim

# Install data analysis and scientific computing packages
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple --trusted-host mirrors.aliyun.com \
    jupyter_kernel_gateway \
    jupyter_client \
    ipykernel \
    numpy \
    pandas \
    matplotlib \
    seaborn \
    scikit-learn \
    requests \
    beautifulsoup4 \
    lxml \
    pillow \
    tqdm \
    pyarrow

# Install and register the Python kernel
RUN python -m ipykernel install --sys-prefix --name python3 --display-name "Python 3"

EXPOSE 8888
CMD ["jupyter", "kernelgateway", "--KernelGatewayApp.ip=0.0.0.0", "--KernelGatewayApp.port=8888", "--KernelGatewayApp.allow_origin=*"]
EOF

# Build the image
echo "Building Docker image: ${IMAGE_NAME}:${IMAGE_TAG}"
docker build -f Dockerfile.sandbox -t "${IMAGE_NAME}:${IMAGE_TAG}" .

# Clean up
rm Dockerfile.sandbox

echo "✓ Docker image built successfully: ${IMAGE_NAME}:${IMAGE_TAG}"
echo ""
echo "To test the image, run:"
echo "  docker run -it --rm ${IMAGE_NAME}:${IMAGE_TAG}"
echo ""
echo "To use with the sandbox system, use image: '${IMAGE_NAME}:${IMAGE_TAG}'"
