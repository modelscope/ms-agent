# MS-Agent WebUI

[English](./README.md)

这个目录包含 MS-Agent 的源码工作区 WebUI：

- `frontend/`：React Router 8 SSR、React 19、Vite 和 Ant Design。
- `backend/`：FastAPI、MS-Agent SDK 适配层以及 SSE 对话流。

当前支持的启动方式面向本地开发工作区。一条 `ms-agent ui` 命令会统一管理
两个子服务：

```text
http://127.0.0.1:7860       React Router 开发服务器
          /api/*  ────────> http://127.0.0.1:8000 上的 FastAPI
```

这不是生产部署方案，也不是独立 wheel 安装方式。命令需要在包含本
`webui/` 目录的 MS-Agent 源码 checkout 中运行，前端由开发服务器提供。


### 相比旧版 WebUI 的能力变化

当前界面替换了此前的 Vite/MUI 版本，定位是通用 Agent 工作区，**不再提供**旧版
那个专门的 **Deep Research** 视图（`deep_research_worker` / `DeepResearchView`
这套链路）。Agentic Insight v2 请改用 CLI 运行，见
[`projects/deep_research/v2`](../projects/deep_research/v2/README.md)。

### 必须遵守的运行约束

- 对话运行时、事件缓冲、turn lock、权限 Future 全部在进程内存里，后端**必须保持
  单 worker**。加 uvicorn worker 会静默破坏停止/中断、重新接管和授权弹窗。
- 对话走 SSE，整个栈里没有任何 WebSocket。
- `--host` 接受任意网卡，而这套栈**没有认证**。绑到非回环地址时，能访问端口的人
  就能使用这个 Agent——包括它的 shell 工具。

## 前置环境

