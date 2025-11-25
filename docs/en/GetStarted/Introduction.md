---
slug: Introduction
title: Introduction
description: Ms-Agent Introduction
---

# Quick Start

MS-Agent is the official Agent framework launched by the ModelScope community. This framework is committed to using a clear and simple universal capability framework to solve proprietary problems in several domains.

Currently, the domains we are exploring include:

- DeepResearch: Generate in-depth research reports in the scientific research field
- CodeScratch: Generate runnable software project code from requirements
- General domain: MS-Agent adapts to general LLM conversation scenarios and is compatible with MCP tool calling

MS-Agent is also the backend agent framework for [mcp-playground](https://modelscope.cn/mcp/playground) on the ModelScope official website. If developers are interested in the above domains, or hope to learn Agent technology principles and conduct secondary development, welcome to use MS-Agent.

## Installation

For MS-Agent installation, please refer to the [installation documentation](Installation.md).

## Usage Examples

The following example can start a general agent conversation:
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

### Using Command Line

```shell
ms-agent run --config ms-agent/simple_agent --modelscope_api_key xxx
```

The above two examples have the same effect and both can conduct multi-turn conversations with the model. Developers can also refer to the following usage methods:

- A [more comprehensive example](https://github.com/modelscope/ms-agent/tree/main/examples)
- DeepResearch [example](https://github.com/modelscope/ms-agent/tree/main/projects/deep_research)
- CodeScratch [example](https://github.com/modelscope/ms-agent/blob/main/projects/code_scratch/README.md)
