# 执行环境

执行环境回答“代码在哪里运行、能看到哪些文件”。[权限](permissions.md)回答“这个调用是否被允许”。二者互补，不能用允许/拒绝规则代替进程、容器或网络隔离。

## 本地执行

```yaml
output_dir: ./workspace
tools:
  code_executor:
    mcp: false
    implementation: python_env
    include: [python_executor, shell_executor]
```

`python_env`选择本地实现。shell/Python调用与Notebook不是同一种状态模型：独立调用不能依赖上一次shell的`cd`或环境激活；Notebook可能保留内核状态。需要固定解释器时使用项目环境的绝对路径或在同一次调用中激活并执行。

| 操作 | 注意事项 |
| --- | --- |
| shell_executor | 检查工作目录、PATH、超时和网络授权 |
| python_executor | 使用当前指定解释器；不要假设跨调用保存变量 |
| notebook_executor | 依赖Notebook组件；状态和内核重启需明确 |
| reset_executor | 可能清空执行上下文，不能视为无副作用检查 |
| get_executor_info | 用于确认实际环境而非推测 |

## 沙箱与部署

沙箱实现需要对应依赖、镜像和运行服务。仓库的领域项目可能配置特定镜像；不能仅将implementation换名就声称已隔离。按项目指南准备镜像、挂载、网络和资源限制，再用无害任务验证。

WebUI运行所在机器的文件系统才是Agent看到的环境。远程部署时，浏览器中选择的路径属于服务器，不是浏览器电脑。不要向公共网络直接开放无认证的工作台。

## 产物与故障

工作产物放在工作目录；内部索引、锁、临时文件和快照集中到 `.ms_agent`。检查返回的实际产物路径，不把工具的内存文档更新当作磁盘保存。

执行失败时记录解释器/命令、目录和已脱敏错误，检查依赖是否安装在正确环境。取消后确认本任务创建的进程已退出，但不要终止其他用户或服务的进程。

下一步：[部署](../user-guide/deployment.md)、[存储](../development/storage.md)。实现：`tools/code/code_executor.py`、`local_code_executor.py`、`sandbox_manager.py`。
