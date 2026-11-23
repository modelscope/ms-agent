# 凭据存储设计

凭据保护由 SDK 负责，WebUI、TUI 和配置管理器共用同一实现。目标是让单独复制配置或项目文件的人无法还原已加密的 API Key，同时保留可读的 JSON/YAML 结构。用户操作和恢复步骤见[密钥保存与恢复](../user-guide/credentials.md)。

## 设计选择

| 选择 | 原因与边界 |
| --- | --- |
| `cryptography` 的 Fernet 字段加密 | 使用现成的对称加密与完整性校验；密文带 `enc:v1:` 前缀 |
| 每个实例一把主密钥 | 降低本地和 Docker 部署成本；首次需要加密非空凭据时创建 |
| 默认钥匙位于规范化 home 的同级 `.secrets` 目录 | 只导出应用目录时不会带走钥匙；导出父目录不具备此边界 |
| 配置对象保留密文，消费端按需解密 | 避免修改无关设置时把明文写回文件 |
| 只加密已登记字段 | 不猜测任意字符串是否为秘密；工具扩展需要同时接入写入与解密 |
| 新历史移除凭据，旧历史迁移加密 | 减少新副本，并保护仍需保留的旧配置快照 |

当前不接系统钥匙串或 KMS，不提供自动主密钥轮换；平台可注入外部钥匙。版本前缀用于识别存储格式，不代表已经实现轮换。运行进程被控制、同权限程序读取钥匙，或钥匙和数据一起外泄时，这层加密不能继续保密。

## 写入与调用

```{mermaid}
flowchart TD
  A[WebUI / TUI 保存] --> B[SDK 加密字段]
  B --> C[配置保留密文]
  C --> D[状态与掩码]
  C --> E[调用前解密]
  E --> F[供应商 API]
  K[独立主密钥] --> B
  K --> E
```

`write_managed_config()` 在文件锁内读取旧配置，保护新配置后原子替换并同步写入；生成主密钥也使用锁和原子替换。空值不触发生成，`${...}` 引用不会被提前解析成磁盘上的明文 Key。

LLM、模型列表探测、搜索与摘要、标题、记忆事实抽取和嵌入组件在调用前解密所选凭据。压缩和文件记忆复用主模型客户端。WebUI 恢复历史使用当前模型、工具和记忆配置；主密钥指纹参与运行时缓存校验，避免继续复用失效的解密状态。管理接口及输入校验错误不回显凭据。

## 迁移文件与触发点

| 文件 | 处理方式 |
| --- | --- |
| `$MS_AGENT_HOME/settings.json` | 迁移已登记字段 |
| `<project>/.ms_agent/config.yaml`、`settings.local.json` | 迁移已登记字段 |
| `<project>/.ms_agent/memory/*.yaml` | 旧快照迁移；新快照在写入前移除凭据 |
| 旧 `.ms-agent/` 对应文件与 `<project>/.memory/*.yaml` | 按相同规则兼容 |

`migrate_home()` 在 WebUI 启动时枚举已登记项目，包括 home 外部和尚未打开的项目。全局配置读取会补迁移，`ConfigResolver` 也检查全局配置和当前项目。没有定时全盘扫描；任意源 `agent.yaml`、备份和未接入字段不因此被改写。

`migrate_file()` 按文件内容判断是否需要迁移，不依赖旧版本号。已有密文不重复加密；明文与密文混合时，先确认旧密文可解密，再写入。迁移不产生额外明文备份，也不是整个实例的事务：启动扫描继续处理其他文件并汇总失败，WebUI 保留管理入口；SDK 解析遇到问题则报错。

## 主密钥与失败处理

默认路径是解析真实 home 后追加 `.secrets/master.key`。Linux/macOS 创建的目录为 `0700`、文件为 `0600`，拒绝默认密钥文件或其父目录的符号链接；home 的路径别名归一到同一把钥匙。Windows ACL 需要另行验证。

`MS_AGENT_SECRET_KEY_FILE` 与 `MS_AGENT_SECRET_KEY` 互斥；显式空值、缺失或非法来源不得回退到默认路径。外部钥匙只读取，不复制到应用目录。这两个变量会从 Node SSR、shell 和 LSP 子进程环境移除，以减少继承；这不隔离同权限进程的文件访问。

已有密文但默认钥匙缺失时，系统拒绝自动新建钥匙。修改非敏感元数据或清除密文无需新建默认钥匙；解密失败不得静默改用环境变量凭据。明确重置会清空管理范围内的登记字段，不替换已有主密钥。操作步骤及跨版本限制见[恢复指南](../user-guide/credentials.md)。

## 接入新字段

登记表覆盖提供方、LLM 通用／供应商专用／视觉 Key，搜索引擎和摘要 Key，以及记忆事实抽取与嵌入 Key。MCP 任意 env/headers、消息、日志和自定义工具字段不自动获得完整保护。

扩展应在迁移、读取或保存配置**之前**登记路径，并在请求供应商的位置解密：

```python
from omegaconf import OmegaConf
from ms_agent.config.secrets import (
    register_secret_field, resolve_secret, write_managed_config,
)

register_secret_field('tools.my_tool.access_token')
# path 为受管配置文件；home 为当前实例的应用目录。
write_managed_config(path, config, home=home)
stored = OmegaConf.load(path)
token = resolve_secret(stored.tools.my_tool.access_token, home=home)
# 仅将 token 交给客户端，不把它写回 stored。
```

登记字段不会扩展文件扫描范围。新增持久化文件还需接入迁移入口；新增整文件写入必须经过保护层，不能只在 WebUI 表单里加密。验证应覆盖旧明文、已有密文、主密钥缺失，以及修改无关字段后不写回明文。

## 导出与发行包边界

SDK 的 ms-agent Agent Hub 适配器在导入和上传时清理登记凭据。外部导出方仍应清空敏感字段、排除实际主密钥来源；加密提供额外保护，不证明实验场等外部流程已经完成清理。备份和模板分享的区别见[用户指南](../user-guide/credentials.md)。

发行包只发现 `ms_agent` 下的 Python 包，排除临时脚本、运行历史、应用数据、主密钥目录和本地 `.env`，并清理旧库构建目录。`.gitignore` 本身不能限制 wheel/sdist；发布前仍需检查实际产物。

实现入口：`ms_agent/config/secrets.py`（加密、迁移与重置）、`llm/credentials.py`（模型凭据）、`utils/history_secrets.py`（新历史清理）；WebUI 的 `bootstrap.py`、`providers.py`、`runtime.py` 分别处理启动迁移、状态展示和会话缓存。目录职责见[存储布局](storage.md)。
