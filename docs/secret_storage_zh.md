# 配置中的密钥存储

WebUI 保存的模型和搜索 API Key 使用 Fernet 对称加密。配置文件保留密文，模型、搜索和记忆组件在调用服务前解密；管理页面只返回掩码和状态。空白表单表示保留已有 Key，明确清除才删除，新填写的 Key 替换已有值。

## 主密钥与应用数据

| 内容 | 默认位置 |
| --- | --- |
| 应用数据 | `~/.ms_agent`，或 `MS_AGENT_HOME` |
| 主密钥 | 在规范化后的应用目录名后拼接 `.secrets/master.key`，默认 `~/.ms_agent.secrets/master.key` |
| 配置文件 | 全局 `settings.json`；项目 `.ms_agent/config.yaml`、可选 `settings.local.json`；`.ms_agent/memory/*.yaml` 历史配置 |

系统首次保存非空 Key 时生成主密钥。Linux/macOS 上密钥目录权限为 `0700`，文件为 `0600`。可以通过 `MS_AGENT_SECRET_KEY_FILE` 指定外部密钥文件，或通过 `MS_AGENT_SECRET_KEY` 注入 Fernet 主密钥；两者不能同时设置。明确配置但缺失、为空或格式错误的密钥不会回退到默认路径。

Docker 默认使用 `/data` 和 `/data.secrets/master.key`。应分别持久化两个目录，例如 WebUI README 中的两个卷。仅持久化 `/data` 会在容器重建后丢失主密钥。也可以只读挂载外部文件，并设置 `MS_AGENT_SECRET_KEY_FILE`。

## 升级、迁移与模板复用

WebUI 启动时迁移全局配置及所有已登记项目的上述文件；项目配置加载时再次检查，管理接口读取全局配置时也会检查，以兼容外部导入。旧目录 `.ms-agent`、`.memory` 同样处理。迁移只改已登记的敏感字段，保留其他配置和历史消息，不生成明文备份。已加密的字段保持不变，不会重复加密。若旧文件混有无法解密的字段，迁移报错并保留该文件，须修复后再分享。

旧版本不能直接使用新密文，共享同一数据目录的程序应一起升级。既有备份不在自动迁移范围内，也不能因此认为它们已受保护。

搬迁自己的服务需要同时迁移数据和原主密钥。分享模板应清空敏感字段、排除主密钥：接收方第一次填写自己的 Key 时生成本地主密钥；已有本地主密钥时直接复用。SDK 的 ms-agent agent-hub 上传和导入会清空已登记的敏感字段。实验场导出由外部产品负责，应采用同样约定。

只复制密文而不复制主密钥时，接收方不能使用原 Key。WebUI 显示“密钥不可用”，模型发现和聊天报错，不把密文作为 API Key 发送，也不从旧历史恢复被清除的 Key。密钥丢失时仍可查看历史和修改非敏感元数据，但系统不会自动生成另一把主密钥来掩盖问题。

恢复原主密钥是首选。确定放弃当前实例所有已保存凭据时，可执行：

```bash
python -m ms_agent.config.secrets reset --home ~/.ms_agent --confirm
```

这会清空全局及所有已登记项目的敏感字段，保留供应商、模型、项目定义和消息；不会替换已有主密钥。额外的未登记项目可加 `--project /path/to/project`。原本地密钥已丢失时，清空后首次保存新 Key 才生成新的本地主密钥；外部密钥配置仍需先修复。此命令适用于复制了密文的模板，也意味着其他旧凭据会被放弃。

## 保护范围与扩展

加密覆盖供应商 Key、LLM 通用及服务专用 Key、视觉模型 Key、搜索各引擎和摘要模型 Key，以及记忆的事实抽取、嵌入模型 Key。工具增加敏感字段时，必须同时登记存储路径和接入调用端的解密：

```python
from ms_agent.config.secrets import register_secret_field, resolve_secret

register_secret_field('tools.my_tool.access_token')
# 保存配置统一使用 write_managed_config；调用服务前解密选中的字段。
token = resolve_secret(config.tools.my_tool.access_token, config=config)
```

`${...}` 配置引用保留原有解析方式，不把环境变量引用改成保存的明文 Key。任意源 `agent.yaml`、`.env`、MCP 的任意 `env`/headers、自定义工具、会话消息和日志并不自动获得全量保护，须按实际写入与调用位置接入。登记机制不能自动找出未知凭据。

这层保护有明确价值：单独拿到应用目录或项目文件的人无法读取已加密的 Key。但如果导出包含主密钥、整个用户 home 或容器文件系统，保护就失效；同权限运行的进程也可能读取主密钥或调用时的明文。它保护文件意外泄露，不替代登录鉴权、进程隔离或导出方的敏感字段清理。
