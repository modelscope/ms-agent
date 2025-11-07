# DevContainer 使用指南

## 概述

已为您配置了完整的DevContainer开发环境，基于Ubuntu 22.04，包含所有MS-Agent项目开发所需的工具和配置。

## 快速开始

### 方法一：使用VS Code（推荐）

1. 在VS Code中打开项目文件夹
2. 安装"Dev Containers"扩展
3. 按`Ctrl+Shift+P`，选择"Dev Containers: Reopen in Container"
4. 等待容器构建完成

### 方法二：使用命令行

```bash
# 构建并启动容器
./.devcontainer/devctl.sh build
./.devcontainer/devctl.sh up

# 进入容器
./.devcontainer/devctl.sh shell
```

## 环境特性

### 🐧 Ubuntu系统
- Ubuntu 22.04基础镜像
- 非root用户（vscode）运行
- 完整的sudo权限

### 🐍 Python环境
- Python 3.x 预安装
- pip包管理器
- 自动安装项目依赖

### 🛠️ 开发工具
- **基础工具**: git, curl, wget, vim, nano
- **编译工具**: build-essential, cmake
- **VS Code扩展**: Python, Black, Pylint, Jupyter等

### 🔧 自动化配置
- 代码格式化（Black）
- 导入排序（isort）
- 代码检查（Pylint）
- 保存时自动格式化

## 端口映射

| 端口 | 用途 |
|------|------|
| 8888 | Jupyter Notebook |
| 8080 | Web应用服务 |
| 3000 | 其他开发服务 |

## 管理命令

使用`./.devcontainer/devctl.sh`脚本管理容器：

```bash
# 构建镜像
./.devcontainer/devctl.sh build

# 启动容器
./.devcontainer/devctl.sh up

# 停止容器
./.devcontainer/devctl.sh down

# 进入shell
./.devcontainer/devctl.sh shell

# 查看状态
./.devcontainer/devctl.sh status

# 查看日志
./.devcontainer/devctl.sh logs

# 清理资源
./.devcontainer/devctl.sh clean
```

## 文件结构

```
.devcontainer/
├── devcontainer.json    # VS Code配置
├── Dockerfile          # 容器构建文件
├── docker-compose.yml  # 容器编排配置
├── devctl.sh          # 管理脚本
└── README.md          # 使用指南
```

## 开发工作流

1. **首次使用**: VS Code → "Reopen in Container"
2. **日常开发**: 直接在容器中编码和测试
3. **同步更新**: 容器内运行 `./sync-upstream.sh`
4. **调试代码**: VS Code调试器支持Python调试

## 注意事项

- 所有修改都在容器内进行，不会影响宿主机
- 代码会自动挂载到容器的`/workspace`目录
- 容器停止后数据会保留（卷挂载）
- 建议定期备份重要代码到Git仓库
