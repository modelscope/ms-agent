# CLI 任务与脚本

CLI适合从终端运行任务或接入脚本。持续交互优先考虑[TUI](tui.md)，精确参数见[CLI参考](../development/cli-reference.md)。

## 一次只运行一个明确任务

```bash
ms-agent run --config ./agent.yaml --query '总结这份资料' --output_dir ./results
```

`agent.yaml`必须已配置可访问的模型。`--output_dir`是工作目录，不只是导出目录；工具会在这个范围工作。使用空测试目录验证后再指向真实项目。

脚本调用应显式关闭交互并设置预算：

```yaml
interactive: false
callbacks: []
max_chat_round: 3
```

模型凭据用环境变量或本地 `.env`，不要在共享脚本里硬编码。`--env /path/to/.env`可指定文件；进程已有变量和配置覆盖需要按入口解析规则确认。

## 输入与输出

传 `--query` 时任务明确；不传时可进入交互或读取配置/管道输入。自动化任务不要依赖“恰好没有TTY”的隐式分支，明确提供查询、配置和输出目录。

终端输出包含过程信息，不应把stdout整体当成稳定JSON API。业务需要结构化结果时使用[Python SDK](../get-started/python-sdk.md)并选择消息/产物。脚本检查退出状态、日志和预期文件，不能只搜索“完成”字样。

## 外部工具与代码

```bash
ms-agent run --config ./agent.yaml --mcp_server_file ./mcp.json --query '检查可用工具'
```

使用 `--mcp_server_file`接入服务。`--mcp_config`虽然仍在参数定义中，不应在没有验证其实际接入的情况下作为推荐路径。自定义Python代码需要 `--trust_remote_code true`；TUI同名选项则是布尔flag，语法不同。

## 中断与重试

Ctrl-C停止当前进程时，检查工具/子进程退出及已有产物。`--load_cache true`用于已有项目/步骤缓存恢复，不等于一个统一的会话选择器；先核对配置和缓存对应关系，再重试。

首次默认Agent可能下载依赖；保持网络并阅读进度。缺模块时确认当前python/pip属于同一环境，不在系统环境反复安装。

下一步：[配置](../core/configuration.md)、[工作流](../core/workflows.md)、[排障](troubleshooting.md)。
