# 快速开始

本页介绍 MS-Agent 1.7.0 的 PyPI 安装与首次使用，选择 WebUI 或终端路径即可。Python 应用开发者可先完成终端安装，再阅读 [Python SDK](python-sdk.md)。

## 选择入口与环境

| 入口 | 环境 | 适合 |
| --- | --- | --- |
| WebUI | Python 3.12+、Node 22.22.0+、pnpm 10.17.1 | 在浏览器中对话并处理项目文件 |
| TUI / CLI / SDK | Python 3.10+ | 终端交互、运行任务、嵌入应用 |

模型通过 API 调用时，基础对话不需要本地 GPU。可选研究、向量检索和视频功能有各自依赖。以下命令使用 macOS/Linux shell；Windows 的环境激活方式见下方说明，平台支持和实际依赖应分别核验。

(environment)=
## 准备 Python 环境

确认 `python3 --version` 满足所选入口要求；首次体验推荐使用 Python 3.12。在准备存放虚拟环境的目录执行：

```bash
python3 -m venv ms-agent-env
source ms-agent-env/bin/activate
python --version
python -m pip --version
```

已有虚拟环境或 Conda 环境可直接激活，不必重复创建。Windows PowerShell 使用 `python -m venv ms-agent-env` 和 `.\ms-agent-env\Scripts\Activate.ps1`。后续安装都在已激活的环境中进行。

````{dropdown} 还没有合适的 Python 或 Node.js？
使用 uv 准备 Python（已有正确环境可跳过）：
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
uv venv --python 3.12 --seed ms-agent-env
source ms-agent-env/bin/activate
```

WebUI 还需要 Node.js；可通过 nvm 安装到用户目录：
```bash
curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
export NVM_DIR="$HOME/.nvm"
source "$NVM_DIR/nvm.sh"
nvm install 22.22.0
node --version
```
执行网络安装脚本前阅读其来源和内容；这些命令会修改本机工具环境。不要在系统 Python 中直接安装项目依赖。
````

(webui)=
## 路径一：WebUI

### 1. 安装并启动

```bash
npm install --global pnpm@10.17.1
python -m pip install -U "ms-agent[webui]"
ms-agent ui
```

WebUI 使用当前 Python 环境运行后端，安装包已包含构建好的前端。首次启动会通过 pnpm 下载 Node 依赖并存入本地缓存，请保持网络连接。准备完成后，使用终端显示的地址访问；启动器默认从 `http://127.0.0.1:8000` 开始选择空闲端口。

