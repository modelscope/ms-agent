# 执行环境

执行环境回答“代码在哪里运行、能看到哪些文件”。[权限](permissions.md)回答“这个调用是否被允许”。二者互补，不能用允许/拒绝规则代替进程、容器或网络隔离。

## 本地执行

```yaml
output_dir: ./workspace
tools:
  code_executor:
    mcp: false
    implementation: python_env
    shell_timeout: 120
    include: [shell_executor]
```

`python_env` 使用本机 shell，不再提供本地 Python / Notebook 执行器。POSIX 使用 `/bin/sh`，Windows 使用 `cmd.exe`；每次调用是独立进程，不能依赖上一次的 `cd`、环境激活或 Python 变量。执行 Python 文件时调用项目解释器路径，或在同一次 shell 调用中激活环境并执行。

本地默认 `shell_timeout` 为 60 秒，示例显式设为 120 秒。`shell_env` 用于传入所需环境变量；工具不会自动继承进程中的所有凭据。Docker 镜像的 `MS_AGENT_SHELL_PATH` 可将 Agent 工具环境与服务自身的环境分开，显式 `shell_env` 优先。

旧本地配置应从过滤列表移除 `python_executor`、`notebook_executor`、`reset_executor`、`get_executor_info`，将 `python_timeout` / `notebook_timeout` 换为 `shell_timeout`、`kernel_env` 换为 `shell_env`。这四个接口仍适用于对应沙箱模式。

## 沙箱与部署

Docker / Docker Notebook 沙箱支持 Python、Notebook、shell 和文件操作，Notebook 内核可保留变量，重置会清空其状态。容器中的 `/data` 用于挂载共享资料。沙箱实现需要对应依赖、镜像和运行服务。仓库的领域项目可能配置特定镜像；不能仅将implementation换名就声称已隔离。按项目指南准备镜像、挂载、网络和资源限制，再用无害任务验证。

WebUI运行所在机器的文件系统才是Agent看到的环境。远程部署时，浏览器中选择的路径属于服务器，不是浏览器电脑。不要向公共网络直接开放无认证的工作台。

## 产物与故障

工作产物放在工作目录；内部索引、锁、临时文件和快照集中到 `.ms_agent`。检查返回的实际产物路径，不把工具的内存文档更新当作磁盘保存。

执行失败时记录解释器/命令、目录和已脱敏错误，检查依赖是否安装在正确环境。取消后确认本任务创建的进程已退出，但不要终止其他用户或服务的进程。

下一步：[部署](../user-guide/deployment.md)、[存储](../development/storage.md)。实现：`tools/code/code_executor.py`、`local_code_executor.py`、`sandbox_manager.py`。
