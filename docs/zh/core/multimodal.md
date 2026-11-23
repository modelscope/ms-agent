# 多模态

读图是模型输入能力；生成图像、音频或视频是工具能力。两者需要分别选择模型与依赖，不能因为能上传图片就推断所有模型或项目都支持多模态生成。

## 输入图片的路径

WebUI/TUI 将本地图片附件转换为消息引用。LLM 层在协议边界编码像素：OpenAI 兼容路径使用图片内容块，Anthropic 路径使用图片 source。两者都要求当前模型及端点支持图片输入。

```yaml
llm:
  supports_vision: true
  vision:
    enabled: true
    detail: auto
    transcode: true
    max_images: 0
```

将这些字段合并到已配置的视觉模型中。`supports_vision`是三态：未设置时按模型元数据识别，未知模型默认关闭；显式false/true是用户覆盖。不要给纯文本模型强行标true。

## 本地图片 SDK 示例

先完成[SDK 安装](../get-started/python-sdk.md)，并安装 `pillow`。选择支持图片的模型，为当前进程设置 `OPENAI_API_KEY`、`OPENAI_BASE_URL` 和 `VISION_MODEL`（实际模型 ID）。下面使用 OpenAI 兼容端点；这些凭据只保存在私有环境中。

用自己有权处理的 PNG/JPEG，或在空的测试目录生成不含个人信息的红色方块：

```bash
python -c "from PIL import Image; Image.new('RGB', (160, 160), 'red').save('sample.png')"
```

保存为 `multimodal_demo.py`。默认运行一轮；`--stream` 消费累计流式消息，`--follow-up` 使用返回历史继续追问。示例仅为自身进程重定向 `HOME` / `MS_AGENT_HOME`，将状态与工具产物放在临时目录，不加载日常配置；结束后清理临时状态，不删除输入图片。

```python
import asyncio
import os
from pathlib import Path
import sys
import tempfile

from omegaconf import OmegaConf
from ms_agent import LLMAgent
from ms_agent.llm.utils import Message

async def main():
    image = Path(sys.argv[1]).resolve(strict=True)
    stream = '--stream' in sys.argv
    with tempfile.TemporaryDirectory(prefix='ms-vision-') as work:
        os.environ['MS_AGENT_HOME'] = str(Path(work) / 'home')
        os.environ['HOME'] = str(Path(work) / 'user')
        config = OmegaConf.create({
            'llm': {
                'service': 'openai', 'use_provider_router': True,
                'model': os.environ['VISION_MODEL'],
                'api_key': os.environ['OPENAI_API_KEY'],
                'base_url': os.environ['OPENAI_BASE_URL'],
                'supports_vision': True,
                'vision': {'enabled': True, 'transcode': True},
            },
            'generation_config': {'stream': stream, 'stream_output': False},
            'tools': {}, 'callbacks': [], 'interactive': False,
            'max_chat_round': 1, 'output_dir': work,
        })
        agent = LLMAgent(config=config)
        chunks = None
        try:
            messages = [Message(role='system', content='You are an image assistant.'),
                Message(role='user', content='Describe this image briefly.',
                attachments=[{'type': 'image', 'path': str(image),
                              'media_type': 'image/png'}])]
            if stream:
                chunks = await agent.run(messages=messages, stream=True)
                previous = ''
                history = None
                async for history in chunks:
                    last = history[-1]
                    if last.role == 'assistant' and isinstance(last.content, str):
                        print(last.content[len(previous):], end='', flush=True)
                        previous = last.content
                print()
            else:
                history = await agent.run(messages=messages)
                print(history[-1].content)
            if '--follow-up' in sys.argv and history:
                history.append(Message(role='user', content='What is its main color?'))
                config.generation_config.stream = False
                history = await agent.run(messages=history)
                print(history[-1].content)
        finally:
            if chunks is not None:
                await chunks.aclose()
            await agent.cleanup_tools()

if __name__ == '__main__':
    asyncio.run(main())
```

```bash
python multimodal_demo.py sample.png
python multimodal_demo.py sample.png --stream --follow-up
```

预期输出是图像描述，红色方块应描述为红色；追问仍能使用前一轮图片。流式返回的是累计历史，不是独立 token，不能把每个 chunk 的全文反复拼接。提前停止时关闭生成器并执行 `cleanup_tools()`；示例的 `finally` 同样处理异常和取消。

