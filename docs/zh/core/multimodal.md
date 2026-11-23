# 多模态

读图是模型输入能力；生成图像、音频或视频是工具能力。两者需要分别选择模型与依赖，不能因为能上传图片就推断所有模型或项目都支持多模态生成。

## 输入图片的路径

WebUI/TUI把支持的附件转换为消息数据，LLM层在协议边界编码图片。当前实现包含OpenAI兼容和Anthropic消息路径，不能沿用旧文档中“Anthropic只支持纯文本”的结论。

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

实现：`llm/multimodal.py`、`llm/spec.py`、`tools/image_reader_tool.py`、`agent/agent.yaml`。
