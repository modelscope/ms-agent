---
slug: supported-models
title: 支持的模型
description: Ms-Agent 支持模型列表： OpenAI、ModelScope、Anthropic 等。
---

# 支持的模型

MS-Agent支持标准OpenAI接口的大模型API。除此之外，为了方便不同模型provider使用，也提供了yaml中不同的配置key。

## OpenAI通用

```yaml
llm:
  service: openai
  # 模型id
  model:
  # 模型api_key
  openai_api_key:
  # 模型base_url
  openai_base_url:
```

## ModelScope

```yaml
llm:
  service: modelscope
  # 模型id
  model:
  # 模型api_key
  modelscope_api_key:
  # 模型base_url
  modelscope_base_url:
```

## Anthropic

```yaml
llm:
  service: anthropic
  # 模型id
  model:
  # 模型api_key
  anthropic_api_key:
  # 模型base_url
  anthropic_base_url:
```

> 如果你有其他模型provider，请协助更新此文档。

## 多模态支持

关于如何使用多模态模型（如图片理解、分析功能），请参考 [多模态支持指南](./multimodal-support.md)。
