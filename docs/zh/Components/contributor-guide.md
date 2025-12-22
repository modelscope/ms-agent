---
slug: contributor-guide
title: 贡献者指南
description: Ms-Agent 贡献者指南：如何为 Ms-Agent 贡献工作流和代码。
---

# 贡献者指南

## 工作流贡献

MS-Agent的设计目标是基于单命令或单搜索框模式的端到端工作流Agent框架。并且支持直接加载外部代码和配置：

```shell
ms-agent --config local-dir --trust_remote_code true
# or
ms-agent --config group/model-id --trust_remote_code true
```

上面两种方式可以分别从本地或魔搭模型仓库加载配置和代码并运行。在此基础上，针对MS-Agent的二次开发就不局限于直接对github仓库的PR，开发者可以使用我们的基础能力，把代码托管到魔搭模型仓库中，使用者只需要指定仓库id即可使用你的代码工作流。

这种方式和目前的projects/*下面的项目很相似，区别在于加载本地文件夹或者模型仓库代码。我们在代码仓库中提供了若干脚手架项目，开发者可以基于这些项目的代码继续开发：

- 一个继承LLMAgent实现自定义逻辑的样例：https://www.modelscope.cn/models/ms-agent/simple_agent_code
- 一个自定义外部工作流案例：https://www.modelscope.cn/models/ms-agent/simple_workflow
- 一个自定义外部工具的案例：https://www.modelscope.cn/models/ms-agent/simple_tool_plugin
- 一个定义了配置文件的agent样例：https://www.modelscope.cn/models/ms-agent/simple_agent
- 一个稍微复杂的数据收集案例：https://www.modelscope.cn/models/ms-agent/newspaper

我们后续会提供基于github clone的外部融合方式，因此后续开发者也可以将代码托管在github上。

## 开发者声望

欢迎将自己的工作以PR的方式加入到README的“有趣的工作”一栏中，并给出对自己项目的介绍。同时，你也可以在你配置文件目录同级提供一个author.txt文件，将自己的大名写入其中，开发者在使用你的工作流时会看到这样的打印：

![](../../resources/author.jpg)
