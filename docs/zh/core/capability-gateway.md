# MCP 能力服务

Capability Gateway把MS-Agent项目、组件和原子工具暴露为MCP工具，让外部Agent调用。这与MS-Agent作为[MCP客户端](mcp-client.md)使用外部工具相反；网关不会自动注入每个进程内LLMAgent的工具列表。

## 检查并启动

```bash
python -m ms_agent.capabilities.mcp_server --check
python -m ms_agent.capabilities.mcp_server
```

健康检查当前报告31个注册descriptor、30个MCP工具。父组件 `lsp_code_server`提供组件说明但不独立暴露，两个子能力独立暴露。数量是发现口径，不代表全部工具依赖/凭据已就绪。

宿主配置的命令使用安装MS-Agent的Python绝对路径，参数为 `-m ms_agent.capabilities.mcp_server`。stdio模式协议走stdout，Python库输出受保护；HTTP/SDK调用不替换宿主stdout。

## 长任务调用

```{mermaid}
sequenceDiagram
 participant Host as 宿主Agent
 participant MCP as MCP服务
 participant Task as 任务管理器
 Host->>MCP: submit task
 MCP->>Task: 启动工作
 MCP-->>Host: task_id
 Host->>MCP: check progress
 MCP-->>Host: running / completed / failed
 Host->>MCP: get result
 MCP-->>Host: 结果、产物或错误
```

长任务优先submit/check/get；同步工具可能长时间占用请求。任务状态主要保存在进程内，服务重启后task_id不能被当作持久任务凭证；输出文件与任务状态是不同资产。

## 依赖与已知边界

- 委派凭据按所选配置Provider解析；显式配置路径不存在会报错，不静默换成默认Agent。
- Exa接受 `EXA_API_KEY` 或 `EXA_API_KEYS`；其他引擎有自己的Key，arXiv无需Key。
- TypeScript通过npx解析语言服务器；目录LSP检查只索引，不能将空diagnostics当成项目无错。增量检查和最终类型测试分别进行。
- wheel 构建会将单技能包 `ms-agent-skills/` 放到 `ms_agent/skills/ms-agent/`。

技能说明与宿主集成见[仓库技能包](https://github.com/modelscope/ms-agent/tree/main/ms-agent-skills)和[示例](https://github.com/modelscope/ms-agent/tree/main/examples/capability)。安装技能与建立MCP连接是两步，缺一不可。

实现：`capabilities/mcp_server.py`、`registry.py`、`async_task.py`及wrappers。
