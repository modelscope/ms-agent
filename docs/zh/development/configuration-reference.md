# 配置字段参考

先读[配置方式](../core/configuration.md)理解文件位置和覆盖顺序。本页列出当前主要配置面；默认值区分代码缺省与随包YAML，专用项目还可定义自己的字段。

## 运行与生命周期

| 字段 | 类型 | 默认/语义 |
| --- | --- | --- |
| `type` | str | 通用Agent为llmagent；加载器也支持codeagent，工作流使用自己的type |
| `code_file` | str | 自定义Python Agent；显式信任代码后加载，优先于普通类型选择 |
| `output_dir` | str | SDK默认当前工作目录；项目YAML可设为./output等 |
| `max_chat_round` | int | 类默认20；随包通用agent.yaml为9999；TUI还会调整交互预算 |
| `interactive` | bool | 是否交互；未指定时由入口/输入判断 |
| `callbacks` | list[str] | 生命周期回调；通用YAML含input_callback，批处理应显式控制交互 |
| `handler` | str | 处理器的 Python 模块名（不带.py），从配置目录导入 |
| `tool_call_timeout` | number | 默认120秒 |
| `tool_call_timeout_max` | number | 默认600秒，用于限制工具超时 |
| `save_history` | bool | 旧历史缓存保存选项，与SessionLog不是同一层 |
| `enable_snapshots` | bool | 文件快照选项；按工具和入口配置生效 |
| `index_cache_dir` | str | 自定义索引缓存位置；与项目工作文件分开 |

某些组件只有在有效模型、路径或后端配置存在时才装配。

<a id="config_handler"></a>
<a id="config-handler"></a>

### 配置生命周期处理器

在同一目录保存以下两个文件。`Config.from_task()` 会将配置文件所在目录写入 `local_dir`；`handler` 是模块名，不是实例属性 `config_handler`，也不是文件路径。模块中需定义直接继承 `ConfigLifecycleHandler` 的类。

```yaml
# agent.yaml
handler: reviewed_handler
trust_remote_code: true
```

```python
# reviewed_handler.py
from ms_agent.config.config import ConfigLifecycleHandler

class ReviewedHandler(ConfigLifecycleHandler):
    def task_begin(self, config, tag):
        return config
```

把这段 YAML 合入自己的 Agent 配置。加载时会导入模块并实例化处理器；`task_begin` / `task_end` 分别在任务开始和结束时接收并返回配置。启动入口也必须显式授权：SDK 使用 `LLMAgent(config=config, trust_remote_code=True)`，CLI 使用 `--trust_remote_code true`。构造函数会覆盖配置中的信任状态，仅在 YAML 中写 `trust_remote_code: true` 不足以授权。先审查模块及来源；处理器不在工具权限沙箱中运行。缺少信任开关或有效 `local_dir` 时加载会失败。

## 模型与生成参数

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `llm.service` | str | 模型提供方；名称/别名见模型页 |
| `llm.model` | str | 服务实际提供的模型ID |
| `llm.use_provider_router` | bool | 显式切换Provider/legacy路由；省略时按服务默认选择 |
| `llm.protocol` | str | 协议覆盖需符合当前路由支持 |
| `llm.api_key` / `base_url` | str | Provider层通用字段；兼容路径还支持服务特定字段 |
| `llm.openai_api_key` / `openai_base_url` | str | OpenAI兼容路径配置 |
| `llm.modelscope_api_key` / `modelscope_base_url` | str | ModelScope兼容配置 |
| `llm.anthropic_api_key` / `anthropic_base_url` | str | Anthropic兼容配置 |
| `llm.supports_vision` | bool或未设置 | 图片能力覆盖；未设置按模型元数据，未知模型默认关闭 |
| `llm.context_limit` | int或未设置 | 手动窗口上限；只能缩小已知模型窗口 |
| `llm.vision` | mapping | 图像编码、尺寸、转码和辅助读图配置 |
| `generation_config` | mapping | 温度、采样、流式、token及服务扩展参数；支持范围依协议而定 |
| `prompt.system` | str | 替换基础系统提示层；不自动移除其他装配层 |
| `prompt.query` | str | 初始任务输入 |

随包示例含temperature 0.3、top_k 20、stream true；这不是所有模型的有效参数保证。未知键可能被过滤，`extra_body`也需目标服务支持。详见[模型](../core/models.md)、[多模态](../core/multimodal.md)。

