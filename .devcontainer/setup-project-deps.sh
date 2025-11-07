#!/bin/bash

echo "🚀 开始安装项目依赖..."

# 切换到workspace目录（项目代码在此）
cd /workspace

# 设置代理相关环境变量（如果存在）
if [ -n "$HTTP_PROXY" ] || [ -n "$HTTPS_PROXY" ]; then
    echo "🔧 检测到代理设置，使用主机网络模式..."

    # 使用主机网络时，可以直接使用 127.0.0.1
    CONTAINER_HTTP_PROXY="$HTTP_PROXY"
    CONTAINER_HTTPS_PROXY="$HTTPS_PROXY"

    echo "✅ 使用主机代理配置:"
    echo "   HTTP_PROXY: $CONTAINER_HTTP_PROXY"
    echo "   HTTPS_PROXY: $CONTAINER_HTTPS_PROXY"

    # 测试代理连接
    echo "🔍 测试代理连接..."
    if timeout 5 curl -s --proxy "$CONTAINER_HTTP_PROXY" http://httpbin.org/ip > /dev/null 2>&1; then
        echo "✅ 代理连接正常，配置 pip 代理..."
        pip config set global.proxy "$CONTAINER_HTTP_PROXY"
        pip config set global.trusted-host "pypi.org,pypi.python.org,files.pythonhosted.org"

        # 配置环境变量
        export http_proxy="$CONTAINER_HTTP_PROXY"
        export https_proxy="$CONTAINER_HTTPS_PROXY"
        export HTTP_PROXY="$CONTAINER_HTTP_PROXY"
        export HTTPS_PROXY="$CONTAINER_HTTPS_PROXY"
    else
        echo "⚠️ 代理连接失败，跳过代理配置，使用直连"
        echo "💡 请确保代理服务在主机上正常运行"
    fi
else
    echo "ℹ️ 未检测到代理设置，使用直连模式"
fi

echo "📦 安装 Python 项目依赖..."
# 升级pip
python3.11 -m pip install --upgrade pip

if [ -f "requirements.txt" ]; then
    python3.11 -m pip install -r requirements.txt
    echo "✅ 已安装 requirements.txt 中的依赖"
elif [ -f "requirements/framework.txt" ]; then
    python3.11 -m pip install -r requirements/framework.txt
    echo "✅ 已安装 requirements/framework.txt 中的依赖"
else
    echo "⚠️  未找到requirements文件，跳过Python依赖安装"
fi

echo ""
echo "🎉 项目依赖安装完成！"
