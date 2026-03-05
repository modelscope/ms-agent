# ms-agent 多模态支持指南

本文档介绍如何使用 ms-agent 进行多模态对话，包括图片理解和分析功能。

## 概述

ms-agent 已经支持多模态模型，如阿里云的 `qwen3.5-plus` 模型。多模态模型能够：
- 分析图片内容
- 识别图片中的对象、场景和文字
- 结合图片内容进行对话

## 前置要求

### 1. 安装依赖

确保已安装必要的依赖包：

```bash
pip install openai
```

### 2. 配置 API Key

（以qwen3.5-plus为例）获取 DashScope API Key 并设置环境变量：

```bash
export DASHSCOPE_API_KEY='your-dashscope-api-key'
```

或者在配置文件中直接设置 `dashscope_api_key`。

## 配置多模态模型

### 使用配置文件

可以使用预定义的多模态配置文件 `config/cfg_model_multimodal.yaml`：

```yaml
llm:
  service: dashscope
  model: qwen3.5-plus
  dashscope_api_key: your-api-key  # 或使用环境变量
  modelscope_base_url: https://dashscope.aliyuncs.com/compatible-mode/v1

generation_config:
  temperature: 0.7
  top_k: 50
  top_p: 0.8
  max_tokens: 2048
  stream: true
  extra_body:
    enable_thinking: false
```

### 在代码中配置

```python
from ms_agent.config import Config
from ms_agent.llm import LLM

config = Config.from_task('path/to/config')
config.llm.model = 'qwen3.5-plus'
config.llm.service = 'dashscope'
config.llm.dashscope_api_key = 'your-api-key'
config.llm.modelscope_base_url = 'https://dashscope.aliyuncs.com/compatible-mode/v1'

llm = LLM.from_config(config)
```

## 使用 LLMAgent 进行多模态对话

推荐使用 `LLMAgent` 来进行多模态对话，它提供了更完整的功能，包括记忆管理、工具调用和回调支持。

### 基本用法

```python
import asyncio
import os
from ms_agent import LLMAgent
from ms_agent.config import Config
from ms_agent.llm.utils import Message

async def multimodal_chat():
    # 创建配置
    config = Config.from_task('ms_agent/agent/agent.yaml')
    config.llm.model = 'qwen3.5-plus'
    config.llm.service = 'dashscope'
    config.llm.dashscope_api_key = os.environ.get('DASHSCOPE_API_KEY', '')
    config.llm.modelscope_base_url = 'https://dashscope.aliyuncs.com/compatible-mode/v1'

    # 创建 LLMAgent
    agent = LLMAgent(config=config)

    # 构建多模态消息
    multimodal_content = [
        {"type": "text", "text": "请描述这张图片。"},
        {"type": "image_url", "image_url": {"url": "https://example.com/image.jpg"}}
    ]

    # 调用 agent
    response = await agent.run(messages=[Message(role="user", content=multimodal_content)])
    print(response[-1].content)

asyncio.run(multimodal_chat())
```

### 非 Stream 模式

```python
# 配置中禁用 stream
config.generation_config.stream = False

agent = LLMAgent(config=config)

multimodal_content = [
    {"type": "text", "text": "请描述这张图片。"},
    {"type": "image_url", "image_url": {"url": "https://example.com/image.jpg"}}
]

# 非 stream 模式：直接返回完整响应
response = await agent.run(messages=[Message(role="user", content=multimodal_content)])
print(f"[回复] {response[-1].content}")
print(f"[Token使用] 输入: {response[-1].prompt_tokens}, 输出: {response[-1].completion_tokens}")
```

### Stream 模式

```python
# 配置中启用 stream
config.generation_config.stream = True

agent = LLMAgent(config=config)

multimodal_content = [
    {"type": "text", "text": "请描述这张图片。"},
    {"type": "image_url", "image_url": {"url": "https://example.com/image.jpg"}}
]

# stream 模式：返回生成器
generator = await agent.run(
    messages=[Message(role="user", content=multimodal_content)],
    stream=True
)

full_response = ""
async for response_chunk in generator:
    if response_chunk and len(response_chunk) > 0:
        last_msg = response_chunk[-1]
        if last_msg.content:
            # 流式输出新增内容
            print(last_msg.content[len(full_response):], end='', flush=True)
            full_response = last_msg.content

print(f"\n[完整回复] {full_response}")
```

