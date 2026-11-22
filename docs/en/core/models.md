# Models and providers

A model ID selects the model, a provider defines the connection, and a protocol defines request/response formats. An OpenAI-compatible endpoint does not automatically support every model capability.

## Registered providers

These entries come from the current `ProviderRegistry`. Use model IDs actually served by your endpoint.

| service | Key environment variables | Default endpoint |
| --- | --- | --- |
| modelscope | MODELSCOPE_API_KEY | https://api-inference.modelscope.cn/v1 |
| openai | OPENAI_API_KEY | https://api.openai.com/v1 |
| anthropic | ANTHROPIC_API_KEY | https://api.anthropic.com |
| google | GOOGLE_API_KEY / GEMINI_API_KEY | https://generativelanguage.googleapis.com/v1beta/openai/ |
| zhipu | GLM_API_KEY / ZHIPU_API_KEY / ZHIPUAI_API_KEY | https://open.bigmodel.cn/api/paas/v4 |
| kimi | KIMI_API_KEY / MOONSHOT_API_KEY | https://api.moonshot.cn/v1 |
| deepseek | DEEPSEEK_API_KEY | https://api.deepseek.com/v1 |
| dashscope | DASHSCOPE_API_KEY | https://dashscope.aliyuncs.com/compatible-mode/v1 |
| minimax | MINIMAX_API_KEY | https://api.minimaxi.com/v1 |
| openrouter | OPENROUTER_API_KEY | https://openrouter.ai/api/v1 |

`glm/bigmodel` alias zhipu; `moonshot` aliases kimi. Explicit configuration and corresponding environment variables also affect URL/key resolution.

## Provider and legacy routes

`modelscope/openai/anthropic/dashscope` retain legacy implementations by default. Other registered providers use the provider layer automatically; `llm.use_provider_router` overrides the selection. Check tool calling, streaming, images, reasoning, and error handling before switching. The paths are not byte-for-byte equivalents.

```yaml
llm:
  service: openai
  model: your-served-model
  openai_base_url: http://127.0.0.1:8000/v1
  openai_api_key: EMPTY
  use_provider_router: true
generation_config:
  stream: false
```

This connects to a local service you have already started. `EMPTY` is only appropriate for test endpoints that do not require authentication; configure actual credentials for production.

In the Provider router, `llm.protocol` can select `openai` or `anthropic`; the wire format must match the endpoint. `dashscope_supplier` is specific to the legacy Anthropic implementation's DashScope bridge, not a universal provider selector.

## Match capabilities, not just names

- Provider declarations are defaults, not proof that every model supports images. Set model-level `supports_vision` deliberately; see [Multimodal](multimodal.md).
- Generation parameters depend on the protocol/service. Unknown parameters may be filtered; do not copy another provider's entire parameter set.
- Caching, reasoning budgets, continuation, and rate limiting differ. Anthropic protocol support does not imply that every caching control is implemented.
- For 401/403, check keys/access; for 404, URL/model ID; for 400, parameters, tools, and content types; for timeouts, connectivity and budgets.

See [Model settings](../user-guide/model-settings.md). Implementation: `llm/spec.py`, `credentials.py`, `llm.py`, `transport/`.
