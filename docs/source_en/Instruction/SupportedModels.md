# Supported Models

MS-Agent supports large model APIs with the standard OpenAI interface. In addition, to facilitate usage by different model providers, it also provides distinct configuration keys in YAML.

## OpenAI Generic

```yaml
llm:
  service: openai
  # Model ID
  model:
  # Model API key
  openai_api_key:
  # Model base URL
  openai_base_url:
```

## ModelScope

```yaml
llm:
  service: modelscope
  # Model ID
  model:
  # Model API key
  modelscope_api_key:
  # Model base URL
  modelscope_base_url:
```

## Anthropic

```yaml
llm:
  service: anthropic
  # Model ID
  model:
  # Model API key
  anthropic_api_key:
  # Model base URL
  anthropic_base_url:
```

> If you have other model providers, please assist in updating this documentation.
