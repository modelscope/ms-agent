# TUI / WebUI 设置账本 — 端到端验收

两端必须同一 `MS_AGENT_HOME`、同一工作目录。**不要用开发者自己的 `~/.ms_agent`。**

代码：

- SDK：`modelscope-agent-feat-tui-align`（分支 `feat/tui-align-webui`）
- WebUI：GitLab `ms-agent-webui-feat-tui-align`（WebUI 后端请用这份 SDK，例如 `PYTHONPATH` 或 editable install）

## 共用环境

```bash
export MS_AGENT_HOME=/tmp/ms-agent-align-e2e
rm -rf "$MS_AGENT_HOME"
mkdir -p "$MS_AGENT_HOME" /tmp/align-work

# WebUI：启动进程时带上同一 MS_AGENT_HOME
# TUI（在 SDK 工作树）：
ms-agent tui --work-dir /tmp/align-work
```

换期前可清空 `$MS_AGENT_HOME`。磁盘是唯一验收源；当前这一轮对话若没跟上，脚本会写「需 `/new`」。

对齐标准：**同一账本**（TUI slash 能管 WebUI 设置页写的那些文件），不是 TUI/WebUI 界面完全一致。

**不测：** 工作区编辑器、多项目 IDE、卡片回放、外观主题、权限 UX、把 TUI 事件还原成 WebUI 卡片。

---

## 本期功能清单（提测用）

每条都要两边看：TUI 命令 → 磁盘 → 刷新 WebUI；以及 WebUI 改完 → TUI 再读。建议按 0 → 5 顺序，0 不过后面的设置对不齐。

### A. 项目与会话（第 0 期）

| # | 功能 | 怎么测 | 通过标准 |
|---|---|---|---|
| A1 | 同一文件夹 = 同一项目 | WebUI 打开 `W`，再 TUI `--work-dir W` | 不是两套 project id |
| A2 | WebUI 会话 TUI 能续 | WebUI 说一句 → TUI `/sessions` `/resume` | 能读到那句 |
| A3 | TUI 会话 WebUI 能看到 | TUI 说一句 → 刷新 WebUI | 同一项目、同一会话树 |
| A4 | TUI 空 home 能启动 | 不先开 WebUI，直接 `ms-agent tui` | 不因 todo_list 当 MCP 崩溃 |
| A5 | TUI 默认模型跟 WebUI | WebUI 设默认模型后新开 TUI（无 `--config`） | 第一轮就用该模型，不必先 `/model` |
| A6 | 显式 `--config` 不被 settings 改掉 | `ms-agent tui --config custom.yaml` | 仍用 yaml 里的模型 |

### B. 模型（第 0 / 3 期）

落盘：`$MS_AGENT_HOME/settings.json` 的 `providers` / `default_model` / `llm`。

| # | 功能 | TUI | 通过标准 |
|---|---|---|---|
| B1 | 列出供应商 | `/model` `/model list` | 与 WebUI 模型设置同源；key 只显示 set/missing，无明文 |
| B2 | 切换当前模型 | `/model <model>` 或 `/model <provider>/<model>` | banner/当前模型变了；settings 的 default_model 更新；下一轮走新模型 |
| B3 | 新增供应商 | `/model provider add <id> key= url= protocol=` | WebUI 模型页出现该项 |
| B4 | 改 key | `/model provider key <id> <value>\|clear` | json 变了；列表仍不打印明文；当前供应商会尽量立刻生效 |
| B5 | 改 base_url | `/model provider url <id> <url>\|clear` | 同上 |
| B6 | 改协议/名称等 | `/model provider set <id> protocol= name=` | 只改给的字段，不把别的冲掉 |
| B7 | 模型目录 | `/model catalog add\|remove <id> <model>` | WebUI 该供应商的模型列表同步 |
| B8 | 不能删内置 | `/model provider remove openai`（无覆盖时） | 拒绝；有覆盖时只清覆盖，内置还在 |

### C. 搜索（第 1 期）

落盘：`settings.json` → `tools.web_search`。

