# MS-Agent WebUI

在浏览器里使用 MS-Agent，让智能体围绕你的项目完成资料检索、代码编写和文件处理。对话、工具调用和生成结果都在同一个工作台中，方便查看过程并继续追问。[English](README.md)

- **按项目开展工作**：打开本地文件夹，管理多个会话，浏览和编辑项目文件。
- **看清任务进展**：流式查看回复、思考过程、工具调用和生成的文件。
- **选择模型与工具**：配置模型服务，接入 MCP 工具，并为项目启用所需的技能。
- **延续项目上下文**：保留会话记录，管理记忆，在后续对话中继续工作。

## 快速开始

**新版 WebUI 尚未发布到 PyPI，请按以下流程克隆源码并可编辑安装。** PyPI 上的 `ms-agent==1.6.0` 使用旧版 WebUI，不能用于体验本指南介绍的新版工作台。

### 1. 准备环境

| 工具 | 要求 | 用途 |
| --- | --- | --- |
| [Python](https://www.python.org/downloads/) | 3.12 或更高版本 | 运行 MS-Agent 和 WebUI 后端 |
| [Node.js](https://nodejs.org/en/download) | 22.22.0 或更高版本 | 运行 WebUI 前端服务 |
| pnpm | 10.17.1 | 安装前端依赖 |
| [uv](https://docs.astral.sh/uv/) | 0.5 或更高版本 | 准备独立的后端 Python 环境 |
| Git | 当前可用版本 | 克隆源码 |

#### 首次配置

以下命令默认使用 macOS / Linux 的 shell。如果还没有合适的 Python 或 Node.js，可以按下面的流程安装；已有环境的用户可跳到[检查并激活环境](#检查并激活环境)。先运行 `git --version`；如果使用 macOS 时提示安装 Command Line Tools，完成安装后再继续。

##### 安装 Node.js

安装 [nvm](https://github.com/nvm-sh/nvm)，并通过它安装 Node.js。Node 安装在用户目录中，后续安装 pnpm 无需 `sudo`：

```bash
curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
export NVM_DIR="$HOME/.nvm"
source "$NVM_DIR/nvm.sh"
nvm install 22.22.0
npm install --global pnpm@10.17.1
node --version
pnpm --version
```

##### 安装 Python

安装 uv，用它下载 Python 3.12 并创建带 pip 的环境。在准备存放项目的目录执行：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
uv venv --python 3.12 --seed ms-agent-env
source ms-agent-env/bin/activate
python --version
pip --version
```

保持这个终端和环境，继续下面的 uv 检查及源码安装即可。

#### 检查并激活环境

已有 Python 和 Node.js 时，先用 `python3 --version`、`node --version` 检查版本，再安装 pnpm：

```bash
npm install --global pnpm@10.17.1
pnpm --version
```

如果还没有 Python 环境，确认 `python3` 为 3.12+ 后创建一个：

```bash
python3 -m venv ms-agent-env
source ms-agent-env/bin/activate
```

已有虚拟环境或 Conda 环境的用户直接激活即可；如果已按上面的流程创建并激活环境，无需重复操作。Windows PowerShell 使用 `python -m venv ms-agent-env` 和 `.\ms-agent-env\Scripts\Activate.ps1`。后续命令都在已激活的环境中运行。

安装 uv，并确认当前终端能找到它：

```bash
pip install uv
uv --version
```

### 2. 克隆源码、安装并启动

```bash
git clone https://github.com/modelscope/ms-agent.git
cd ms-agent
pip install -e .
ms-agent ui
```

可编辑安装让 `ms-agent` 命令使用这个仓库中的 SDK。首次启动会通过 uv 在 `webui/backend/.venv` 中准备后端及其依赖，在 `webui/frontend/` 安装前端依赖并构建页面和样式；无需手动安装 `ms-agent[webui]`。请保持网络连接，并等待终端显示就绪地址。后续启动会检查依赖与构建状态，复用有效的构建结果。

浏览器会自动打开 WebUI，通常是 **http://127.0.0.1:8000**。如果端口被占用，会选择后续可用端口，以终端打印的地址为准。按 **Ctrl-C** 停止服务。

### 3. 开始对话

使用 ModelScope 时，可在[访问令牌页面](https://modelscope.cn/my/myaccesstoken)获取 API Key。

1. 打开 **设置 → 模型设置**，选择 **ModelScope → 编辑**，填写 API Key 并保存。内置服务商已配置接口地址；其他 OpenAI 兼容服务可通过“添加提供方”填写 Base URL 和 Key。
2. 在该服务商下点击 **添加模型**，填写服务实际支持的模型 ID，例如 `Qwen/Qwen3.8-Flash-Next`。如果这个 id 返回 400，请改填该服务商当前可用的对话模型。模型是否可用及调用额度以服务商账号为准。
3. 返回对话页，使用默认项目或新建项目，在输入框下方选择刚添加的模型，发送第一条消息；需要时可附上文件或图片。
4. 按需为项目配置工作目录、技能和 MCP 工具。

### 4. 下次启动

重新打开终端时，先激活上面创建的环境，再启动服务。假设环境和仓库保存在同一目录：

```bash
source ms-agent-env/bin/activate
cd ms-agent
ms-agent ui
```

请先切换到实际存放它们的目录。模型配置和会话会保留，无需重复填写 API Key。如果通过 nvm 安装 Node.js，确认新终端能运行 `node --version`；找不到命令时，先执行 `source "$HOME/.nvm/nvm.sh"`。

## 从历史回复分支

在已完成回复下方，点击复制按钮旁的 **分支**，即可保留截至该回复的历史，进入新会话继续聊。新会话依次命名为 `原标题 (2)`、`原标题 (3)`，会继承历史工具结果和已经保存的摘要。历史末尾的分隔线可以点击，返回原会话。

原会话仍在运行时，也可以从前面已完成的回复分支；中断或未完成的回合不可选。新会话沿用原会话当前选择的模型，输入框留空，打开它不会修改全局默认模型。返回原会话时，同一浏览器标签页会保留尚未发送的草稿；刷新页面后草稿不会保留。

各会话的聊天记录独立，项目文件、配置和记忆仍然共享当前状态。分支不会复制或回退工作目录。

<a id="模型能力与上下文"></a>

## 模型与上下文

### 目录更新

WebUI 使用 SDK 随包提供的 models.dev 快照查询模型能力、上下文长度和价格。目录中没有的模型仍可手动添加，实际访问权限取决于供应商账号和端点。

| 安装方式 | 默认更新行为 |
| --- | --- |
| 源码安装，包括 `pip install -e .` | WebUI 启动时检查；成功后 24 小时内不重复检查，失败后 15 分钟重试 |
| wheel 或镜像 | 使用随包数据或较新的兼容本地缓存 |
| 两种方式均支持 | 在 **设置 → 模型 → 更新目录** 下载数据，重启服务后生效 |

更新请求的超时时间为 8 秒。下载存入 `$MS_AGENT_HOME/cache/models.dev/v1`；更新失败时继续使用当前有效的本地数据。设置页显示正在使用的目录和等待重启的版本。重启时，SDK 从随包快照和兼容缓存中选择较新的数据。

通过 `MS_AGENT_MODEL_CATALOG` 设置更新策略：

| 值 | 行为 |
| --- | --- |
| `auto`（默认） | 按上表中对应安装方式处理 |
| `local` | 跳过启动检查，保留手动更新 |
| `bundled` | 只使用随包快照，关闭更新 |

`ms-agent ui --skip-install` 也会跳过自动检查。pip 安装、元数据查询和包构建本身不下载目录。TUI 暂未提供更新控件。

### 思考与图片

在模型设置或对话输入框的模型名称旁选择思考档位。每段对话会记住各模型的选择；修改时同时更新新会话的默认值，切回已有对话则恢复其保存的档位。列表只显示模型支持的选项。高级 JSON 中的原生思考参数优先，此时快捷选择禁用。

图片理解提供 **自动 / 开启 / 关闭** 三种设置。自动按目录判断，未知模型默认关闭。原有开启或关闭设置会保留，选择自动可恢复识别。关闭图片理解时，WebUI 会提示并只传文件路径。自定义部署确认支持图片后，可手动开启。目录中的音频、视频和 PDF 标签描述模型能力，本界面尚未支持这些格式的原生上传。

### 上下文占用与压缩

输入框右侧、附件按钮左边的圆环显示最近一次请求组装后的输入估算。点开可查看系统提示、工具定义和消息占用，也可点击 **压缩上下文**。输出预留单独显示。更换模型或配置后，旧估算清除，等待下一次请求更新。

模型设置中的上下文限制可缩小已知模型的窗口，或为未知模型指定上限；清空可恢复默认值。自动压缩通常在有效窗口的 85% 触发，输入上限和输出预留可能使它提前。

手动压缩、自动压缩和 SDK `/compact` 使用同一个操作，WebUI 尚未接入 slash command 路由。压缩不追加用户消息；离开页面后继续运行，点击停止可取消。完成后，历史中显示触发来源和压缩前后的 token 估算，原始消息仍保留在会话日志中。

摘要失败时保留原上下文。如果原上下文已经超过可发送范围，可点击 **重试压缩并继续** 续接保存的请求，不重复追加消息。最新输入本身过大时，需要缩短内容或选择更大窗口的模型。

### 记忆与用量记录

开启项目记忆后，压缩前可先提取长期事实。普通记忆提取失败时保留旧记忆和重试来源，合格摘要仍可提交。系统指令会在下一次请求前重新加载。摘要使用单独的低开销思考设置，可能遗漏细节，重要证据应保存在项目文件中。

SDK 独立记录每次响应的用量，压缩失败不会丢弃已经收到的数据。费用估算标记为完整、部分或未知，金额目前不在 WebUI 展示。存储、恢复和定价细节见 [模型目录与上下文压缩](../docs/zh/Components/model-catalog.md)。

## 编辑项目文件

打开项目的工作区，可以新建文件或文件夹、直接重命名，并编辑文本文件。切换文件时，尚未保存的编辑会暂存在当前页面；按 **Cmd/Ctrl+S** 保存当前文件，或在关闭工作区编辑器时选择 **全部保存并关闭**。离开页面或刷新浏览器前请先保存，这些草稿不会自动持久化。

其他编辑器或智能体修改文件后，工作区会在重新检查当前文件时发现变化。如果你也有未保存的编辑，请先查看提示，再选择从磁盘重新加载或用当前版本覆盖。重新加载会放弃当前草稿。

## 常用启动方式

```bash
# 指定访问端口
ms-agent ui --port 8080

# 只启动服务，不自动打开浏览器
ms-agent ui --no-browser

# 允许通过本机的其他网络地址访问
ms-agent ui --host 0.0.0.0 --port 8000
```

本地使用默认关闭认证。通过网络开放服务前，请启用下方的内置登录，或通过已认证且无法绕过的网关提供访问。

| 参数 | 说明 |
| --- | --- |
| `--host HOST` | 监听地址，默认 `127.0.0.1` |
| `--port PORT` | 指定浏览器访问的端口；省略时从 8000 开始选择 |
| `--backend-port PORT` | 指定内部 API 端口，通常无需设置 |
| `--no-browser` | 不自动打开浏览器 |
| `--skip-install` | 跳过依赖安装，仍校验页面和样式；源码构建过期时仍会重新构建 |
| `--prepare-only` | 准备依赖后退出，不启动服务 |
| `--startup-timeout SECONDS` | 启动等待时间，默认 120 秒 |
| `--production` | 兼容参数，默认已使用构建后的前端 |
| `--reload` | 暂不支持，热更新请使用下方开发命令 |

手动指定的端口必须空闲，且前端与内部 API 端口不能相同。任一服务异常退出时，启动器会停止另一服务并报告错误。

## 可选登录认证

MS-Agent 是面向本地使用的 Agent 框架。WebUI 默认监听 `127.0.0.1`，打开后直接进入对话。需要登录保护时，在启动前设置以下环境变量，也可以写入 `webui/backend/.env`：

```dotenv
MS_AGENT_WEBUI_AUTH_ENABLED=true
MS_AGENT_WEBUI_USERNAME=admin
MS_AGENT_WEBUI_PASSWORD=请替换为足够长且不重复使用的密码
```

重新启动 `ms-agent ui` 后，使用配置的用户名和密码登录。每个实例只有一个账号，无需注册。用户名默认为 `admin`；开启认证却未设置密码时，服务会拒绝启动。登录状态保留 7 天，重启服务后仍然有效。使用共享浏览器时，可在**设置 → 退出登录**中退出。修改用户名或密码并重启后，原有登录状态失效；忘记密码时也可通过这种方式重设。

开启后，页面和后端 API 都需要登录，包括文件、配置和流式对话接口。登录 Cookie 使用 HttpOnly、SameSite=Lax，HTTPS 登录时同时使用 Secure。浏览器写入请求只接受同源或 `MS_AGENT_CORS_ORIGINS` 明确列出的来源，开启认证时不允许通配来源。远程访问请使用 HTTPS。

设置 `MS_AGENT_WEBUI_AUTH_ENABLED=false`（默认值）即可直接进入对话。关闭登录本身不限制 API 访问；关闭认证并监听非回环地址时，启动器会输出提醒。`MS_AGENT_FRONTEND_HOSTED_MODE` 只调整界面控件，不提供访问控制。

## 配置与数据

模型、工具和记忆通常可以直接在界面的设置中配置。也可通过环境变量提供配置，例如 `OPENAI_API_KEY`、`OPENAI_BASE_URL`，以及首次启动时的 `MS_AGENT_LLM_PROVIDER`、`MS_AGENT_LLM_MODEL` 默认值。

项目配置、会话和托管技能默认保存在 `~/.ms_agent`；可以通过 `MS_AGENT_HOME` 指定其他目录。项目工作目录中的文件保存在原位置。源码安装的后端环境位于 `webui/backend/.venv`，前端依赖和构建结果位于 `webui/frontend/`，与项目数据分开。

按本指南从可编辑源码运行时，WebUI 读取已保存的 SDK 设置，并依次加载仓库根目录、`webui/`、`webui/backend/` 下的 `.env`，后者优先，已设置的进程环境变量优先级最高。可参考 [配置示例](backend/.env.example)。

本地向量记忆需要额外安装 `fastembed`，首次使用时会下载嵌入模型。在 `webui/backend/` 执行 `uv sync --locked --extra local-embed` 将其安装到后端环境。其他模型和搜索服务按各自配置使用，不必为普通对话安装本地嵌入模型。

## 从源码运行与开发

完成上方快速开始后，即可在同一份源码中开发。修改源码后，重新运行 `ms-agent ui` 会检查并更新过期的前端构建。

需要热更新时，在仓库根目录打开两个终端：

```bash
# 终端 1：后端
cd webui/backend
uv sync --locked
uv run dev
```

```bash
# 终端 2：前端
cd webui/frontend
pnpm install --frozen-lockfile
pnpm dev
```

访问 **http://localhost:5173**。前端开发服务器默认连接本机 8000 端口的后端。

运行后端测试前需先安装前端依赖，启动测试会使用其中的 `tsx` 执行构建清单脚本。运行检查：在 `webui/backend/` 执行 `uv run pytest`；在 `webui/frontend/` 执行 `pnpm typecheck` 和 `pnpm build`。完整构建会同时生成 CSS、页面和服务端文件，请使用 `pnpm build`，不要只运行其中一个子步骤。

Windows 使用相同的安装和启动命令。源码运行时也可使用 PowerShell 脚本：

```powershell
.\webui\scripts\start-webui.ps1 --no-browser
```

开发约定见 [AGENTS.md](AGENTS.md)，构建安装包的命令见 [构建工具说明](../.dev_scripts/webui/README.md)。

## Docker 运行

使用 Docker 时无需在宿主机安装 Python、Node.js 或 pnpm。将下面的 `TAG` 替换为要使用的已发布镜像标签：

```bash
docker run --rm -p 127.0.0.1:9000:8000 \
  -e MS_AGENT_HOME=/data -v ms-agent-data:/data \
  modelscope-registry.us-west-1.cr.aliyuncs.com/modelscope-repo/ms-agent:TAG
```

打开 **http://127.0.0.1:9000**。`ms-agent-data` 保存应用数据，替换容器时保留该数据卷；需要操作宿主机的项目文件时，另行挂载对应目录。更改访问端口只需调整 `9000:8000` 左侧的值。

设置 `MS_AGENT_FRONTEND_HOSTED_MODE=1` 可隐藏不适合远程用户操作的本地路径控件；访问控制仍需单独配置。

### Agent 的 Python 环境

服务运行在 `/opt/venv` 中；Agent 的 shell 默认使用容器内 `/usr/local/bin` 下的 Python 和 pip，预装 `requests`、`PyYAML`、`beautifulsoup4`。Git、Node.js、npm/npx、pnpm 和 uv/uvx 也可以直接使用。普通 `pip install` 不会改变服务环境里的依赖。

项目已有虚拟环境时优先复用；需要不同版本的依赖时，可以为项目新建环境。每次工具调用都会启动一个新的 shell，因此应直接使用虚拟环境中的命令路径，或在同一次调用中激活环境并执行命令。使用 uv 安装到容器系统 Python 时，运行 `uv pip install --system 包名`；安装到项目虚拟环境时不加 `--system`。

`MS_AGENT_SHELL_PATH` 指定 shell 默认使用的工具路径，不改变服务的 PATH；显式的 `tools.code_executor.shell_env` 配置优先。本地安装 SDK 时，如果未设置该变量，就沿用原有 PATH。运行中安装到容器系统 Python 的包不会在替换容器后保留，长期需要的依赖应加入派生镜像。

### Python 软件源

镜像中的 `pip`、`uv` 和 `uvx` 在运行时默认使用清华 PyPI 镜像源。

需要使用其他镜像源或公司内部源时，在宿主机创建两个配置文件。例如，切换到官方 PyPI 源，将以下内容保存为 `pip.conf`：

```ini
[global]
index-url = https://pypi.org/simple
```

将以下内容保存为 `uv.toml`：

```toml
[[index]]
url = "https://pypi.org/simple"
default = true
```

在上方 `docker run` 命令的镜像名称之前加入：

```bash
--mount type=bind,src="$PWD/pip.conf",dst=/etc/pip.conf,readonly \
--mount type=bind,src="$PWD/uv.toml",dst=/etc/uv/uv.toml,readonly \
```

建议通过挂载文件设置容器内的默认源，因为 Agent 的执行工具不会继承所有通过 `-e` 传入的环境变量。软件源用于获取 PyPI 包，Git 仓库和模型下载仍使用各自的地址。

## 常见问题

| 现象 | 处理方式 |
| --- | --- |
| 找不到 `ms-agent`、`uv`、`node` 或 `pnpm` | 确认工具已安装，Python 环境已激活，且当前终端可以访问相应命令；安装后可重新打开终端 |
| `python` / `pip` 不存在，或出现 `externally-managed-environment` | 先按环境准备章节创建并激活虚拟环境；不要向系统 Python 安装。激活后检查 `python --version` 与 `pip --version` |
| `npm install --global` 提示 `EACCES` | 使用上面的 nvm 安装方式，将 Node.js 和 pnpm 安装到用户目录 |
| Python 或 Node 版本不满足要求 | 使用上方列出的版本，确认终端中实际使用的解释器 |
| 指定端口被占用 | 更换 `--port`，或省略它让启动器自动选择 |
| 页面或样式缺失 | 重新运行 `ms-agent ui`，让启动器校验并构建前端；若构建失败，按终端错误检查 Node.js、pnpm 和网络 |
| 默认项目记录丢失 | 在 WebUI 恢复页面选择“暂不恢复”，或点击“恢复默认项目”并确认。系统先备份默认项目目录，再重建记录；已有会话和全局配置保留，项目设置恢复为默认值 |
| 模型连接或认证失败 | 检查模型设置中的 API Key、接口地址、模型名称及网络连接 |
| 缺少 WebUI 的 Python 依赖 | 确认 uv 可用，重新运行 `ms-agent ui` 且不加 `--skip-install`，让启动器同步后端环境 |
