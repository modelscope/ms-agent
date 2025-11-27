#!/bin/bash

echo "🚀 开始安装 Claude Code 开发环境..."

# 设置代理相关环境变量（如果存在）
if [ -n "$HTTP_PROXY" ] || [ -n "$HTTPS_PROXY" ]; then
    echo "🔧 检测到代理设置，使用主机网络模式..."
    echo "   HTTP_PROXY: $HTTP_PROXY"
    echo "   HTTPS_PROXY: $HTTPS_PROXY"

    # 使用主机网络时，可以直接使用原始代理地址
    export http_proxy="$HTTP_PROXY"
    export https_proxy="$HTTPS_PROXY"
    export HTTP_PROXY="$HTTP_PROXY"
    export HTTPS_PROXY="$HTTPS_PROXY"
fi

# 更新包管理器
echo "📦 更新包管理器..."
sudo apt-get update

# 安装基础工具
echo "📦 安装基础工具..."
sudo apt-get install -y curl wget gnupg ca-certificates

# 检查是否已安装 Node.js
if ! command -v node &> /dev/null; then
    echo "📦 安装 Node.js..."
    # 使用备用方法安装 Node.js
    if [ -n "$HTTP_PROXY" ] || [ -n "$HTTPS_PROXY" ]; then
        echo "🌐 使用代理安装 Node.js..."
        curl -fsSL --proxy "$HTTP_PROXY" https://deb.nodesource.com/setup_lts.x | sudo -E bash -
        sudo apt-get install -y nodejs
    else
        curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
        sudo apt-get install -y nodejs
    fi
else
    echo "✅ Node.js 已安装: $(node --version)"
fi

# 检查 npm 是否可用，如果不可用则安装
if ! command -v npm &> /dev/null; then
    echo "📦 npm 未找到，尝试安装..."
    # 对于 Ubuntu 22.04，npm 可能需要单独安装
    sudo apt-get install -y npm

    # 检查 npm 是否现在可用
    if command -v npm &> /dev/null; then
        echo "✅ npm 已安装: $(npm --version)"
    else
        echo "⚠️ 标准 npm 安装失败，尝试移除旧版本并重新安装..."
        # 移除可能的冲突版本
        sudo apt-get remove -y nodejs npm
        sudo apt-get autoremove -y

        # 清理并重新添加 NodeSource 仓库
        sudo rm -f /etc/apt/sources.list.d/nodesource.list
        sudo rm -f /usr/share/keyrings/nodesource.gpg

        # 重新安装 Node.js 18.x (包含 npm)
        echo "📦 重新安装 Node.js 18.x..."
        if [ -n "$HTTP_PROXY" ] || [ -n "$HTTPS_PROXY" ]; then
            curl -fsSL --proxy "$HTTP_PROXY" https://deb.nodesource.com/setup_18.x | sudo -E bash -
        else
            curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
        fi
        sudo apt-get install -y nodejs

        # 最终检查
        if command -v npm &> /dev/null; then
            echo "✅ npm 重新安装成功: $(npm --version)"
        else
            echo "❌ npm 安装仍然失败，将使用备用方法"
            # 备用方法：直接下载 npm
            cd /tmp
            if [ -n "$HTTP_PROXY" ] || [ -n "$HTTPS_PROXY" ]; then
                curl --proxy "$HTTP_PROXY" -L https://www.npmjs.com/install.sh | sh
            else
                curl -L https://www.npmjs.com/install.sh | sh
            fi
        fi
    fi
else
    echo "✅ npm 已安装: $(npm --version)"
fi

# 检查是否已安装 Claude Code
if ! command -v claude &> /dev/null; then
    echo "📦 安装 Claude Code..."
    # 使用用户安装路径避免权限问题
    NPM_PATH=$(npm config get prefix)
    if [ ! -w "$NPM_PATH" ]; then
        echo "⚠️  检测到权限问题，使用用户级安装..."
        npm config set prefix ~/.local
        export PATH="$HOME/.local/bin:$PATH"
    fi
    npm install -g @anthropic-ai/claude-code
else
    echo "✅ Claude Code 已安装: $(claude --version 2>/dev/null || echo 'version unknown')"
fi

echo ""
echo "🎉 安装完成！"
echo "📋 工具版本信息："
echo "   Node.js: $(node --version)"
echo "   npm: $(npm --version)"
if command -v claude &> /dev/null; then
    echo "   Claude Code: $(claude --version 2>/dev/null || echo 'installed')"
fi
echo "   Python: $(python3.10 --version)"
echo ""
echo "💡 现在您可以使用 'claude' 命令启动 Claude Code！"
