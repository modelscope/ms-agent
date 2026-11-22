# 快速开始

本页同时覆盖 WebUI 与终端：选择其中一条路径即可。Python 应用开发者完成终端安装后进入 [Python SDK](python-sdk.md)。

## 选择入口与环境

| 入口 | 环境 | 适合 |
| --- | --- | --- |
| WebUI | Python 3.12+、Node 22.22.0+、pnpm 10.17.1、uv 0.5+、Git | 在浏览器中对话并处理项目文件 |
| TUI / CLI / SDK | Python 3.10+、Git | 终端交互、运行任务、嵌入应用 |

模型通过 API 调用时，基础对话不需要本地 GPU。可选研究、向量检索和视频功能有各自依赖。以下命令使用 macOS/Linux shell；Windows 的环境激活方式见下方说明，平台支持和实际依赖应分别核验。

(environment)=
## 准备 Python 环境

确认 `python3 --version` 满足所选入口要求；首次体验推荐 3.12。在准备存放环境与源码的目录执行：

```bash
python3 -m venv ms-agent-env
source ms-agent-env/bin/activate
python --version
pip --version
```

已有虚拟环境或 Conda 环境可直接激活，不必重复创建。Windows PowerShell 使用 `python -m venv ms-agent-env` 和 `.\ms-agent-env\Scripts\Activate.ps1`。后续安装都在已激活的环境中进行。

````{dropdown} 还没有合适的 Python 或 Node.js？
先运行 `git --version`。macOS 若提示安装 Command Line Tools，完成安装再继续。

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
pip install uv
git clone https://github.com/modelscope/ms-agent.git
cd ms-agent
pip install -e .
ms-agent ui
```

首次启动会准备 `webui/backend/.venv`、安装前端依赖并构建页面。保持网络连接，等待终端显示就绪地址；默认从 `http://127.0.0.1:8000` 选择空闲端口，使用实际打印的地址。

已有该仓库时不要再次克隆覆盖它；进入仓库和正确环境再启动。源码安装无需额外手动安装 `ms-agent[webui]`。

### 2. 配置模型

1. 获取 [ModelScope API Key](https://modelscope.cn/my/myaccesstoken)。
2. 打开 **设置 → 模型设置 → ModelScope → 编辑**，填写 Key 并保存。
3. 点击 **添加模型**，填入服务支持的模型 ID，例如 `Qwen/Qwen3.8-Flash-Next`。
4. 回到对话页，在输入框下选择刚添加的模型。自定义 OpenAI 兼容服务使用“添加提供方”，填写实际 Base URL 和 Key。

保存 Key 不等于已经添加或选中模型。不要将真实 Key 发到聊天或截图中。

### 3. 完成首次任务

先发送“用两句话介绍你能怎样帮助我”。收到正常回复后，在一个只含测试文件的项目中请求：“读取 README，列出三个要点；不要修改文件。”

确认模型可回复、工具调用及结果可见、任务结束后能继续追问。若有授权提示，先检查操作和路径，再决定是否允许。页面能打开不代表模型凭据或工具都已可用。

更多操作见 [WebUI 教程](../user-guide/webui.md)。

(terminal)=
## 路径二：终端

在已激活的 Python 环境中安装源码：

```bash
git clone https://github.com/modelscope/ms-agent.git
cd ms-agent
pip install -e .
export MODELSCOPE_API_KEY='<your-api-key>'
```

如果已走过 WebUI 的源码安装，直接复用，不必重新安装。Key 也可放入本地 `.env`；不要提交该文件。WebUI 内保存的模型选择不应当被假设为所有 CLI 调用的默认配置。

持续交互使用 TUI：

```bash
ms-agent tui
```

输入 `/help` 查看命令，发送一个只读任务，以 `/quit` 退出。配置与恢复操作见 [TUI 教程](../user-guide/tui.md)。运行一次任务可使用：

```bash
ms-agent run --query '用两句话解释什么是智能体。'
```

首次默认 Agent 初始化可能下载额外依赖，等待终端进度。需要固定模型、工具或输出目录时，使用明确的 YAML，见 [CLI 教程](../user-guide/cli.md)。

(restart)=
## 停止与下次启动

WebUI 在启动终端按 `Ctrl-C` 停止。新开终端后，切到实际存放环境的目录：

```bash
source ms-agent-env/bin/activate
cd ms-agent
ms-agent ui
```

TUI 则启动 `ms-agent tui`。若通过 nvm 安装 Node，先确认 `node --version` 可用，必要时执行 `source "$HOME/.nvm/nvm.sh"`。已经保存的 WebUI 模型、项目和会话不必重新建立；重启运行进程不等于自动继续中断中的工具任务。

(extras)=
## 按需增加依赖

在源码根目录、已激活的环境中安装；保留引号以兼容 zsh：

| 能力 | 命令 |
| --- | --- |
| 向量/混合技能检索 | `pip install -e '.[retrieval]'` |
| 深度研究与文档解析 | `pip install -e '.[research]'` |
| 代码项目及相关集成 | `pip install -e '.[code]'` |
| 视频生成 | `pip install -e '.[cinema]'` |
| ACP / A2A | `pip install -e '.[acp]'` / `pip install -e '.[a2a]'` |
| 全部功能，Python 3.12+ | `pip install -e '.[all]'` |

基础包不包含 torch/CUDA；部分 extras 会引入较大依赖。Linux 若只需 CPU torch，可先安装 `pip install torch --index-url https://download.pytorch.org/whl/cpu`，再安装所需 extra。项目仍可能需要额外账户、工具或模型部署，安装通过不等于完整任务已通过。

Docker 与远程访问见[部署与数据管理](../user-guide/deployment.md)；遇到启动、模型或文件问题，按[故障排查](../user-guide/troubleshooting.md)逐层检查。
