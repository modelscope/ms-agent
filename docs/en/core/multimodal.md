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

Merge these fields into an already configured vision model. `supports_vision` is tri-state: unset follows model metadata, with unknown models defaulting to disabled; explicit true/false is a user override. Do not mark a text-only model as image-capable.

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