| # | 功能 | TUI | 通过标准 |
|---|---|---|---|
| C1 | 看当前引擎 | `/search` `/search list` | 未配置时默认 tavily；当前项前有 `*` |
| C2 | 切引擎 | `/search engine tavily\|exa\|serpapi\|arxiv` | WebUI 搜索页下拉一致 |
| C3 | 写/清 key | `/search key <value>` `/search key clear` | 按**当前引擎**写 `{engine}_api_key`；arxiv 无需 key |
| C4 | 切引擎不丢别人的 key | 先给 exa 写 key，再切 tavily | json 里 `exa_api_key` 还在 |
| C5 | 开关 | `/search enable\|disable` | WebUI 搜索启用状态一致 |
| C6 | WebUI → TUI | WebUI 改引擎并保存 | TUI `/search` 已是新引擎 |
| C7 | （有网，非必须）对话走该引擎 | `/new` 后让模型去搜 | 工具用的是所选引擎 |

### D. 指令与 Profile（第 2 期）

| # | 功能 | TUI | 落盘 | 通过标准 |
|---|---|---|---|---|
| D1 | 看指令 | `/instruction` 或 `/ins` | — | 能分开显示全局 / 项目 |
| D2 | 写/清全局指令 | `/instruction global <text>\|clear` | `$MS_AGENT_HOME/AGENTS.md` 用户区 | 保留模板头；WebUI 个性化指令同一句 |
| D3 | 写/清项目指令 | `/instruction project <text>\|clear` | `<work>/.ms_agent/AGENTS.md` | **绝不改** 仓库根 `<work>/AGENTS.md` |
| D4 | 看 Profile | `/profile` | `$MS_AGENT_HOME/PROFILE.md` | Call me / About |
| D5 | 称呼 | `/profile callme <name>\|clear` | 同上 | 清称呼不抹掉 About |
| D6 | 自我介绍 | `/profile about <text>\|clear` | 同上 | 清 About 不抹掉称呼 |
| D7 | 下一轮生效 | 改完再发一轮 | — | 不必 `/new`；本轮已发出的 prompt 不回写 |

### E. MCP（第 0 / 4 期）

落盘：`$MS_AGENT_HOME/mcp.json`（及 `settings.json` 的 mcp_servers）；项目级 `<work>/.ms_agent/mcp.json`。

| # | 功能 | TUI | 通过标准 |
|---|---|---|---|
| E1 | 列表 | `/mcp`（当前列表 + usage）；`/mcp list [global\|project]` | 与 WebUI MCP 页一致 |
| E2 | 添加 HTTP | `/mcp add <name> [global\|project] url=<url>` | WebUI 能看到同名同 URL |
| E3 | 添加 stdio | `/mcp add <name> global command="npx -y …"` | command/args 拆对 |
| E4 | 更新 | `/mcp update <name> [global\|project] url=\|command=` | 同一条被改，不是又建一条 |
| E5 | 启用/停用 | `/mcp enable\|disable <name> [global\|project]` | WebUI 开关一致 |
| E6 | 删除 | `/mcp remove <name> [global\|project]` | WebUI 不再显示（或项目级遮罩全局） |
| E7 | 导入 json | `/mcp json <file.json>` | 能进 mcp.json |
| E8 | 本会话连接 | add/update 后 | 能连则立刻连；否则提示 `/new` |

### F. 技能（第 0 / 4 期）

托管副本：`$MS_AGENT_HOME/skills/<id>` 或 `<work>/.ms_agent/skills/<id>`。

| # | 功能 | TUI | 通过标准 |
|---|---|---|---|
| F1 | 列表 | `/skills`（当前列表 + usage）；`/skills list` | 与 WebUI 技能页能对上 |
| F2 | 导入 | `/skills add <含 SKILL.md 的目录> [global\|project]` | 拷进 live tree；WebUI 能看到；源目录还在 |
| F3 | 启用/停用 | `/skills enable\|disable <id> [global\|project]` | 写 skills.json disabled；本会话能跟上 |
| F4 | 删除托管副本 | `/skills remove <id> [global\|project]` | 只删 live tree；**源目录不删**；WebUI 那条消失 |
| F5 | 不删自动发现 | 对 `.agents/skills` 等只读项 `/skills remove` | 提示 disable instead，不得 rmtree 用户仓库 |

### G. 记忆（第 5 期）

两套开关，不要测混：