| 工具 | 版本要求 | 用途 |
| --- | --- | --- |
| Python | 3.12 或更新版本 | WebUI 后端；`uv` 会创建独立环境 |
| [uv](https://docs.astral.sh/uv/) | 较新版本 | 同步 `webui/backend/.venv` |
| [Node.js](https://nodejs.org/) | **22.22.0 或更新版本** | React Router 8 的硬性要求 |
| [pnpm](https://pnpm.io/installation) | **10.x** | 同步前端依赖；项目固定为 10.17.1 |

无需预先激活 Python 3.12；uv 会选择兼容解释器，并可在缺失时自动下载。

启动前可以检查：

```bash
python --version
uv --version
node --version
pnpm --version
```

如果环境中提供 Corepack，可以这样启用项目固定的 pnpm 版本：

```bash
corepack enable
corepack prepare pnpm@10.17.1 --activate
```

### 不依赖 Corepack 安装工具

Node.js 25+ 不再内置 Corepack，而且在 conda 环境里「装了」不等于「会被解析到」——
PATH 可能仍然命中一个更旧的全局副本。版本检查失败时，启动器会打印它实际解析到的
可执行文件路径；把两个工具装进**当前激活环境**：

```bash
pip install uv                                        # uv 装进本环境的 bin/
npm install --global --prefix "$CONDA_PREFIX" pnpm@10.17.1
hash -r                                               # 刷新缓存后验证：
command -v uv pnpm                                    # 都应位于 $CONDA_PREFIX/bin
```

Node.js < 25 上，`corepack enable && corepack prepare pnpm@10.17.1 --activate`
仍是 pnpm 的可选替代方案。

## 快速开始

在 MS-Agent 仓库根目录执行：

```bash
pip install -e .
ms-agent ui
```

Windows 也可以使用：

```powershell
py -m pip install -e .
.\webui\scripts\start-webui.ps1
```

首次启动时，命令会自动完成相当于下面两步的依赖同步：

```bash
cd webui/backend && uv sync --locked --no-dev --inexact
cd webui/frontend && pnpm install --frozen-lockfile
```

后续启动仍会依据 lockfile 快速检查两个环境。同步过程不会安装全局 Python
或 Node 包。两个服务就绪后，浏览器会自动打开
<http://127.0.0.1:7860>。

如果暂时没有模型凭据，只想确认界面和交互，可以使用内存 mock 后端：

```bash
ms-agent ui --mock
```

在启动终端中按 `Ctrl+C` 会同时停止两个服务。

## 配置模型

打开 WebUI 不要求预先设置环境变量。真实对话最简单的配置方式是在页面中完成：

1. 启动 `ms-agent ui`。
2. 打开“设置 → 模型设置”。
3. 选择内置供应商，或者添加兼容的自定义供应商。
4. 根据需要配置 API Key 和 Base URL。
5. 为该供应商添加模型。
6. 选择默认供应商和默认模型。

除非显式设置 `MS_AGENT_HOME`，这些设置会和常规 MS-Agent CLI/TUI 共享
`~/.ms_agent`。通过页面保存的供应商凭据会以明文写入该目录下的
`settings.json`，请勿提交或对外分享该文件。

## 配置文件与环境变量

后端会按照从通用到具体的顺序读取：

```text
<仓库根目录>/.env
<仓库根目录>/webui/.env
<仓库根目录>/webui/backend/.env
```

最终优先级为：

```text
真实进程环境 / 启动器注入
    > webui/backend/.env
    > webui/.env
    > 仓库根目录 .env
```

dotenv 文件不会覆盖真实进程环境变量。所有已加载变量也可以供 MCP 配置中的
`${NAME}` 占位符在运行时解析。上述 `.env` 文件均已被 Git 忽略。

需要脚本化或高级配置时，可以复制模板：

```bash
cp webui/backend/.env.example webui/backend/.env
```

PowerShell 对应命令：

```powershell
Copy-Item .\webui\backend\.env.example .\webui\backend\.env
```

### 首次模型初始化变量

下面这些变量是浏览器配置的可选替代方案：

| 变量 | 含义 |
| --- | --- |
| `MS_AGENT_LLM_MODEL` | 要初始化的模型 ID。**不设置它，初始化根本不会执行**，其余三个变量也随之失效。 |
| `MS_AGENT_LLM_PROVIDER` | 初始化使用的 MS-Agent 供应商 ID（默认 `openai`）。必须真的提供上面那个模型：`qwen*` 属于 DashScope/ModelScope，不属于 OpenAI。 |
| `OPENAI_API_KEY` | 凭据，**仅当**供应商是 `openai` 时生效。其他供应商各自读取自己的变量（`DASHSCOPE_API_KEY`、`DEEPSEEK_API_KEY` 等）。 |
| `OPENAI_BASE_URL` | Base URL，同样只在 `openai` 时生效。 |

初始化只会补充尚不存在的 `llm` 配置。如果 `~/.ms_agent/settings.json`
（或 `MS_AGENT_HOME` 指向的目录）已经包含 `llm`，修改这些环境变量**不会**
覆盖原配置。后续请在“设置 → 模型设置”中修改。

### 可选运行变量

| 变量 | 含义 |
| --- | --- |
| `MS_AGENT_HOME` | 覆盖 SDK 数据目录；默认是 `~/.ms_agent` |
| `EXA_API_KEY` | 使用 Exa 网页搜索时的可选凭据 |
| 任意 `${NAME}` 对应变量 | 在 MCP 配置中运行时展开 |

### 由启动器管理的变量

正常使用 `ms-agent ui` 时不需要手工设置：

| 变量 | 管理方式 |
| --- | --- |
| `HOST`、`PORT` | FastAPI 内部地址，由启动参数决定 |
| `AGENT_BACKEND` | 默认 `ms_agent`；使用 `--mock` 时为 `mock` |
| `API_BASE_URL` | 启动器注入 React Router 进程 |
| `CORS_ORIGINS` | 通常只在手工分别启动服务时需要关注 |

## 命令参数

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--host HOST` | `127.0.0.1` | 前端监听地址 |
| `--port PORT` | `7860` | 前端端口和浏览器访问端口 |
| `--backend-port PORT` | `8000` | 内部 FastAPI 端口 |
| `--reload` | 关闭 | Python 后端源码变化时自动重载；前端始终启用 HMR |
| `--mock` | 关闭 | 使用无需模型凭据的内存演示数据 |
| `--skip-install` | 关闭 | 跳过两项依赖同步；任一项目本地环境缺失时会报错。使用它时只需要 PATH 上有 Node.js——`uv` 与 `pnpm` 完全不会被解析 |
| `--no-browser` | 关闭 | 不自动打开浏览器 |
| `--production` | 不支持 | 保留参数，使用时会明确报错并退出 |

示例：

```bash
# 修改前后端端口
ms-agent ui --port 8080 --backend-port 8001

# 使用 mock 数据开发界面
ms-agent ui --mock --reload

# 不自动打开浏览器
ms-agent ui --no-browser

# 明确允许局域网访问前端
ms-agent ui --host 0.0.0.0
```

后端仍然只监听 `127.0.0.1`，浏览器 API 请求通过前端代理。对外暴露开发
服务器并不等同于生产部署，也不会自动增加身份验证或生产级安全能力。

## 手工分别启动两个服务

需要独立调试前后端时，可以使用两个终端。正常使用不需要执行这些步骤。

### 1. 后端

如果要手工启动真实 MS-Agent 后端，先创建 `webui/backend/.env` 并设置
`AGENT_BACKEND=ms_agent`。没有该设置时，手工启动的后端默认使用 mock 数据。

```bash
cd webui/backend
uv sync --locked
uv run --frozen dev
```

后端监听 <http://127.0.0.1:8000>，健康检查地址是
<http://127.0.0.1:8000/api/health>。后端依赖以 editable 方式指向当前所在的
MS-Agent checkout，因此框架源码修改可以直接生效。

### 2. 前端

在另一个终端执行：

```bash
cd webui/frontend
pnpm install --frozen-lockfile
pnpm dev
```

打开 <http://localhost:5173>。Vite 开发服务器会把 `/api/*` 代理到
`http://127.0.0.1:8000`，SSR 路由 loader 默认也使用这个地址。如果手工修改
后端端口，需要在启动前端进程前相应设置 `API_BASE_URL`。

## 测试

后端测试位于 `webui/backend/tests`，在后端自己的环境里运行。注意启动器同步该环境时
**不含** dev 组，测试前先补装一次：

```bash
cd webui/backend
uv sync --locked            # 含 dev 组（pytest）
./.venv/bin/python -m pytest
```

启动器/契约测试放在仓库的 tests 里，任何装有 SDK 的 Python 都能跑：

```bash
python -m pytest tests/cli/test_ui.py tests/ui
```

前端暂无自动化测试；`pnpm typecheck` 是门禁，UI 回归靠真实 Chrome 走查。

仓库 CI（`pytest tests`）**不包含** `webui/backend/tests`——它的依赖（FastAPI 等）
没有装在那里。改动后端或它消费的 SDK 面时，请按上面的方式在本地运行。

## Windows

推荐使用 PowerShell。在仓库根目录执行随项目提供的 UTF-8 启动脚本：

```powershell
.\webui\scripts\start-webui.ps1
```

所有启动参数都会原样转发：

```powershell
.\webui\scripts\start-webui.ps1 --mock --no-browser
```

这个脚本会把当前控制台切换为 UTF-8，并设置 `PYTHONUTF8` 和
`PYTHONIOENCODING`，保留了此前 Windows 用户反馈控制台乱码后加入的专项修复。

如果本机 PowerShell 执行策略阻止脚本，只为当前进程临时放开：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\webui\scripts\start-webui.ps1
```

这不会修改机器级或用户级策略。启动器使用 Windows 进程组；按 `Ctrl+C` 时会
关闭后代 Python/Node 进程。内置终端使用 Windows 原生命令处理器，不依赖额外
的 POSIX `sh`。支持包含空格和非 ASCII 字符的仓库路径；为了获得更可靠的文件
监听效果，建议把仓库放在本地文件系统中。

Windows 环境检查：

```powershell
Get-Command ms-agent, uv, node, pnpm
node --version
pnpm --version
```

## 常见问题

### 找不到必需命令

安装缺少的工具，重新打开终端以刷新 `PATH`，然后执行上面的版本检查。启动器
会在安装依赖前拒绝低于 22.22.0 的 Node，以及不属于 10.x 系列的 pnpm。

### 依赖同步失败

首次启动需要下载 Python 和 Node 依赖，可能需要一些时间。检查软件源与网络，
然后重新执行 `ms-agent ui`。如需单独观察失败步骤，可运行“手工分别启动”一节
中的两条同步命令。只有在 `webui/backend/.venv` 与
`webui/frontend/node_modules` 都已存在时才适合使用 `--skip-install`。

### 端口已被占用

同时指定新的前后端端口：

启动器会在同步任何依赖**之前**检查两个端口，所以失败很快且会点名端口。另外有两条
强制规则：

- `--port` 与 `--backend-port` 不能相同；
- 前端使用 `--strictPort`，端口被占用是硬失败，不会自动顺延到下一个端口。

显式指定两个端口：

```bash
ms-agent ui --port 8080 --backend-port 8001
```

Windows 可以这样检查默认端口：

```powershell
Get-NetTCPConnection -LocalPort 7860,8000 -ErrorAction SilentlyContinue
```

### 页面能打开，但 API 请求失败

访问 <http://127.0.0.1:8000/api/health>，或对应的自定义后端端口。如果健康
检查失败，请查看启动终端中的后端错误。手工启动时还要确认前端
`API_BASE_URL` 与后端端口一致。

### 对话提示供应商、模型或认证错误

回到“设置 → 模型设置”，同时检查供应商凭据、模型条目和已选择的默认模型。
如果修改环境变量后没有变化，通常是已有 `settings.json.llm` 按设计保持了更高
的配置真值，应改用页面设置。

### 浏览器没有自动打开

手工打开启动器打印的前端地址即可。浏览器打开失败不会停止服务；
`--no-browser` 会主动禁用这一步。

### Windows 控制台乱码

停止启动器，改用 PowerShell 中的 `webui\scripts\start-webui.ps1`。直接执行
`ms-agent ui` 仍然可用，但它无法反向修改已经用传统代码页启动的父控制台编码。

### `--production` 立即退出

这是预期行为。当前一命令模式刻意面向本地源码 checkout，运行 React Router
开发服务器与 FastAPI。生产 SSR 部署、静态打包、wheel 和镜像不属于这个启动器
的职责范围。
