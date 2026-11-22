# Capability Gateway（能力网关）

Capability Gateway 将 ms-agent 的 projects、components 与原子工具封装为统一的
descriptor / registry / 异步 API，并以 **MCP 工具** 的形式暴露给外部宿主 Agent
（nanobot、OpenClaw、Hermes、Cursor、Claude Desktop 等）。

它**不会**注入到进程内 `LLMAgent` 的 ToolManager。宿主通过 MCP 发现工具；
用法说明在技能包 [`ms-agent-skills/`](https://github.com/modelscope/ms-agent/tree/main/ms-agent-skills) 中。

## 入口

| 表面 | 入口 |
|------|------|
| Python API | `from ms_agent.capabilities import create_registry` |
| MCP 服务 | `python -m ms_agent.capabilities.mcp_server` |
| 健康检查 | `python -m ms_agent.capabilities.mcp_server --check` |
| 技能文档 | [`ms-agent-skills/SKILL.md`](https://github.com/modelscope/ms-agent/blob/main/ms-agent-skills/SKILL.md) |

`--check` 同时报告 `registered_total`（31 个 descriptor）与
`mcp_exposed_total`（30 个 MCP 工具）。父组件 `lsp_code_server` 会注册但不作为独立
MCP 工具暴露，其子能力 `lsp_check_directory` / `lsp_update_and_check` 会暴露。

`lsp_check_directory` 当前只索引文件，空诊断列表不表示项目检查通过；增量检查使用 `lsp_update_and_check`，最终仍需项目类型检查或测试。TypeScript 由 `npx` 解析本地或全局依赖。Exa 搜索可配置 `EXA_API_KEY` 或 `EXA_API_KEYS` 多 Key 池。

## 架构

```
宿主 Agent  --MCP stdio-->  mcp_server.py (FastMCP)
                                |
                          CapabilityRegistry
                           /        |        \
                   进程内执行    AsyncTaskManager   子进程
                 (fs/search/lsp/   (submit/check/   (deep_research,
                  delegate/doc)     get/cancel)      fin/code/cinema)
```

长任务优先使用 async 的 submit / check / get 模式。`AsyncTaskManager` **仅进程内有效**：
MCP server 进程重启后 task_id 会丢失。

## 技能包

仓库根目录 `ms-agent-skills/` 文档化全部 30 个 MCP 工具与 SOP：

- 通过 `examples/capability/*/install_skill.sh` 安装到宿主技能目录
- 通过 `ms-agent-skills/scripts/install_into_ms_agent.sh` 安装到
  ms-agent 自身技能树（`$MS_AGENT_HOME/skills/ms-agent`，默认 `~/.ms_agent/skills/ms-agent`）
- 当前源码打包时复制到 wheel 内的 `ms_agent/skills/ms-agent/`；这是源码分发机制，不代表旧 PyPI 1.6.0 已包含新技能资源

校验 Capability Index 与真实 registry 是否一致：

```bash
python ms-agent-skills/scripts/validate_capability_index.py
```

## 集成示例

见 [`examples/capability/`](https://github.com/modelscope/ms-agent/tree/main/examples/capability)（nanobot / OpenClaw / Hermes，
共用说明见 `setup.md`）。

## 相关文档

- [Agent Skills](agent-skills.md) — ms-agent 进程内技能运行时
- [Tools](tools.md) — LLMAgent 侧 MCP 客户端配置
