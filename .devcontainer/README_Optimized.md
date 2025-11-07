# Dev Container 优化配置指南

## 概述

本文档描述了 MS-Agent 项目的 Dev Container 优化配置，集成了 Claude Code 和完整的开发环境。

## 🚀 新增功能

### 1. Claude Code 集成
- **自动安装**: Dockerfile 中已集成 Claude Code 的自动安装
- **全局可用**: 通过 npm 全局安装，可在容器内直接使用 `claude` 命令
- **API密钥配置**: 自动从本地环境变量 `ANTHROPIC_API_KEY` 传递到容器

### 2. Node.js 支持
- **LTS版本**: 安装最新的 Node.js LTS 版本
- **npm全局包**: 支持全局安装 npm 包，包括 Claude Code

### 3. 增强的VS Code配置
- **新增长展**:
  - `GitHub.copilot-chat`: GitHub Copilot 聊天功能
  - `ms-vscode.vscode-typescript-next`: TypeScript 最新支持
  - `bradlc.vscode-tailwindcss`: Tailwind CSS 支持
  - `esbenp.prettier-vscode`: Prettier 代码格式化

- **优化设置**:
  - 自动格式化和导入排序
  - TypeScript 相对路径导入
  - Git 智能提交
  - 集成终端默认为 bash

### 4. 端口映射
新增端口转发：
- `7860`: 常用于机器学习Web界面
- `5000`: Flask应用默认端口

### 5. 生命周期优化
- **postStartCommand**: 容器启动时显示版本信息
- **postAttachCommand**: 连接容器时显示 Claude Code 使用提示
- **postCreateCommand**: 项目依赖安装后显示 Claude Code 就绪信息

## 📁 文件结构

```
.devcontainer/
├── Dockerfile              # 容器构建文件
├── devcontainer.json       # VS Code Dev Container 配置
├── docker-compose.yml      # Docker Compose 配置
├── devctl.sh              # 开发控制脚本
└── README.md              # 说明文档
```

## 🛠️ 使用方法

### 1. 重建容器
由于修改了 Dockerfile，需要重建容器：

```bash
# 在 VS Code 中
# 1. 按 Ctrl+Shift+P
# 2. 选择 "Dev Containers: Rebuild Container"
# 3. 等待重建完成

# 或者使用命令行
docker-compose -f .devcontainer/docker-compose.yml down
docker-compose -f .devcontainer/docker-compose.yml up --build
```

### 2. 验证 Claude Code 安装
容器启动后，在终端中验证：

```bash
# 检查 Claude Code 版本
claude --version

# 启动 Claude Code
claude
```

### 3. 环境变量配置
确保在本地主机设置了以下环境变量：

```bash
# 在主机上设置（根据您的shell）
export ANTHROPIC_API_KEY="your-api-key-here"

# 或添加到 ~/.bashrc 或 ~/.zshrc
echo 'export ANTHROPIC_API_KEY="your-api-key-here"' >> ~/.bashrc
```

## 🔧 故障排除

### Claude Code 命令找不到
```bash
# 1. 检查安装
which claude
npm list -g @anthropic-ai/claude-code

# 2. 重新安装
npm install -g @anthropic-ai/claude-code

# 3. 检查 PATH
echo $PATH | grep node
```

### 容器构建失败
```bash
# 清理Docker缓存
docker system prune -a

# 重新构建
docker-compose -f .devcontainer/docker-compose.yml build --no-cache
```

### 端口冲突
如果遇到端口冲突，可以修改 `devcontainer.json` 中的 `forwardPorts` 配置。

## 📝 开发工作流

### 1. 日常开发
- 容器启动后自动安装项目依赖
- Python 3.11 为默认 Python 版本
- Node.js 和 Claude Code 可直接使用

### 2. 代码质量
- 保存时自动格式化（Black + Prettier）
- 自动导入排序
- Git 智能提交

### 3. 调试支持
- Python 调试器已配置
- 支持 Jupyter Notebook
- 端口转发用于Web应用调试

## 🎯 性能优化

1. **卷挂载优化**: 使用 `cached` 策略提高性能
2. **依赖缓存**: Docker 层缓存减少构建时间
3. **轻量级基础镜像**: Ubuntu 22.04 作为基础

## 📚 扩展配置

如需添加其他工具或配置，可修改：
- `Dockerfile`: 添加系统依赖或工具
- `devcontainer.json`: 添加 VS Code 扩展或设置

---

**注意**: 重建容器会清除容器内的所有数据，但挂载的目录（如 `/workspace`）会保留。
