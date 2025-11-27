#!/bin/bash

echo "🔧 开始配置 Git 环境..."

# 确保 pre-commit 可用，避免 Git 钩子报错
if ! python3 -m pre_commit --version >/dev/null 2>&1; then
    echo "📦 检测到缺少 pre-commit，开始安装..."
    python3.10 -m pip install --user --upgrade pre-commit
    if python3 -m pre_commit --version >/dev/null 2>&1; then
        echo "✅ pre-commit 安装成功"
    else
        echo "❌ pre-commit 安装失败，请检查网络或 pip 设置"
    fi
else
    echo "✅ 已检测到 pre-commit"
fi

# 配置 Git 用户信息
if [ -n "$GIT_AUTHOR_NAME" ] && [ -n "$GIT_AUTHOR_EMAIL" ]; then
    echo "✅ 配置 Git 用户信息..."
    git config --global user.name "$GIT_AUTHOR_NAME"
    git config --global user.email "$GIT_AUTHOR_EMAIL"
    echo "   用户名: $GIT_AUTHOR_NAME"
    echo "   邮箱: $GIT_AUTHOR_EMAIL"
else
    echo "⚠️  未检测到 Git 用户信息，使用默认配置..."

    # 检查是否已有配置
    if ! git config --global user.name > /dev/null 2>&1; then
        echo "📝 请配置您的 Git 用户信息："
        read -p "请输入您的姓名: " git_name
        read -p "请输入您的邮箱: " git_email

        if [ -n "$git_name" ] && [ -n "$git_email" ]; then
            git config --global user.name "$git_name"
            git config --global user.email "$git_email"
            echo "✅ Git 用户信息配置完成"
        else
            echo "⚠️  使用默认配置"
            git config --global user.name "Developer"
            git config --global user.email "developer@example.com"
        fi
    fi
fi

# 配置 GitHub Token（如果提供）
if [ -n "$GITHUB_TOKEN" ]; then
    echo "✅ 配置 GitHub 凭据..."

    # 配置 GitHub 凭据 helper
    git config --global credential.helper store

    # 创建 GitHub 凭据文件
    mkdir -p ~/.git-credentials
    echo "https://oauth2:${GITHUB_TOKEN}@github.com" > ~/.git-credentials
    chmod 600 ~/.git-credentials

    echo "   GitHub Token 已配置"
fi

# 配置默认编辑器
git config --global core.editor "code --wait"

# 配置换行符处理（推荐用于跨平台开发）
git config --global core.autocrlf input
git config --global core.safecrlf warn

# 配置默认分支名
git config --global init.defaultBranch main

# 配置推送策略
git config --global push.default simple

# 配置拉取策略
git config --global pull.rebase false

# 配置代理（如果设置了环境变量）
if [ -n "$HTTP_PROXY" ] || [ -n "$HTTPS_PROXY" ]; then
    echo "🔧 配置 Git 代理..."

    # 转换代理地址（移除可能的 http:// 前缀）
    git_http_proxy="$HTTP_PROXY"
    git_https_proxy="$HTTPS_PROXY"

    # 配置 Git 代理
    git config --global http.proxy "$git_http_proxy"
    git config --global https.proxy "$git_https_proxy"

    echo "   HTTP 代理: $git_http_proxy"
    echo "   HTTPS 代理: $git_https_proxy"
fi

# 显示当前 Git 配置
echo ""
echo "📋 当前 Git 配置："
echo "   用户名: $(git config --global user.name)"
echo "   邮箱: $(git config --global user.email)"
echo "   编辑器: $(git config --global core.editor)"
echo "   默认分支: $(git config --global init.defaultBranch)"

if [ -n "$HTTP_PROXY" ] || [ -n "$HTTPS_PROXY" ]; then
    echo "   HTTP 代理: $(git config --global --get http.proxy || echo '未设置')"
    echo "   HTTPS 代理: $(git config --global --get https.proxy || echo '未设置')"
fi

echo ""
echo "💡 Git 使用提示："
echo "   - 使用 'git status' 查看文件状态"
echo "   - 使用 'git add <file>' 暂存文件"
echo "   - 使用 'git commit -m \"message\"' 提交更改"
echo "   - 使用 'git push' 推送到远程仓库"
echo "   - 使用 'git pull' 拉取远程更改"

echo ""
echo "🎉 Git 配置完成！"