1. **全局默认** `settings.json` → `personalization.memory_enabled` / `memory_backend`：只影响**尚未登记的新文件夹**。
2. **当前项目** `projects/<id>/.ms_agent/project.json` → `memory_enabled`：真正注入记忆工具。file 后端文件在 `<work>/.ms_agent/memory/MEMORY.md`。

| # | 功能 | TUI | 通过标准 |
|---|---|---|---|
| G1 | 看状态 | `/memory` | 能区分全局默认 vs 本项目 |
| G2 | 全局默认 | `/memory global on\|off` | WebUI 个性化默认记忆一致；**已有项目不变** |
| G3 | 新文件夹继承 | 全局 on 后，TUI 打开一个从没登记过的目录 | 该项目 memory_enabled 为 true |
| G4 | 本项目开/关 | `/memory on\|off` 或 `/memory project on\|off` | WebUI 该项目记忆开关一致；file 时对话能走到 unified_memory |
| G5 | 后端 | `/memory backend file\|vector`（全局默认）；`/memory project backend file\|vector`（本项目） | file：TUI 用 MEMORY.md；vector：只落盘给 WebUI，**TUI 不得悄悄写成 file** |
| G6 | WebUI → TUI | WebUI 打开同一项目的 file 记忆 | 新开 TUI `/memory` 项目为 on |
| G7 | 中途关掉 | 已经 load 过记忆后再 `/memory off` | 提示 `/new` 才卸工具 |

### 本会话未覆盖（不要当成回归失败）

- 工作区编辑器、多项目、卡片回放、外观
- 权限卡片 / Ask 流 UX
- TUI 把 vector/mem0 跑起来（vector 只要求落盘，真正跑在 WebUI）

逐步操作见下文各期；磁盘对不上时以 json / markdown 文件为准。

---

## 第 0 期：同一文件夹互续（请测试先跑）

验收：TUI 和 WebUI 看到同一项目、同一套 session，不再拆成两套 id。

### 0.1 WebUI → TUI 续聊

1. 按上面清空并 export `MS_AGENT_HOME`，工作目录 `W=/tmp/align-work`。
2. 打开 GitLab WebUI，用「打开文件夹 / 使用已有目录」选 `W`（不要「从零新建」到别的路径）。
3. 新开对话，发一句：`hello from web`。记下侧栏会话名称或 id。
4. 同一终端环境启动 TUI：`ms-agent tui --work-dir /tmp/align-work`。
5. 输入 `/sessions`：应能看到刚才那条 WebUI 会话。
6. `/resume <id或列表序号>`：应能读到 `hello from web`。
7. 再发一句 `hello from tui`，然后 `/quit`。
8. 刷新 WebUI 同一项目：侧栏仍是同一项目；点进刚才的会话（或 TUI 新开的那条）能看到 `hello from tui`。

**失败：** 出现两套 project、WebUI 看不到 TUI 说的话、TUI `/sessions` 为空、或 resume 没有 WebUI 那句。

### 0.2 TUI → WebUI 发现项目

1. 可用同一 `W`，或清空 home 后只先开 TUI：`ms-agent tui --work-dir /tmp/align-work`。
2. TUI 发一句 `hello from tui first`，`/quit`。
3. 打开 WebUI（同一 `MS_AGENT_HOME`）：项目列表应出现该文件夹；点进去能看到那条会话。

**失败：** WebUI 项目列表没有这个目录，或打开后会话是空的。

### 0.3 已有 slash 写盘（冒烟）

1. TUI `/model list`：能列出供应商（与 WebUI 设置 → 模型同源 `settings.json`）。
2. TUI：`/mcp add docs global url=https://example.invalid/mcp`
3. 刷新 WebUI 设置 → MCP：应出现名为 `docs` 的项，URL 一致。
4. （可选）TUI `/skills` 能列出；有现成 `SKILL.md` 目录时 `/skills add <path> global`，WebUI 技能页能看到。

**失败：** WebUI 完全看不到 TUI 刚加的 MCP。

### 0.4 空 home + 默认 yaml：TUI 能启动（todo_list 不是 MCP）

