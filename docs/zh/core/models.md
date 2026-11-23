# 模型与供应商

模型ID说明调用哪个模型，提供方说明如何连接，协议说明请求与响应格式。自建端点可以兼容OpenAI协议，但不因此自动支持所有模型能力。

## 注册的提供方

以下来自当前 `ProviderRegistry`；使用服务端实际存在的模型ID。

| service | 主要Key环境变量 | 默认端点 |
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
| alibaba | DASHSCOPE_API_KEY | https://dashscope-intl.aliyuncs.com/compatible-mode/v1 |
| zai | ZHIPU_API_KEY | https://api.z.ai/api/paas/v4 |
| moonshotai | MOONSHOT_API_KEY | https://api.moonshot.ai/v1 |
| longcat | LONGCAT_API_KEY | https://api.longcat.chat/openai |
| xiaomi | XIAOMI_API_KEY | https://api.xiaomimimo.com/v1 |
| stepfun | STEPFUN_API_KEY | https://api.stepfun.com/v1 |
| stepfun-ai | STEPFUN_API_KEY | https://api.stepfun.ai/v1 |
| siliconflow-cn | SILICONFLOW_CN_API_KEY | https://api.siliconflow.cn/v1 |
| siliconflow | SILICONFLOW_API_KEY | https://api.siliconflow.com/v1 |

`glm/bigmodel` 是 zhipu 别名，`moonshot` 是 kimi 别名。Base URL、Key的解析还受显式配置和对应环境变量影响。

## 新旧路由共存

`modelscope/openai/anthropic/dashscope` 默认保留兼容实现，其他已注册提供方自动使用Provider层；`llm.use_provider_router`可显式切换。切换前核对所需的工具调用、流式、多模态、思考内容及错误处理，不把两条路径理解为字节级相同。

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

示例连接你已启动的本地兼容服务；`EMPTY`只适用于不要求鉴权的测试服务，生产环境使用真实凭据配置。

Provider路由中的 `llm.protocol` 可覆盖为 `openai` 或 `anthropic`，请求格式必须与端点匹配。`dashscope_supplier` 是兼容 Anthropic 实现接入 DashScope 桥接时的专用字段，不是通用的服务选择开关。

## 能力差异与选型

- 模型能力在本地按提供方、模型 ID 与端点匹配，覆盖思考档位、图片输入及上下文预算。未知模型仍可手动配置，不因目录缺失而禁止调用；目录存在也不代表账号有访问权限。
- `llm.supports_vision` 可覆盖图片能力；未设置时使用模型元数据，未知模型默认关闭。高级 JSON 中的原生思考参数优先于快捷档位，详见[多模态](multimodal.md)。
- `generation_config`参数取决于协议和服务，未知参数可能被过滤，不能照抄另一家的完整参数表。
- 前缀缓存、思考预算、续写和限流行为因提供方不同；例如Anthropic协议支持不等于当前适配层已实现全部缓存控制。
- 401/403先查Key和权限；404查端点/模型ID；400查参数、工具和输入类型；超时查网络及预算。

## 用量与费用

`SessionLog` 独立将每次响应的用量写入 `.usage.jsonl`，压缩或记忆步骤失败不会丢弃已收到的数据。流式累计用量按记录 ID 取最新值，自动续写的多次响应分别记录，避免重复计费。

费用按请求时固定的模型数据版本估算，单位 USD；缓存读取、缓存写入与普通输入分别计算，思考 token 不重复计入输出。字段齐全标记 `complete`，缺少价格、用量或完整响应则标记 `partial` / `unknown`，不能把缺失值当成零。费用不是供应商账单，WebUI 目前不展示金额。

界面操作见[模型设置](../user-guide/model-settings.md)，能力数据更新见[WebUI 工作台](../user-guide/webui.md)。实现：`llm/spec.py`、`credentials.py`、`llm.py`、`transport/`。
