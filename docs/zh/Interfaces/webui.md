---
slug: webui
title: WebUI 工作台
description: 在浏览器中围绕项目管理 MS-Agent 会话、文件、模型、技能与 MCP 工具。
---

# WebUI 工作台

MS-Agent WebUI 把智能体对话与项目文件放在同一个浏览器工作台中。你可以让智能体检索资料、编写代码或处理文件，查看执行过程，并在已有会话中继续推进任务。

## 围绕项目开展工作

- **项目与会话**：打开本地工作目录，为同一项目创建多个会话，保留任务记录。
- **执行过程**：流式查看回复、思考内容和工具调用；需要确认的操作通过权限交互处理。
- **文件与产物**：浏览、预览和编辑项目文件，在对话与生成结果之间切换。
- **模型与扩展**：配置模型服务，为项目选择技能、连接 MCP 工具，并管理记忆。

## 开始使用

安装要求、启动命令、源码开发与 Docker 部署统一维护在 [WebUI 使用指南](https://github.com/modelscope/ms-agent/blob/main/webui/README_ZH.md)。WebUI 的环境要求独立于基础 SDK，请按该指南准备环境。

启动后：

1. 在 **设置 → 模型设置** 中添加服务商、API Key 和模型。
2. 新建项目或打开已有文件夹，按任务需要配置技能与 MCP 工具。
3. 创建会话，选择模型并输入任务；需要时附上文件或图片。
4. 查看工具执行与生成结果，继续追问或在工作区编辑文件。

## 与 SDK 和项目工作流的关系

WebUI 复用 SDK 的智能体执行、项目与会话存储、配置、技能和 MCP 管理能力。界面负责交互与展示，运行逻辑由 SDK 提供，因此可以与 CLI、TUI 共用框架能力。

通用项目对话与仓库中的专用工作流有各自入口。DeepResearch、CodeGenesis、FinResearch 和视频生成的配置与运行方式，请以[深度研究](../Projects/deep-research.md)、[CodeGenesis](../Projects/code-genesis.md)、[金融研究](../Projects/fin-research.md)、[视频生成](../Projects/video-generation.md)文档及项目 README 为准。

## 相关阅读

- [快速开始](../GetStarted/quick-start.md)
- [配置参考](../Components/config.md)
- [架构总览](../Architecture/ARCHITECTURE.md)
