---
slug: MultimodalSupport
title: Multimodal Support
description: Ms-Agent multimodal conversation guide - image understanding and analysis configuration and usage.
---

# Multimodal Support

This document describes how to use ms-agent for multimodal conversations, including image understanding and analysis capabilities.

## Overview

ms-agent supports multimodal models such as Alibaba Cloud's `qwen3.5-plus`. Multimodal models can:
- Analyze image content
- Recognize objects, scenes, and text in images
- Engage in conversations based on image content

## Prerequisites

### 1. Install Dependencies

Ensure the required packages are installed:

```bash
pip install openai
```

### 2. Configure API Key

(Using qwen3.5-plus as an example) Obtain a DashScope API Key and set the environment variable:

```bash
export DASHSCOPE_API_KEY='your-dashscope-api-key'
```

Or set `dashscope_api_key` directly in the configuration file.

## Configure Multimodal Models

Multimodal functionality depends on two factors:
1. **Choose a model that supports multimodal input** (e.g. `qwen3.5-plus`)
2. **Use the correct message format** (containing `image_url` blocks)

You can dynamically modify the model configuration in code on top of an existing config:

```python
from ms_agent.config import Config
from ms_agent import LLMAgent
import os

# Use an existing configuration file (e.g. ms_agent/agent/agent.yaml)
config = Config.from_task('ms_agent/agent/agent.yaml')

# Override configuration for multimodal model
config.llm.model = 'qwen3.5-plus'
config.llm.service = 'dashscope'
config.llm.dashscope_api_key = os.environ.get('DASHSCOPE_API_KEY', '')
config.llm.modelscope_base_url = 'https://dashscope.aliyuncs.com/compatible-mode/v1'

# Create LLMAgent
agent = LLMAgent(config=config)
```

## Using LLMAgent for Multimodal Conversations

Using `LLMAgent` for multimodal conversations is recommended, as it provides more complete features including memory management, tool calling, and callback support.

### Basic Usage

```python
import asyncio
import os
from ms_agent import LLMAgent
from ms_agent.config import Config
from ms_agent.llm.utils import Message

async def multimodal_chat():
    # Create configuration
    config = Config.from_task('ms_agent/agent/agent.yaml')
    config.llm.model = 'qwen3.5-plus'
    config.llm.service = 'dashscope'
    config.llm.dashscope_api_key = os.environ.get('DASHSCOPE_API_KEY', '')
    config.llm.modelscope_base_url = 'https://dashscope.aliyuncs.com/compatible-mode/v1'

    # Create LLMAgent
    agent = LLMAgent(config=config)

    # Build multimodal message
    multimodal_content = [
        {"type": "text", "text": "Please describe this image."},
        {"type": "image_url", "image_url": {"url": "https://example.com/image.jpg"}}
    ]

    # Call the agent
    response = await agent.run(messages=[Message(role="user", content=multimodal_content)])
    print(response[-1].content)

asyncio.run(multimodal_chat())
```

### Non-Stream Mode

```python
# Disable stream in configuration
config.generation_config.stream = False

agent = LLMAgent(config=config)

multimodal_content = [
    {"type": "text", "text": "Please describe this image."},
    {"type": "image_url", "image_url": {"url": "https://example.com/image.jpg"}}
]

# Non-stream mode: returns complete response directly
response = await agent.run(messages=[Message(role="user", content=multimodal_content)])
print(f"[Response] {response[-1].content}")
print(f"[Token Usage] Input: {response[-1].prompt_tokens}, Output: {response[-1].completion_tokens}")
```

### Stream Mode

```python
# Enable stream in configuration
config.generation_config.stream = True

agent = LLMAgent(config=config)

multimodal_content = [
    {"type": "text", "text": "Please describe this image."},
    {"type": "image_url", "image_url": {"url": "https://example.com/image.jpg"}}
]

# Stream mode: returns a generator
generator = await agent.run(
    messages=[Message(role="user", content=multimodal_content)],
    stream=True
)

full_response = ""
async for response_chunk in generator:
    if response_chunk and len(response_chunk) > 0:
        last_msg = response_chunk[-1]
        if last_msg.content:
            # Stream output of new content
            print(last_msg.content[len(full_response):], end='', flush=True)
            full_response = last_msg.content

print(f"\n[Full Response] {full_response}")
```

### Multi-Turn Conversations

LLMAgent supports multi-turn conversations, allowing you to mix images and text:

```python
agent = LLMAgent(config=config, tag="multimodal_conversation")

# Turn 1: Send an image
multimodal_content = [
    {"type": "text", "text": "How many people are in this image?"},
    {"type": "image_url", "image_url": {"url": "https://example.com/image.jpg"}}
]

messages = [Message(role="user", content=multimodal_content)]
response = await agent.run(messages=messages)
print(f"[Turn 1 Response] {response[-1].content}")

# Turn 2: Follow-up question (text only, preserving context)
messages = response  # Use previous response as context
messages.append(Message(role="user", content="What are they doing?"))
response = await agent.run(messages=messages)
print(f"[Turn 2 Response] {response[-1].content}")
```

## Multimodal Message Format

ms-agent uses the OpenAI-compatible multimodal message format. Images can be provided in three ways:

### 1. Image URL

```python
from ms_agent.llm.utils import Message

multimodal_content = [
    {"type": "text", "text": "Please describe this image."},
    {"type": "image_url", "image_url": {"url": "https://example.com/image.jpg"}}
]

messages = [
    Message(role="user", content=multimodal_content)
]

response = llm.generate(messages=messages)
```

### 2. Base64 Encoding

```python
import base64

# Read and encode the image
with open('image.jpg', 'rb') as f:
    image_data = base64.b64encode(f.read()).decode('utf-8')

multimodal_content = [
    {"type": "text", "text": "What is this?"},
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

### 3. Local File Path

```python
import base64
import os

image_path = 'path/to/image.png'

# Get MIME type
ext = os.path.splitext(image_path)[1].lower()
mime_type = {
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif': 'image/gif',
    '.webp': 'image/webp'
}.get(ext, 'image/png')

# Read and encode
with open(image_path, 'rb') as f:
    image_data = base64.b64encode(f.read()).decode('utf-8')

multimodal_content = [
    {"type": "text", "text": "Describe this image."},
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

## Running Examples

### Running the Agent Example

```bash
# Run the complete test suite (including stream and non-stream modes)
python examples/agent/test_llm_agent_multimodal.py
```

## FAQ

### Q: Are there image size limits?

A: Yes, different models have different limits:
- qwen3.5-plus: Recommended image size under 4MB
- Recommended resolution not exceeding 2048x2048

### Q: What image formats are supported?

A: Commonly supported formats:
- JPEG / JPG
- PNG
- GIF
- WebP

### Q: Can I send multiple images at once?

A: Yes, you can add multiple `image_url` blocks in a single message:

```python
multimodal_content = [
    {"type": "text", "text": "Compare these two images."},
    {"type": "image_url", "image_url": {"url": "https://example.com/img1.jpg"}},
    {"type": "image_url", "image_url": {"url": "https://example.com/img2.jpg"}}
]
```

### Q: Is streaming output supported?

A: Yes, multimodal conversations support streaming output. Set `stream: true`:

```python
config.generation_config.stream = True
response = llm.generate(messages=messages, stream=True)
```
