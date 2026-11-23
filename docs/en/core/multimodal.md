# Multimodal input

Image understanding is a model-input capability. Image, audio, and video generation are tool capabilities. Configure models and dependencies separately; uploading an image does not imply that every model or application supports multimodal generation.

## Image input path

WebUI/TUI local images become message references. The LLM layer encodes pixels at the protocol boundary: image content blocks for OpenAI-compatible endpoints, image sources for Anthropic. Both require an image-capable model and endpoint.

```yaml
llm:
  supports_vision: true
  vision:
    enabled: true
    detail: auto
    transcode: true
    max_images: 0
```

Merge these fields into an already configured vision model. `supports_vision` is tri-state: unset follows model metadata, with unknown models defaulting to disabled; explicit true/false is a user override. Do not mark a text-only model as image-capable.

## Local-image SDK example

Complete [SDK installation](../get-started/python-sdk.md) and install `pillow`. Set `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and `VISION_MODEL` (a served image-capable model ID) in the current process's private environment. This example uses an OpenAI-compatible endpoint.

Use a PNG/JPEG you are allowed to process, or generate a synthetic red square in an empty test directory:

```bash
python -c "from PIL import Image; Image.new('RGB', (160, 160), 'red').save('sample.png')"
```

Save as `multimodal_demo.py`. It runs one turn by default; `--stream` consumes accumulated messages, and `--follow-up` continues from returned history. Only the example process redirects `HOME` / `MS_AGENT_HOME` to temporary state, avoiding everyday configuration. The state is cleaned on exit; the input image is not deleted.

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

Expected: a description of the image, identifying the synthetic square as red; follow-up can still use the first image. Stream chunks contain accumulated history, not independent tokens. Do not concatenate each full chunk. Close the generator on early exit and call `cleanup_tools()`; the example's `finally` also handles errors and cancellation.

### URL and Base64 input

`attachments[].path` accepts local paths only: it does not download URLs or decode Base64. For a shared attachment entry point across protocols, acquire an authorized local file first. Use the actual `media_type` for images other than the PNG example.

For OpenAI-compatible endpoints supporting native image blocks, replace the example's image message with the following, retaining the system message. Remote URLs must be accessible to the model service:

```python
messages = [Message(role='system', content='You are an image assistant.'),
    Message(role='user', content=[
    {'type': 'text', 'text': 'Describe this image briefly.'},
    {'type': 'image_url', 'image_url': {'url': 'https://example.com/sample.png'}},
])]
```

OpenAI Base64 input uses a `data:image/png;base64,...` URL:

```python
import base64
encoded = base64.b64encode(image.read_bytes()).decode('ascii')
messages = [Message(role='system', content='You are an image assistant.'),
    Message(role='user', content=[
    {'type': 'text', 'text': 'Describe this image briefly.'},
    {'type': 'image_url', 'image_url': {'url': f'data:image/png;base64,{encoded}'}},
])]
```

Anthropic native blocks use `{'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png', 'data': encoded}}`. Configure the corresponding Anthropic model, protocol, and credentials as well; OpenAI `image_url` is not a universal message shape.

### Troubleshooting

- 401/403: verify process credentials, endpoint, and model access. Do not print keys or resolved configurations.
- 400/format errors: confirm image support, actual media type, service size limits, and request budget.
- Only paths or an unreadable-image notice: check file access, `supports_vision`, and `vision.enabled`. Missing/unencodable files fall back to text notices.
- Timeout/cancellation: keep the input, inspect network/service status, then rerun. Calls may incur charges; offline imports and mock tests do not verify real image understanding.

## Images returned by MCP tools

MCP images are validated for base64 encoding, format, and readability, then stored by content hash under `.ms_agent/artifacts/images/` in the workspace. Tool results carry relative paths and media types in image order, not encoded pixels embedded in ordinary result text.

A vision-capable main model can receive these images through OpenAI-compatible or Anthropic transports. With image understanding disabled, only references are provided. The WebUI can preview images in tool results, but display alone does not prove the current model received pixels. Session recovery and forks reuse stored references; backups must include the artifact files.

Tool images are currently limited to 16 MiB decoded and 40 megapixels, with declared media types matching the actual bytes. Invalid or unsupported images mark the result as an error while retaining readable text. These local checks are separate from provider input limits.

## Encoding and budgets

| Option | Meaning |
| --- | --- |
| `enabled` | Enable image encoding |
| `max_edge` | Long-edge cap; otherwise use shared defaults and provider capability |
| `max_bytes` | Base64 string-length budget, not the original image file size |
| `transcode` | Convert unsupported formats; animated input may use only its first frame |
| `max_images` | Keep the most recent images; 0 means no count limit |
| `detail` | OpenAI-compatible image detail selection |

The shared long-edge baseline is 2048, with provider-specific overrides. The bundled YAML leaves it unset to preserve provider selection. Actual service size, format, and token limits still apply.

## Auxiliary vision for text models

`llm.vision.auxiliary` can configure a separate vision model that describes images as text. Enable `tools.image_reader` as well; a flag without an auxiliary model does not create a usable reader. This is a lossy fallback, not a preferred substitute for a vision-capable main model.

Generation uses dedicated tools, credentials, and application configuration. See [Tools](tools.md) and [Singularity Cinema](../applications/singularity-cinema.md). Record model, protocol, image dimensions, and errors when diagnosing failures, without exposing private images or keys.

Implementation: `llm/multimodal.py`, `llm/spec.py`, `tools/mcp_client.py`, `utils/artifact_manager.py`, `tools/image_reader_tool.py`, `agent/agent.yaml`.
