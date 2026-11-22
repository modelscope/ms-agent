# Python SDK

Run a minimal task without tools before embedding an agent in your application. Complete the {ref}`terminal installation <terminal>` and set `MODELSCOPE_API_KEY` in the environment running the script.

## Run a task

Save the following as `hello_agent.py` in an empty example directory. Explicit configuration avoids interactive callbacks waiting for input and does not enable file or shell tools for this example.

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
        messages = await agent.run('Explain an agent in two sentences.')
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

A successful run prints a reply and exits. Available model IDs, access, and quotas depend on your provider. Do not put API keys in scripts or commit them to a repository.

## Results and lifecycle

Non-streaming `run()` returns a list of messages, not a string. The list may contain system/user messages, tool calls, and tool results. Select the roles and content your application needs.

Tool connections belong to the execution lifecycle. Release resources you created even when a task fails or is cancelled. A long-running service should not create a new agent for every text fragment.

Streaming mode returns an async generator. Message-history views and interface events are different contracts; see [Messages and events](../core/messages-events.md) before consuming them.

## Grow the example

1. Load YAML with [configuration services](../core/configuration.md) rather than repeating settings across scripts.
2. Add [tools](../core/tools.md) or [skills](../core/skills.md), limited to what the task needs.
3. Use [sessions](../core/sessions.md) and [context management](../core/context.md) for multi-turn work.
4. When stages and dependencies are known, use a [workflow](../core/workflows.md) instead of one long prompt.