## 工具、技能与扩展

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `tools` | mapping | 内置工具或MCP服务配置 |
| `tools.NAME.mcp` | bool | 内置工具必须显式false；缺省可能按MCP处理 |
| `tools.NAME.include` / `exclude` | list[str] | 互斥的工具过滤列表 |
| `tools.NAME.enabled` | bool | 支持此开关的工具/配置层启停；核对实际组件 |
| `tools.plugins` | list[str] | 自定义Python工具文件，相对配置目录；不同于顶层plugins资源系统 |
| `tools.code_executor.implementation` | str | python_env为本地 shell；Python/Notebook接口仅用于沙箱 |
| `tools.code_executor.shell_timeout` / `shell_env` | number / mapping | 本地 shell 默认超时60秒及显式环境变量 |
| `tools.localsearch.paths` | list[str] | 允许本地检索的实际根目录 |
| `knowledge_search_paths` | str | CLI兼容的逗号分隔路径，归入localsearch |
| `skills.sources` | list[mapping] | 显式type/path/repo_id等结构化来源 |
| `skills.auto_discover` | bool | 默认false；不等于关闭所有活动技能树 |
| `skills.disabled` / `whitelist` | list[str] | 按运行时skill_id筛选 |
| `skills.enable_manage` | bool | 是否开放管理工具，和只读技能加载分开 |
| `skills.prompt_injection` | str | all / always_only / none |
| `skills.update_notice` | bool | 默认false；仅稳定技能摘要段 |
| `skills.update_notice_in_sdk` | bool | 默认false；与 `update_notice` 同时启用时由 SDK 发送会话通知。WebUI 默认启用，TUI 保留独立通知。见[设计与实现](skill-management.md) |
| `skills.search` | mapping | BM25/vector/hybrid等选择及依赖 |
| `skills.safety` | mapping | 启用、信任策略和可选LLM检查 |
| `hooks` | mapping | 事件→matcher组→hooks；当前command执行器 |
| `plugins` | mapping或入口解析的配置 | 资源装配与作用域管理，详见插件模块 |
| `acp_agents` / `a2a_agents` | mapping | 各自远端Agent连接；两套schema不同 |

```yaml
tools:
  file_system:
    mcp: false
    include: [read_file, glob, grep]
skills:
  sources:
    - type: local
      path: ./skills
```

## 会话、上下文、记忆

| 配置块 | 主要字段 | 说明 |
| --- | --- | --- |
| `session_log` | `enabled`、`dir`、`context_limit`、`reserved_buffer` | 日志与上下文预算；目录可由入口显式提供 |
| `compaction` | `enabled`、`context_limit`、`compression_ratio`、`reserved_buffer`、`strategies` | 默认摘要，裁剪需显式启用；比例默认0.85，旧reserved_buffer覆盖比例阈值 |
| `unified_memory` 或 `memory.unified_memory` | `enabled`、`storage`、`base_dir`、`ingest_interval`、`recall_top_k` | 通用记忆后端；具体加载路径影响默认目录 |
| `memory` 的旧压缩器 | `context_compressor`、`refine_condenser`、`code_condenser` | 部分领域项目仍使用，不自动删除 |
| `personalization` | `enabled`、`global_instruction`、`project_instruction` | 文件优先和旧字段回退；通用YAML启用，解析缺省false |
| `rag` | `name`、`embedding`、`chunk_size`、`chunk_overlap`、`retrieve_only`、`storage_dir` | 传统RAG，独立于按需localsearch |

上下文窗口优先结合模型能力与手动上限，未知时回退128000；输出预留按实际生成参数计算，自动压缩通常在85%触发。`summary_max_calls`（默认32）和 `summary_reasoning_effort` 可配置摘要预算；不要将旧预留字段当作请求输出上限。记忆的后端字段、生命周期和可插拔例子见[记忆模块](../core/memory.md)。

## 权限

`permission.mode`为 `ask` / `auto` / `full-access`；`restricted` / `interactive`兼容为ask，`delegate`为auto，旧strict为full-access。`decision_provider`选择llm/agent评估，`provider_timeout`默认30秒。`whitelist/blacklist/ask_rules`表达外层规则。`safety_rules`中的patterns、sensitive_paths、sensitive_read_paths、dangerous_removal_paths是**替换默认值的列表**，省略才能保留默认保护。

`allowed_directories/read_only_directories`控制路径；`allow_temp_dir`默认true；`path_validation.read_policy`为loose/strict，`max_command_chars`默认8192。配置是否覆盖所有工具取决于执行路径，见[权限](../core/permissions.md)。

## 环境变量与密钥

用 `.env` 或进程变量提供凭据，环境覆盖不是对任意工具嵌套字段无限新增。WebUI配置加载层和CLI的 `--env` 行为不同；定位问题先确认入口。不要将解析后的完整配置写到公开日志。

WebUI 可选登录使用 `MS_AGENT_WEBUI_AUTH_ENABLED`、`MS_AGENT_WEBUI_USERNAME`、`MS_AGENT_WEBUI_PASSWORD`，详见[部署](../user-guide/deployment.md)。模型能力数据更新策略使用 `MS_AGENT_MODEL_CATALOG=auto|local|bundled`；对话默认排队/插话选择保存在 SDK 设置的 `interaction.follow_up_behavior`，不是 Agent YAML。

源码依据：`config/config.py`、`resolver.py`、`llm/spec.py`、`permission/config.py`、`memory/unified/config.py`与具体模块。