先前：`_apply_session` 写入 `tools.todo_list.plan_filename` 却没有 `mcp: false`，ToolManager 把它当 MCP 去连，报 `'url' or 'command' parameter is required`。WebUI 因为 `settings.json` 里已有 `todo_list.mcp: false` 所以没事。

1. 清空 `$MS_AGENT_HOME`（不要先开 WebUI，不要手改 yaml）。
2. `ms-agent tui --work-dir /tmp/align-work`
3. 应出现会话 banner 和输入框，**不得**在启动时因 todo_list / MCP url 崩溃。
4. 空 home、还没有 API key：应提示 `/model provider key` / `/model openai/<model>`，**不得直接退出**。配好 key 后再发一句即可；`/quit` 仍能离开。
5. 已有 key 时输入 `/quit` 正常退出即可。

**失败：** 启动即 traceback，或日志里出现 `'url' or 'command' parameter is required`。

### 0.5 TUI 第一轮推理用 WebUI 默认模型（不必再 `/model`）

先前：`/model list` 读 `settings.json`，真正跑模型仍走 `Config.from_task(agent.yaml)`（包装里的 Qwen3-235B）。要对齐得手动 `/model openai/qwen3.7-plus`。

1. 同一 `MS_AGENT_HOME`。WebUI 设置 → 模型，默认选 `openai/qwen3.7-plus`（或当前环境真实在用的那条）并保存。
2. 新开 TUI：`ms-agent tui --work-dir /tmp/align-work`。`/model` 只写两端共用的 `default_model`，不再给这个文件夹钉一份 `.ms_agent/config.yaml`；之后在 WebUI 改默认，下次打开 TUI（无 `--config`）应跟上。
3. `/model`（无参数）或看 banner：当前模型应是 WebUI 刚设的那条，而不是 yaml 里的 `Qwen/Qwen3-235B-A22B-Instruct-2507`。
4. 发一句短回复（如 `ping`）。请求应打到该默认模型，不必先 `/model openai/qwen3.7-plus`。
5. （对照）`ms-agent tui --config /path/to/custom.yaml --work-dir ...`：应继续用 yaml 里写死的模型，不被 settings 改掉。

**失败：** 默认 TUI 仍在用包装 yaml 的模型；或显式 `--config` 反而被 settings 覆盖；或 TUI `/model` 之后 WebUI 再改默认，这个文件夹的 TUI 仍钉在旧模型上。

---

## 第 1 期：搜索

磁盘：`$MS_AGENT_HOME/settings.json` → `tools.web_search.engine` 以及 `{engine}_api_key`（`arxiv` 无 key）。切引擎不得删掉别的引擎的 key。

TUI 命令：

```
/search
/search list
/search engine tavily|exa|serpapi|arxiv
/search key <value>
/search key clear
/search enable|disable
```

### 1.1 TUI → WebUI

1. 同一隔离 home。TUI：`/search` 默认引擎应为 `tavily`（未配置时）。
2. `/search engine arxiv`。打开 `settings.json`，确认 `tools.web_search.engine` 为 `arxiv`。
3. 刷新 WebUI 设置 → 搜索：下拉为 arXiv，无 API key 框（或标明无需 key）。
4. TUI：`/search engine exa` 然后 `/search key sk-test-exa`。
5. json 中应有 `exa_api_key`；刷新 WebUI：引擎为 Exa，且显示已配置 key（不要要求页面把明文 key 打出来）。
6. TUI 再 `/search engine tavily`：json 里 `exa_api_key` **仍在**，`engine` 为 `tavily`。WebUI 切到 Tavily 后，再切回 Exa，key 仍显示已配置。

### 1.2 WebUI → TUI

1. WebUI 搜索页改成 `serpapi`（或当前页上另一个引擎）并保存。
2. TUI `/search`：Engine 应已变成该引擎。`/search list` 当前项前有 `*`。

### 1.3 对话是否走到该引擎（有网，非必须）

1. `/new` 或新开会话后，请模型「用搜索查一下今天日期」之类。
2. 工具调用应使用所选引擎。当前会话若仍用旧引擎，先 `/new` 再试。

**失败：** 两边引擎不一致；切 Tavily 后 Exa 的 key 从 json 里消失；arxiv 仍出现 key 输入且 TUI `/search key` 能写进去。

---

