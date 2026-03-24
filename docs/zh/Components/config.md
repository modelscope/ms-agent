---
slug: config
title: 配置与参数
description: Ms-Agent 配置与参数：类型配置、自定义代码、LLM 配置、推理配置、system 和 query、callbacks、工具配置、其他、config_handler、命令行配置
---

# 配置与参数

MS-Agent 使用一个 yaml 文件进行配置管理，通常这个文件被命名为 `agent.yaml`，这样的设计使不同场景可以读取不同的配置文件。该文件具体包含的字段有：

## 类型配置

> 可选

```yaml
# type: codeagent
type: llmagent
```

标识本配置对应的 agent 类型，支持 `llmagent` 和 `codeagent` 两类。默认为 `llmagent`。如果 yaml 中包含了 code_file 字段，则 code_file 优先生效。

## 自定义代码

> 可选，在需要自定义 LLMAgent 时使用

```yaml
code_file: custom_agent
```

可以使用一个外部 agent 类，该类需要继承自 `LLMAgent`。可以复写其中的若干方法，如果 code_file 有值，则 `type` 字段不生效。

## LLM 配置

> 必须存在

```yaml
llm:
  # 大模型服务 backend
  service: modelscope
  # 模型 id
  model: Qwen/Qwen3-235B-A22B-Instruct-2507
  # 模型 api_key
  modelscope_api_key:
  # 模型 base_url
  modelscope_base_url: https://api-inference.modelscope.cn/v1
```

## 推理配置

> 必须存在

```yaml
generation_config:
  # 下面的字段均为 OpenAI sdk 的标准参数，你也可以配置 OpenAI 支持的其他参数在这里。
  top_p: 0.6
  temperature: 0.2
  top_k: 20
  stream: true
  extra_body:
    enable_thinking: false
```

## system 和 query

> 可选，但推荐传入 system

```yaml
prompt:
  # LLM system，如果不传递则使用默认的 `you are a helpful assistant.`
  system:
  # LLM 初始 query，通常来说可以不使用
  query:
```

## callbacks

> 可选，推荐自定义 callbacks

```yaml
callbacks:
  # 用户输入 callback，该 callback 在 assistant 回复后自动等待用户输入
  - input_callback
```

## 工具配置

> 可选，推荐使用

```yaml
tools:
  # 工具名称
  file_system:
    # 是否是 mcp
    mcp: false
    # 排除的 function，可以为空
    exclude:
      - create_directory
      - write_file
  amap-maps:
    mcp: true
    type: sse
    url: https://mcp.api-inference.modelscope.net/xxx/sse
    exclude:
      - map_geo
```

支持的完整工具列表，以及自定义工具请参考 [这里](./tools)

## 内存压缩配置

> 可选，用于长对话场景的上下文管理

```yaml
memory:
  # 上下文压缩器：基于token检测 + 工具输出裁剪 + LLM摘要
  context_compressor:
    context_limit: 128000      # 模型上下文窗口大小
    prune_protect: 40000       # 保护最近工具输出的token阈值
    prune_minimum: 20000       # 最小裁剪数量
    reserved_buffer: 20000     # 预留缓冲区
    enable_summary: true       # 是否启用LLM摘要
    summary_prompt: |          # 自定义摘要提示词（可选）
      Summarize this conversation...

  # 精炼压缩器：保留执行轨迹的结构化压缩
  refine_condenser:
    threshold: 60000           # 触发压缩的字符阈值
    system: ...                # 自定义压缩提示词（可选）

  # 代码压缩器：生成代码索引文件
  code_condenser:
    system: ...                # 自定义索引生成提示词（可选）
    code_wrapper: ['```', '```']  # 代码块标记
```

支持的压缩器类型：

| 类型 | 适用场景 | 压缩方式 |
|------|---------|---------|
| `context_compressor` | 通用长对话 | Token检测 + 工具裁剪 + LLM摘要 |
| `refine_condenser` | 需保留执行轨迹 | 结构化消息压缩（1:6压缩比） |
| `code_condenser` | 代码生成任务 | 生成代码索引JSON |

## 其他

> 可选，按需配置

```yaml
# 自动对话轮数，默认为 20 轮
max_chat_round: 9999

# 工具调用超时时间，单位秒
tool_call_timeout: 30000

# 输出 artifact 目录
output_dir: output

# 帮助信息，通常在运行错误后出现
help: |
  A commonly use config, try whatever you want!
```

## config_handler

为了便于在任务开始时对 config 进行定制化，MS-Agent 构建了一个名为 `ConfigLifecycleHandler` 的机制。这是一个 callback 类，开发者可以在 yaml 文件中增加这样一个配置：

```yaml
handler: custom_handler
```

这代表和 yaml 文件同级有一个 custom_handler.py 文件，该文件的类继承自 `ConfigLifecycleHandler`，分别有两个方法：

```python
    def task_begin(self, config: DictConfig, tag: str) -> DictConfig:
        return config

    def task_end(self, config: DictConfig, tag: str) -> DictConfig:
        return config
```

`task_begin` 在 LLMAgent 类构造时生效，在该方法中可以对 config 进行一些修改。如果你的工作流中下游任务会继承上游的 yaml 配置，这个机制会有帮助。值得注意的是 `tag` 参数，该参数会传入当前 LLMAgent 的名字，方便分辨当前工作流的节点。


## 命令行配置

在 yaml 配置之外，MS-Agent 还支持若干额外的命令行参数。

- query: 初始 query，这个 query 的优先级高于 yaml 中的 prompt.query
- config: 配置文件路径，支持 modelscope model-id
- trust_remote_code: 是否信任外部代码。如果某个配置包含了一些外部代码，需要将这个参数置为 true 才会生效
- load_cache: 从历史 messages 继续对话。cache 会被自动存储在 `output` 配置中。默认为 `False`
- mcp_server_file: 可以读取一个外部的 mcp 工具配置，格式为：
    ```json
    {
      "mcpServers": {
        "amap-maps": {
          "type": "sse",
          "url": "https://mcp.api-inference.modelscope.net/..."
        }
      }
    }
    ```
- knowledge_search_paths: 知识搜索路径，逗号分隔的多个路径。传入后会自动启用 SirchmunkSearch 进行知识检索，LLM 配置自动从 `llm` 模块复用

> agent.yaml 中的任意一个配置，都可以使用命令行传入新的值，也支持从同名（大小写不敏感）环境变量中读取，例如 `--llm.modelscope_api_key xxx-xxx`。

### 知识搜索快速使用

通过 `--knowledge_search_paths` 参数，可以快速启用基于本地文档的知识搜索：

```bash
# 使用默认 agent.yaml 配置，自动复用 LLM 设置
ms-agent run --query "如何实现用户认证？" --knowledge_search_paths "./src,./docs"

# 指定配置文件
ms-agent run --config /path/to/agent.yaml --query "你的问题" --knowledge_search_paths "/path/to/docs"
```

LLM 相关参数（api_key, base_url, model）会自动从配置文件的 `llm` 模块继承，无需重复配置。
如果需要在 `knowledge_search` 模块中使用独立的 LLM 配置，可以在 yaml 中显式配置 `knowledge_search.llm_api_key` 等参数。
