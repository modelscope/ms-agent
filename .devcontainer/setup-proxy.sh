#!/bin/bash

# DevContainer 代理配置脚本
# 自动检测并应用代理配置

echo "🔧 开始配置代理设置..."

# 使用主机网络模式，直接使用主机的代理配置
if [ -n "$HTTP_PROXY" ]; then
    echo "✅ 检测到代理环境变量，使用主机网络模式:"
    echo "   HTTP_PROXY: $HTTP_PROXY"
    echo "   HTTPS_PROXY: $HTTPS_PROXY"

    # 直接使用主机代理地址（不需要转换）
    HOST_PROXY="$HTTP_PROXY"

    # 设置容器内代理变量
    export HTTP_PROXY="$HOST_PROXY"
    export HTTPS_PROXY="$HTTPS_PROXY"
    export http_proxy="$HTTP_PROXY"
    export https_proxy="$HTTPS_PROXY"

    # 创建 pip 配置目录
    mkdir -p ~/.pip

    # 配置 pip 代理
    if [ ! -f ~/.pip/pip.conf ] || ! grep -q "proxy = " ~/.pip/pip.conf; then
        echo "📦 配置 pip 代理..."
        cat > ~/.pip/pip.conf << EOF
[global]
proxy = $HOST_PROXY
trusted-host = pypi.org
               pypi.python.org
               files.pythonhosted.org
EOF
    else
        echo "📦 pip 代理已存在，跳过配置"
    fi

    # 配置 Git 代理
    echo "🔧 配置 Git 代理..."
    git config --global http.proxy "$HOST_PROXY"
    git config --global https.proxy "$HOST_PROXY"

    # 配置 npm 代理（如果存在）
    if command -v npm &> /dev/null; then
        echo "📦 配置 npm 代理..."
        npm config set proxy "$HOST_PROXY"
        npm config set https-proxy "$HOST_PROXY"
        npm config set strict-ssl false
    fi

    # 配置 Docker 代理
    mkdir -p ~/.docker
    cat > ~/.docker/config.json << EOF
{
  "proxies": {
    "default": {
      "httpProxy": "$HOST_PROXY",
      "httpsProxy": "$HOST_PROXY",
      "noProxy": "localhost,127.0.0.1,*.local,*.company.com"
    }
  }
}
EOF

    echo "✅ 代理配置完成"
    echo ""
    echo "📋 当前代理配置:"
    echo "   Git: $(git config --global --get http.proxy || echo '未设置')"
    echo "   pip: $(grep 'proxy = ' ~/.pip/pip.conf 2>/dev/null | cut -d' ' -f3 || echo '未设置')"
    if command -v npm &> /dev/null; then
        echo "   npm: $(npm config get proxy || echo '未设置')"
    fi

else
    echo "ℹ️ 未检测到代理环境变量，跳过代理配置"
    echo ""
    echo "💡 如需使用代理，请在主机设置以下环境变量:"
    echo "   export HTTP_PROXY=http://proxy.company.com:8080"
    echo "   export HTTPS_PROXY=http://proxy.company.com:8080"
    echo "   export NO_PROXY=localhost,127.0.0.1,*.local"
    echo ""
    echo "然后重新构建 DevContainer"
fi

echo "🔧 代理配置脚本执行完成"