### URL 与 Base64 输入

`attachments[].path` 只接受本地文件路径，不会自动下载 URL 或解析 Base64。为两种协议使用同一个附件入口时，先由自己的程序取得有权使用的文件，再传本地路径。PNG 示例以外的文件请填写正确的 `media_type`。

OpenAI 兼容端点若支持原生图片内容块，可用以下消息列表替换示例的输入（system 在前，图片消息在后）；远程 URL 必须能被服务端访问：

```python
messages = [Message(role='system', content='You are an image assistant.'),
    Message(role='user', content=[
    {'type': 'text', 'text': 'Describe this image briefly.'},
    {'type': 'image_url', 'image_url': {'url': 'https://example.com/sample.png'}},
])]
```

本地 Base64 的 OpenAI 内容块使用 `data:image/png;base64,...`：

```python
import base64
encoded = base64.b64encode(image.read_bytes()).decode('ascii')
messages = [Message(role='system', content='You are an image assistant.'),
    Message(role='user', content=[
    {'type': 'text', 'text': 'Describe this image briefly.'},
    {'type': 'image_url', 'image_url': {'url': f'data:image/png;base64,{encoded}'}},
])]
```

Anthropic 原生内容块使用 `{'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png', 'data': encoded}}`；同时需将 LLM 配置改为相应 Anthropic 模型、协议及凭据，不能将 OpenAI 的 `image_url` 结构作为所有协议的通用输入。

### 常见失败

- 401/403：检查当前进程的凭据、端点和模型访问权限；不输出完整配置或密钥。
- 400/格式错误：确认模型支持图片、媒体类型正确，并核对服务端尺寸和请求预算。
- 只得到文件路径或“无法读图”：检查文件可读性、`supports_vision` 和 `vision.enabled`；文件缺失或无法编码时会退化为文本提示。
- 超时或取消：保留输入文件，检查网络和服务状态后再运行。模型调用可能计费；离线导入及模拟测试不能替代真实读图验证。

## MCP 返回的图片

MCP 工具返回的图片经过 base64、格式和可读性校验后，按内容哈希保存到工作目录的 `.ms_agent/artifacts/images/`。工具结果携带相对路径和媒体类型，保留多张图片的顺序，不把编码后的图片塞进普通结果文本。

支持图片的主模型可经 OpenAI 兼容或 Anthropic 协议接收这些图片；关闭图片理解时只提供引用路径。WebUI 在工具结果中展示可预览图片，但界面能显示不代表当前模型已收到像素。会话恢复与分支复用已保存引用，备份时也应保留对应产物文件。

当前工具图片上限为解码后 16 MiB、4000 万像素，且声明媒体类型必须与实际文件一致。无效或不支持的图片标记为工具错误，同时保留可读文本；这些本地校验与供应商输入上限分别计算。

## 编码与预算

| 选项 | 含义 |
| --- | --- |
| `enabled` | 是否编码图像输入 |
| `max_edge` | 最长边限制；未显式设置时使用通用默认与Provider能力 |
| `max_bytes` | base64字符串长度预算，不是原始图片文件大小 |
| `transcode` | 对不直接支持的格式转码，动图可能只取首帧 |
| `max_images` | 保留最近图片数量，0不设数量限制 |
| `detail` | 兼容OpenAI的图像细节选项 |

默认长边基准是2048，特定Provider可提升；随包配置保留未设置以便使用对应能力。图片仍受服务商实际尺寸、格式和token限制，不保证所有端点相同。

## 非视觉模型的辅助路径

`llm.vision.auxiliary`可配置另一个视觉模型，将图片描述成文本。还需要启用 `tools.image_reader`；仅设置开关而没有辅助模型不会得到可用的读图工具。这是有损回退，不应替代能直接理解图片的主模型。

图像/视频生成需要对应工具、服务凭据和项目配置，见[工具](tools.md)和[Singularity Cinema](../applications/singularity-cinema.md)。排障时记录模型、协议、图片尺寸与错误，不在报告里附私密图像或Key。

实现：`llm/multimodal.py`、`llm/spec.py`、`tools/mcp_client.py`、`utils/artifact_manager.py`、`tools/image_reader_tool.py`、`agent/agent.yaml`。
