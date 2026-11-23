# 存储布局

工作目录保存用户产物，应用home保存全局设置和管理信息；源码构建缓存是第三类数据。备份或排障前先区分它们。

## 目录职责

| 位置 | 内容 |
| --- | --- |
| `$MS_AGENT_HOME`，默认 `~/.ms_agent` | 全局设置、技能/MCP配置、项目管理、日志等 |
| 规范化 home 加 `.secrets/master.key`，默认 `~/.ms_agent.secrets/master.key` | 实例主密钥；与数据分开存放，私有恢复时配对使用 |
| `<work_dir>` / `output_dir` | 用户选择的工作文件和产物 |
| `<work_dir>/.ms_agent` | 记忆、快照、索引、锁和工具产物；MCP 图片位于 `artifacts/images/` |
| `$MS_AGENT_HOME/projects/<key>` | 按工作目录分组的SDK会话；入口可指定更细布局 |
| `webui/backend/.venv` | 源码WebUI后端依赖环境 |
| `webui/frontend/node_modules`、`build` | 前端依赖和生成页面，不是项目备份 |

项目键根据绝对工作路径计算；移动目录可能改变默认会话查找位置。WebUI通过SessionManager管理的记录不应只凭一个目录模式猜测。

## 用代码确认路径

```python
from ms_agent.project.paths import global_home, local_internal_dir, memory_dir

print(global_home())
print(local_internal_dir('./workspace'))
print(memory_dir('./workspace'))
```

这些函数解析路径，不要求启动模型。公开日志前脱敏输出里的个人目录。

## 兼容与迁移

当前写入优先 `.ms_agent`；旧 `.ms-agent`、旧sessions或snapshot位置可能仍有读取兼容。不要因为新目录存在就批量删除旧数据。

迁移前停止相关写入，备份配置、元数据、会话和真实工作文件，记录版本。会话中的 MCP 图片引用依赖工作区文件，备份会话时也应保存对应产物。恢复到新位置后检查模型、技能/MCP、记忆与会话；不要复制运行中的数据库锁作为正常数据。

## 安全

受管 settings 中已登记的凭据字段会加密，新历史快照移除凭据；`.env`、未登记字段、消息和日志仍可能包含敏感内容。限制权限，避免公开上传整个 home 或主密钥。私有备份需保留对应钥匙，分享模板需清除凭据并排除钥匙，见[密钥保存与恢复](../user-guide/credentials.md)。清理构建缓存与删除用户产物应分开确认。

相关：[项目与会话](../user-guide/projects-sessions.md)、[部署](../user-guide/deployment.md)。实现：`project/paths.py`、`session_manager.py`、`config/resolver.py`。
