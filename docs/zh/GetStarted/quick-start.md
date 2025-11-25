---
slug: quick-start
title: 快速开始
description: Ms-Agent 快速开始
---

# 快速开始

MS-Agent是魔搭社区官方推出的Agent智能体框架。本框架致力于使用一个清晰简单的通用能力框架，解决若干领域的专有问题。

目前我们在探索的领域有：

- DeepResearch：生成科研领域的深度调研报告
- CodeScratch： 从需求生成可运行的软件项目代码
- 通用领域：MS-Agent适配于通用LLM对话场景，并兼容MCP工具调用

MS-Agent也是魔搭官网的[mcp-playground](https://modelscope.cn/mcp/playground)的后台agent框架，如果开发者对上述领域感兴趣，或者希望学习Agent技术原理并进行二次开发，欢迎使用MS-Agent。

## 安装

MS-Agent的安装请参考[安装文档](installation)。

## 使用样例


下面的样例可以启动一个通用agent对话
```python
import asyncio
import sys

from ms_agent import LLMAgent
from ms_agent.config import Config

async def run_query(query: str):
    config = Config.from_task('ms-agent/simple_agent')
    # TODO change to your real api key https://modelscope.cn/my/myaccesstoken
    config.llm.modelscope_api_key = 'xxx'
    engine = LLMAgent(config=config)

    _content = ''
    generator = await engine.run(query, stream=True)
    async for _response_message in generator:
        new_content = _response_message[-1].content[len(_content):]
        sys.stdout.write(new_content)
        sys.stdout.flush()
        _content = _response_message[-1].content
    sys.stdout.write('\n')
    return _content


if __name__ == '__main__':
    query = 'Introduce yourself'
    asyncio.run(run_query(query))
```

### 使用命令行

```shell
ms-agent run --config ms-agent/simple_agent --modelscope_api_key xxx
```

上面两个例子的效果是相同的，都可以和模型进行多轮对话。开发者也可以参考下面的使用方式：

- 一个[更全面的例子](https://github.com/modelscope/ms-agent/tree/main/examples)
- DeepResearch的[例子](https://github.com/modelscope/ms-agent/tree/main/projects/deep_research)
- CodeScratch的[例子](https://github.com/modelscope/ms-agent/blob/main/projects/code_scratch/README.md)
