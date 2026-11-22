# Multimodal input

Image understanding is a model-input capability. Image, audio, and video generation are tool capabilities. Configure models and dependencies separately; uploading an image does not imply that every model or application supports multimodal generation.

## Image input path

WebUI/TUI attachments become message data, and the LLM layer encodes images at the protocol boundary. Current code includes OpenAI-compatible and Anthropic message paths. The old claim that Anthropic always receives plain text is no longer accurate.

```yaml
llm:
  supports_vision: true
  vision:
    enabled: true
    detail: auto
    transcode: true
    max_images: 0
```

Merge these fields into an already configured vision model. `supports_vision` is tri-state: unset can fall back to provider declarations and runtime learning; explicit true/false is a user choice. Do not mark a text-only model as image-capable.

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

Implementation: `llm/multimodal.py`, `llm/spec.py`, `tools/image_reader_tool.py`, `agent/agent.yaml`.
