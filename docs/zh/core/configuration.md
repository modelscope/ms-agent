# 配置

配置决定模型、工具、工作目录和执行行为。先确定自己使用的入口，再选择配置文件；界面设置、`Config.from_task()` 和分层解析器不是完全相同的加载路径。

## 两条加载路径

| 方式 | 适用场景 | 行为 |
| --- | --- | --- |
| `Config.from_task()` | CLI、独立脚本、项目配置 | 加载本地文件、目录或模型仓库任务，补齐配置并处理环境变量 |
| `ConfigResolver` | WebUI、需要多层设置的服务 | 合并框架、界面默认值、全局设置、Agent、项目和会话覆盖 |

分层解析后者优先；MCP、技能和插件还会按自己的名称与作用域规则合并，不能把所有列表当作简单追加。

```{mermaid}
flowchart TD
  A[框架默认值] --> B[界面默认值 · 可选]
  B --> C[全局用户设置]
  C --> D[Agent 配置]
  D --> E[项目补丁]
  E --> F[会话覆盖]
  F --> G[解析工具、MCP、技能和插件]
```

## 最小配置

保存为 `agent.yaml`，先设置 `MODELSCOPE_API_KEY`，然后运行 `ms-agent run --config agent.yaml --query '你好'`。

```yaml
llm:
  service: modelscope
  model: Qwen/Qwen3-235B-A22B-Instruct-2507
generation_config:
  stream: false
callbacks: []
max_chat_round: 1
```

只给已有配置增加必要字段。`tools.<name>` 未写 `mcp: false` 时可能被当成 MCP 服务；内置工具应明确标记。`trust_remote_code` 是加载外部 Python 代码的信任开关，不是模型生成代码的通用安全沙箱。

## 文件位置与覆盖

- 全局设置在 `$MS_AGENT_HOME/settings.json`，默认根目录为 `~/.ms_agent`。
- 项目配置通常在工作目录的 `.ms_agent/config.yaml`；旧 `.ms-agent` 路径保留读取兼容。
- `ConfigResolver.resolve(session_overrides=...)` 的会话覆盖优先于项目补丁。
- CLI 的参数覆盖和 `.env` 加载由其入口处理；不能假设改变 WebUI 的默认模型会覆盖每一个独立 YAML。

调试时先确认工作目录、`MS_AGENT_HOME`、实际配置文件及入口，再检查最终字段。打印配置前删去密钥和敏感 URL。

## 编程式合并

```python
from omegaconf import OmegaConf
from ms_agent.config.resolver import ConfigResolver

resolver = ConfigResolver(global_dir='./demo-home', project_root='./demo-project')
config = resolver.resolve(
    agent_config=OmegaConf.create({'max_chat_round': 3}),
    session_overrides={'max_chat_round': 1},
)
assert config.max_chat_round == 1
```

示例使用隔离目录，展示覆盖关系，不创建模型会话。字段定义见[配置参考](../development/configuration-reference.md)，模型凭据见[模型](models.md)。

实现：`ms_agent/config/config.py`、`ms_agent/config/resolver.py`、`ms_agent/agent/base.py`。
