# Python SDK

本页运行一个不需要工具的最小任务，适合把智能体嵌入 Python 应用。先完成{ref}`终端安装 <terminal>`，并在运行脚本的环境设置 `MODELSCOPE_API_KEY`。

## 运行一个任务

在空的示例目录保存为 `hello_agent.py`。使用明确配置可以避免默认交互回调等待用户输入，也不会为这个例子启用文件或终端工具。

```python
import asyncio
import os
from omegaconf import OmegaConf
from ms_agent.agent import LLMAgent

async def main():
    config = OmegaConf.create({
        'llm': {
            'service': 'modelscope',
            'model': 'Qwen/Qwen3.8-Flash-Next',
            'modelscope_api_key': os.environ['MODELSCOPE_API_KEY'],
        },
        'generation_config': {'stream': False},
        'tools': {},
        'callbacks': [],
        'personalization': {'enabled': False},
        'max_chat_round': 1,
    })
    agent = LLMAgent(config=config)
    try:
        messages = await agent.run('用两句话解释什么是智能体。')
        for message in messages:
            if message.role == 'assistant' and message.content:
                print(message.content)
    finally:
        await agent.cleanup_tools()

asyncio.run(main())
```

```bash
python hello_agent.py
```

成功时，程序输出模型回复并退出。模型 ID、访问权限和额度以提供方实际服务为准。不要把 API Key 写进脚本或提交到仓库。

## 返回值与生命周期

非流式 `run()` 返回消息列表，而不是字符串。列表可能含系统消息、用户消息、工具调用和工具结果，选择需要的角色与内容后再交给业务层。

工具连接属于运行生命周期的一部分。即使发生异常或取消，也应释放自己创建的智能体资源；长期运行服务不要为每一段文本创建一个新 Agent。

流式模式的返回是异步生成器，历史消息视图和界面事件不是同一种对象。具体消费方式见[消息与事件](../core/messages-events.md)。

## 从示例走向应用

1. 用 [Config 配置](../core/configuration.md)载入 YAML，避免在多个脚本重复参数。
2. 添加[工具](../core/tools.md)或[技能](../core/skills.md)，先限制到任务需要的范围。
3. 用[会话](../core/sessions.md)和[上下文](../core/context.md)管理多轮任务。
4. 如果阶段和依赖已知，使用[工作流](../core/workflows.md)，而不是把所有步骤写成一个长提示。