## 第 2 期：指令与 Profile（`AGENTS.md` / `PROFILE.md`）

磁盘（与 WebUI「个性化 / 项目指令 / 用户 Profile」同一套文件）：

| 范围 | 文件 | TUI |
|---|---|---|
| 全局指令 | `$MS_AGENT_HOME/AGENTS.md` 的用户区（保留模板头） | `/instruction global …` |
| 项目指令 | `<work>/.ms_agent/AGENTS.md` | `/instruction project …` |
| 用户 Profile | `$MS_AGENT_HOME/PROFILE.md` | `/profile callme` / `/profile about` |

**界面绝不写** `<work>/AGENTS.md`（仓库根，给团队/编码助手用的；SDK 只读，排在私有槽之前）。

```
/instruction
/instruction global|project
/instruction global|project <text>
/instruction global|project clear
/profile
/profile callme <name>|clear
/profile about <text>|clear
```

下一轮对话就会读到新文件；不必 `/new`，但已发出的那一轮不会回写旧 system prompt。

### 2.1 TUI → WebUI 全局指令

1. 同一隔离 home。TUI：`/instruction global Always answer in French.`
2. 打开 `$MS_AGENT_HOME/AGENTS.md`：应仍有 `---` 头，用户区有那句。
3. 刷新 WebUI 设置 → 个性化 → 个性化指令：应显示同一句。
4. 新开一轮对话，模型应遵守该全局指令。

### 2.2 TUI → WebUI 项目指令（只写私有槽）

1. 工作目录 `W` 里若已有仓库根 `AGENTS.md`，先记下内容（或故意写一句 `keep me at root`）。
2. TUI：`/instruction project This project uses FastAPI.`
3. 确认 `W/.ms_agent/AGENTS.md` 是项目指令；**根目录 `W/AGENTS.md` 一字未改**。
4. 刷新 WebUI 该项目的「项目指令」：应是 FastAPI 那句，不是根文件。

### 2.3 WebUI → TUI

1. WebUI 个性化指令改成 `Be terse.` 并保存。
2. TUI `/instruction global`：应看到 `Be terse.`
3. WebUI 用户 Profile：称呼 `Alice`，自我介绍 `I work on agents.` 保存。
4. TUI `/profile`：Call me 为 Alice，About 含那句。

### 2.4 Profile 字段互不覆盖

1. TUI `/profile callme Alice` 再 `/profile about researcher`
2. `/profile callme clear`：称呼空了，About 仍是 researcher。
3. 打开 `PROFILE.md`：`- Call me:` 行已去掉，自我介绍还在。

**失败：** TUI 改了仓库根 `AGENTS.md`；WebUI 看不到 TUI 刚写的全局/项目指令；`/profile callme` 把 about 区抹掉。

---

## 第 3 期：模型供应商 CRUD（key / base_url / catalog）

磁盘：`$MS_AGENT_HOME/settings.json` 的 `providers` / `default_model` / `llm`（与 WebUI「模型设置」同一套）。内置供应商不能删；同名自定义条目是凭证覆盖。列表里的 key 只显示 set/missing，不打印明文。`/model list live` 对已配 key 的供应商现拉 `/v1/models`，只展示对话/视觉理解 id（图生、视频生、embedding 会丢掉），结果不写回 json。

```
/model list
/model list live [provider]
/model <provider>/<model>
/model provider add <id> [key=] [url=] [protocol=openai|anthropic] [name=]
/model provider set <id> [key=] [url=] [protocol=] [name=]
/model provider key <id> <value>|clear
/model provider url <id> <url>|clear
/model provider remove <id>
/model catalog add <id> <model>
/model catalog remove <id> <model>
```

当前正在用的供应商改 key/url 后，TUI 会尽量立刻重建 LLM。

### 3.1 TUI → WebUI

1. 同一隔离 home。TUI：`/model provider add acme key=sk-test-acme url=https://example.invalid/v1 protocol=openai`
2. `/model catalog add acme a-1`
3. 打开 `settings.json`：应有 `providers.acme`，含 key、url、`models: ["a-1"]`。
4. 刷新 WebUI 设置 → 模型：应出现 acme，且显示已配置 key（不要要求页面打出明文）。
5. TUI：`/model provider key acme sk-test-acme-2`。json 里 key 已换；WebUI 刷新仍显示已配置。
6. TUI：`/model openai/qwen3.7-plus`（或当前真实在用的那条）后发一句 `ping`，应能出回复。