### 多轮对话

LLMAgent 支持多轮对话，可以在对话中混合使用图片和文本：

```python
agent = LLMAgent(config=config, tag="multimodal_conversation")

# 第一轮：发送图片
multimodal_content = [
    {"type": "text", "text": "这张图片里有几个人？"},
    {"type": "image_url", "image_url": {"url": "https://example.com/image.jpg"}}
]

messages = [Message(role="user", content=multimodal_content)]
response = await agent.run(messages=messages)
print(f"[第一轮回复] {response[-1].content}")

# 第二轮：继续追问（纯文本，保留上下文）
messages = response  # 使用上一轮的回复作为上下文
messages.append(Message(role="user", content="他们在做什么？"))
response = await agent.run(messages=messages)
print(f"[第二轮回复] {response[-1].content}")
```

## 多模态消息格式

ms-agent 使用 OpenAI 兼容的多模态消息格式。图片可以通过以下三种方式提供：

### 1. 图片 URL

```python
from ms_agent.llm.utils import Message

multimodal_content = [
    {"type": "text", "text": "请描述这张图片。"},
    {"type": "image_url", "image_url": {"url": "https://example.com/image.jpg"}}
]

messages = [
    Message(role="user", content=multimodal_content)
]

response = llm.generate(messages=messages)
```

### 2. Base64 编码

```python
import base64

# 读取并编码图片
with open('image.jpg', 'rb') as f:
    image_data = base64.b64encode(f.read()).decode('utf-8')

multimodal_content = [
    {"type": "text", "text": "这是什么？"},
    {
        "type": "image_url",
        "image_url": {
            "url": f"data:image/jpeg;base64,{image_data}"
        }
    }
]

messages = [Message(role="user", content=multimodal_content)]
response = llm.generate(messages=messages)
```

### 3. 使用本地文件（Base64 编码）

```python
import base64
import os

image_path = 'path/to/image.png'

# 获取 MIME 类型
ext = os.path.splitext(image_path)[1].lower()
mime_type = {
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif': 'image/gif',
    '.webp': 'image/webp'
}.get(ext, 'image/png')

# 读取并编码
with open(image_path, 'rb') as f:
    image_data = base64.b64encode(f.read()).decode('utf-8')

multimodal_content = [
    {"type": "text", "text": "描述这张图片。"},
    {
        "type": "image_url",
        "image_url": {
            "url": f"data:{mime_type};base64,{image_data}"
        }
    }
]

messages = [Message(role="user", content=multimodal_content)]
response = llm.generate(messages=messages)
```

## 运行示例

### 运行 Agent 示例

```bash
# 运行完整测试套件（包括 stream 和非 stream 模式）
python examples/agent/test_llm_agent_multimodal.py
```

## 常见问题

### Q: 图片大小有限制吗？

A: 是的，不同模型有不同的限制：
- qwen3.5-plus: 推荐图片大小不超过 4MB
- 分辨率建议不超过 2048x2048

### Q: 支持哪些图片格式？

A: 通常支持：
- JPEG / JPG
- PNG
- GIF
- WebP

### Q: 可以一次发送多张图片吗？

A: 是的，可以在消息中添加多个 `image_url` 块：

```python
multimodal_content = [
    {"type": "text", "text": "比较这两张图片。"},
    {"type": "image_url", "image_url": {"url": "https://example.com/img1.jpg"}},
    {"type": "image_url", "image_url": {"url": "https://example.com/img2.jpg"}}
]
```

### Q: 流式输出支持吗？

A: 是的，多模态对话支持流式输出。设置 `stream: true` 即可：

```python
config.generation_config.stream = True
response = llm.generate(messages=messages, stream=True)
```

