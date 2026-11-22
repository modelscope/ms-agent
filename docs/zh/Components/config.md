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
  # 示例面向支持这些参数的 OpenAI 兼容服务；top_k、extra_body 等取决于供应商。
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
  # 基础系统提示；未配置时使用内置 BASE_AGENT_PROMPT
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
      - write_file
  amap-maps:
    mcp: true
    type: sse
    url: https://mcp.api-inference.modelscope.net/xxx/sse
    exclude:
      - map_geo
  # 本地代码库/文档搜索（sirchmunk），对应模型可调用的 `localsearch` 工具
  localsearch:
    mcp: false
    paths:
      - ./src
      - ./docs
    work_path: ./.sirchmunk
    mode: FAST
    # 可选：llm_api_key、llm_base_url、llm_model_name（不填则从 `llm` 继承）
```

支持的完整工具列表，以及自定义工具请参考 [这里](./tools.md)

## 技能配置

> 可选，启用 Agent Skills 时使用

```yaml
skills:
  # 技能来源（本地目录 / ModelScope 或 GitHub 仓库 ID），可多源
  sources:
    - type: local
      path: /path/to/skills
  # 是否自动发现 CWD/skills 下的技能目录（默认 False）
  auto_discover: false
  # 禁用的技能 id 列表
  disabled: []
  # 系统提示注入策略：all | always_only | none
  prompt_injection: all
  # 固定系统提示中的技能清单，技能变化通过后续消息通知（默认 false）
  update_notice: false
```

完整的技能模块说明（包括架构、目录结构、API 参考和安全机制等），请参考 [智能体技能](./agent-skills.md)。

此选项只固定技能清单；个性化文件等其他系统提示层仍可更新。

## 上下文压缩配置（compaction）

> 可选，用于长对话场景的非破坏式上下文管理

历史以 append-only 的 `session_log` 为唯一真相源；每轮由 `ContextAssembler` 非破坏式地重建上下文视图，可按策略压缩，原始日志始终完整。

```yaml
# append-only 消息日志（历史真相源）
session_log:
  enabled: true            # 默认 true
  context_limit: 128000    # 活动窗口保留的最大 token
  reserved_buffer: 20000   # 为下一次回复预留的余量
  prune_protect: 40000     # 最近这些 token 不会被工具输出裁剪

# 非破坏式上下文压缩（每轮重建）
compaction:
  enabled: true            # 默认 true；false 则不压缩（仍记录日志）
  context_limit: 128000    # 覆盖 session_log.context_limit
  reserved_buffer: 20000
  strategies:              # 默认两者，按此顺序
    - name: tool_output_pruner
      enabled: true
      prune_protect: 40000 # 最近 token 免于裁剪
    - name: summary_compactor
      enabled: true        # 需要 LLM；对较早轮次做摘要
```

未指定 `session_log.dir` 时，会话按工作目录保存在 `$MS_AGENT_HOME/projects/` 下（默认 `~/.ms_agent/projects/`）。WebUI 为项目会话设置独立的日志目录。

新建通用智能体建议使用 `compaction` 与 `session_log`。旧的 `memory.context_compressor`、`refine_condenser` 和 `code_condenser` 仍受支持，CodeGenesis 等项目也仍在使用；迁移已有工作流时，应先检查其自定义压缩和恢复逻辑。

## 其他

> 可选，按需配置

```yaml
# 自动对话轮数：框架常量默认 20，随包 agent.yaml 设为 9999
max_chat_round: 9999

# 工具调用超时（秒），默认 120；上限由 tool_call_timeout_max 控制（默认 600）
tool_call_timeout: 120

# 输出 artifact 目录
output_dir: output

# 每次任务开始前保存工作区快照，默认关闭
enable_snapshots: false

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
- load_cache: 从历史 messages 继续对话。缓存路径由 `output_dir` 等运行配置决定。默认为 `False`
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
- knowledge_search_paths: 知识搜索路径，逗号分隔。会合并到 `tools.localsearch.paths` 并注册 **`localsearch`** 工具（sirchmunk），由模型按需调用，不再在每轮自动注入上下文；除非配置 `tools.localsearch.llm_*`，否则 LLM 从 `llm` 模块复用

> agent.yaml 中的任意一个配置，都可以使用命令行传入新的值，也支持从同名（大小写不敏感）环境变量中读取，例如 `--llm.modelscope_api_key xxx-xxx`。

### 知识搜索快速使用

通过 `--knowledge_search_paths` 或在 yaml 中配置 `tools.localsearch`，启用本地知识搜索（模型按需调用 `localsearch`）：

```bash
# 使用默认 agent.yaml 配置，自动复用 LLM 设置
ms-agent run --query "如何实现用户认证？" --knowledge_search_paths "./src,./docs"

# 指定配置文件
ms-agent run --config /path/to/agent.yaml --query "你的问题" --knowledge_search_paths "/path/to/docs"
```

LLM 相关参数（api_key, base_url, model）会自动从配置文件的 `llm` 模块继承，无需重复配置。
若 sirchmunk 需独立 LLM，可在 yaml 的 `tools.localsearch` 下设置 `llm_api_key`、`llm_base_url`、`llm_model_name`。仍支持旧版顶层 `knowledge_search` 相同字段，以便迁移。