基础包 `ms-agent` 不含 WebUI 后端依赖，因此这里需要安装 `[webui]` 扩展。上面的 PyPI 安装流程无需 Git 或 uv；它们用于后文的[源码安装](#从源码安装)。

### 2. 配置模型

1. 打开 **设置 → 模型设置**，选择服务商，点击 **编辑** 填写 API Key 并保存。ModelScope 的 Key 可在[访问令牌页面](https://modelscope.cn/my/myaccesstoken)获取。若服务商未列出，先按[模型设置指南](../user-guide/model-settings.md)添加。
2. 点击 **添加模型**，填写该服务支持的模型 ID，例如 ModelScope 的 `Qwen/Qwen3.8-Flash-Next`。
3. 回到对话页，在输入框下方选中模型。首次使用时，权限模式保持为 **总是询问**。

保存 Key 不会自动添加或选中模型。不要在聊天内容或截图中暴露 API Key。

### 3. 完成首次任务

先发送“用两句话介绍你能怎样帮助我”。收到正常回复后，在一个只含测试文件的项目中请求：“读取 README，列出三个要点；不要修改文件。”

确认模型可回复、工具调用及结果可见、任务结束后能继续追问。若有授权提示，先检查操作和路径，再决定是否允许。页面能打开不代表模型凭据或工具都已可用。

更多操作见 [WebUI 教程](../user-guide/webui.md)。

(terminal)=
## 路径二：终端

在已激活的 Python 环境中安装基础包，并设置 ModelScope API Key：

```bash
python -m pip install -U ms-agent
export MODELSCOPE_API_KEY='<your-api-key>'
```

如果已经安装 WebUI，同一环境中也已包含终端界面和 SDK，只需配置 Key。终端使用的 Key 也可保存在本地 `.env` 中，请勿提交该文件。WebUI 中保存的模型选择不一定是 CLI 的默认配置。

持续交互使用 TUI：

```bash
ms-agent tui
```

输入 `/help` 查看命令，发送一个只读任务，以 `/quit` 退出。配置与恢复操作见 [TUI 教程](../user-guide/tui.md)。运行一次任务可使用：

```bash
ms-agent run --query '用两句话解释什么是智能体。'
```

首次运行默认智能体时可能需要下载额外依赖，请等待准备完成。需要指定模型、工具或输出目录时，可使用 YAML 配置，见 [CLI 教程](../user-guide/cli.md)。

(restart)=
## 停止与下次启动

WebUI 在启动终端按 `Ctrl-C` 停止。新开终端后，切到实际存放环境的目录：

```bash
source ms-agent-env/bin/activate
ms-agent ui
```

使用 TUI 时运行 `ms-agent tui`，并重新设置终端所需的 API Key 环境变量。若通过 nvm 安装 Node，先确认 `node --version` 可用，必要时执行 `source "$HOME/.nvm/nvm.sh"`。WebUI 中保存的模型、项目和会话会保留；重启服务不会自动继续中断的工具操作。

## 升级已有安装

停止服务，激活原来的 Python 环境，再次执行 `python -m pip install -U "ms-agent[webui]"`。仅使用终端或 SDK 时，执行 `python -m pip install -U ms-agent`。这两条命令也可将 1.7.0 候选版升级到正式版。升级时保留应用数据和凭据主密钥，详见[密钥保存与恢复](../user-guide/credentials.md)。

(extras)=
## 按需增加依赖

在同一 Python 环境中按需安装扩展；保留命令中的引号，避免 zsh 将方括号作为文件匹配表达式：

| 能力 | 命令 |
| --- | --- |
| 向量/混合技能检索 | `python -m pip install -U "ms-agent[retrieval]"` |
| 深度研究与文档解析 | `python -m pip install -U "ms-agent[research]"` |
| 代码项目及相关集成 | `python -m pip install -U "ms-agent[code]"` |
| 视频生成 | `python -m pip install -U "ms-agent[cinema]"` |
| ACP / A2A | `python -m pip install -U "ms-agent[acp]"` / `python -m pip install -U "ms-agent[a2a]"` |
| 全部功能，Python 3.12+ | `python -m pip install -U "ms-agent[all]"` |

基础包不包含 torch/CUDA，部分扩展会引入较大的依赖。Linux 若只需 CPU 版 torch，可先执行 `python -m pip install torch --index-url https://download.pytorch.org/whl/cpu`，再安装所需扩展。具体应用还可能需要额外的账户、工具或模型部署。

<a id="source-install"></a>

## 从源码安装

参与开发或体验尚未发布的功能时，可在独立的 Python 环境中安装源码。此方式还需要 Git：

```bash
git clone https://github.com/modelscope/ms-agent.git
cd ms-agent
python -m pip install -e .
```

使用 WebUI 时，还需准备上表中的 Node.js 和 pnpm，并执行 `python -m pip install "uv>=0.5"` 安装 uv。随后在仓库目录运行 `ms-agent ui`：首次启动会在 `webui/backend/.venv` 中准备独立的后端环境，安装前端依赖并构建前端。可编辑源码安装无需另装 `[webui]` 扩展。热更新等开发方式见 [WebUI 开发说明](https://github.com/modelscope/ms-agent/blob/release/1.7/webui/README_ZH.md#从源码运行与开发)。

为可编辑安装增加扩展时，在仓库目录使用 `python -m pip install -e '.[research]'` 等命令，避免用 PyPI 包替换正在开发的源码版本。

Docker 与远程访问见[部署与数据管理](../user-guide/deployment.md)；遇到启动、模型或文件问题，按[故障排查](../user-guide/troubleshooting.md)逐层检查。