### 3.2 不能删内置

1. TUI：`/model provider remove openai`（若没有自定义覆盖）：应拒绝。
2. 若曾 `/model provider key openai …` 写过覆盖：`remove` 只清覆盖，内置 openai 仍在 `/model list`。

**失败：** WebUI 看不到 TUI 刚加的供应商；`/model list` 打印了明文 key；删掉了内置 openai。

---

## 第 4 期：`/mcp update` 与 `/skills remove`

磁盘：MCP 仍是 `mcp.json` / `settings.json` 的 `mcpServers`；技能删除只动 **managed live tree**（`$MS_AGENT_HOME/skills/<id>` 或 `<work>/.ms_agent/skills/<id>`），与 WebUI 删「托管副本」一致。不要删 `.agents/skills` 里自动发现的目录。

```
/mcp update <name> [global|project] url=... | command=...
/skills remove <id> [global|project]
```

### 4.1 MCP update

1. TUI：`/mcp add docs global url=https://example.invalid/mcp`
2. `/mcp update docs global url=https://example.invalid/v2`
3. 打开 `$MS_AGENT_HOME/mcp.json`：docs 的 url 为 v2。
4. 刷新 WebUI 设置 → MCP：同一条 docs，URL 已改。

### 4.2 Skills remove

1. 准备一个带 `SKILL.md` 的临时目录，TUI：`/skills add <path> global`
2. 确认 `$MS_AGENT_HOME/skills/<dirname>/SKILL.md` 存在；WebUI 技能页能看到。
3. TUI：`/skills remove <dirname> global`
4. 该 managed 目录应已删除；**原始临时目录还在**。WebUI 刷新后这条托管技能消失。
5. 对自动发现/只读技能：`/skills remove` 应提示 disable instead，不得 `rmtree` 用户仓库里的技能目录。

**失败：** update 没改盘；remove 把导入源目录也删了；或删掉了 `.agents/skills` 自动发现项。

---

## 第 5 期：记忆开关（PersonalizationSettings + 项目开关）

两端两套开关，语义与 WebUI 相同：

1. **全局默认** `$MS_AGENT_HOME/settings.json` → `personalization.memory_enabled` / `memory_backend`：只影响**新打开的文件夹**。
2. **当前项目** `<home>/projects/<id>/.ms_agent/project.json` 的 `memory_enabled`：真正往 agent 配置注入 `memory.unified_memory`（file 后端 → `<work>/.ms_agent/memory/MEMORY.md`）。

```
/memory
/memory on|off
/memory project on|off
/memory global on|off
/memory backend file|vector
/memory project backend file|vector
```

TUI 的 vector/mem0 不在本期接；选 vector 只落盘给 WebUI 用，**不会**悄悄改写成 file。当前会话若已加载过记忆工具，关记忆后需要 `/new`。

### 5.1 全局默认 → 新项目

1. TUI：`/memory global on`
2. `settings.json` 的 `personalization.memory_enabled` 为 true。
3. 刷新 WebUI 个性化：默认记忆开。
4. 用**尚未登记**的新目录再开一次 TUI：该项目 `memory_enabled` 应为 true（已有项目不受全局开关改写）。

### 5.2 项目开关 → 本会话

1. 同一工作目录。TUI：`/memory on`（或 `/memory project on`）
2. 项目 meta 里 `memory_enabled` 为 true。
3. `/new` 后再请模型「记住我喜欢快排」之类；应能走到 `unified_memory` 工具（file 后端）。
4. 刷新 WebUI 该项目记忆开关：应为开；`MEMORY.md` 若已写入，WebUI 记忆页能看到。

### 5.3 WebUI → TUI

1. WebUI 打开同一项目，打开记忆（file）。
2. 新开 TUI 同一 `--work-dir`：`/memory` 项目应为 on；配置里有 `memory.unified_memory`。

**失败：** 只改了全局 settings、当前项目对话仍没有记忆工具；或 TUI 把 vector 项目悄悄写成了 MEMORY.md。
