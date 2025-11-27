# MS-Agent 演示手册

本手册基于 MS-Agent 官方文档（最后更新：2025-01-25），提供最准确的演示流程和配置指南。

## 1. 快速开始 (Quick Start)

### 安装

MS-Agent 支持多种安装方式：

**PyPI 安装（推荐）**：

```bash
# 基础安装
pip install ms-agent

# 带研究功能（Doc Research / Deep Research）
pip install 'ms-agent[research]'

# 带代码生成功能（Code Scratch）
pip install 'ms-agent[code]'
```

**源码安装（开发者）**：

```bash
git clone https://github.com/modelscope/ms-agent.git
cd ms-agent
pip install -e .
```

### 通用对话 Demo

体验基础的 Agent 对话能力。

**命令行启动**：

```bash
# 使用 ModelScope API Key
ms-agent run --config ms-agent/simple_agent --modelscope_api_key <YOUR_KEY>
```

**Python 脚本启动**：

```python
import asyncio
import sys

from ms_agent import LLMAgent
from ms_agent.config import Config

async def run_query(query: str):
    config = Config.from_task('ms-agent/simple_agent')
    # 配置 ModelScope API Key: https://modelscope.cn/my/myaccesstoken
    config.llm.modelscope_api_key = 'xxx'
    engine = LLMAgent(config=config)

    _content = ''
    generator = await engine.run(query, stream=True)
    async for _response_message in generator:
        new_content = _response_message[-1].content[len(_content):]
        sys.stdout.write(new_content)
        sys.stdout.flush()
        _content = _response_message[-1].content
    sys.stdout.write('\n')
    return _content

if __name__ == '__main__':
    query = 'Introduce yourself'
    asyncio.run(run_query(query))
```

---

## 2. Doc Research (文档深度研究)

**定位**: 您的日常论文副驾驶。输入 URL 或文件，输出多模态研报。

### 核心特性

- **多模态**: 生成包含图表的 Markdown 报告。
- **交互式**: 基于 Gradio 的 Web UI。
- **导出/分享**: 支持导出 PDF/PPTX/Word，一键上传 ModelScope/GitHub。

### 演示准备

1.  **安装依赖**: `pip install 'ms-agent[research]'`
2.  **配置环境变量**:
    ```bash
    export OPENAI_API_KEY="sk-..."
    export OPENAI_BASE_URL="https://api.openai.com/v1" # 或 ModelScope/DeepSeek
    export OPENAI_MODEL_ID="Qwen/Qwen3-235B-A22B-Instruct-2507" # 推荐模型
    ```

### 演示流程

1.  **启动应用**:
    ```bash
    ms-agent app --app_type doc_research
    ```
    - 默认监听 7860 端口；若看到 `Cannot find empty port`，说明 7860 被占用，可临时换端口：
      ```bash
      ms-agent app --app_type doc_research --server_port 7861
      ```
      或事先设置环境变量 `export GRADIO_SERVER_PORT=7861` 再启动。
    - 启动成功后，终端会输出 `Running on ...:PORT`，浏览器直接打开该地址即可。
2.  **浏览器访问**: `http://127.0.0.1:7860`
3.  **操作**:
    - 输入 Prompt: "总结这篇论文的核心创新点"
    - 上传 PDF 文件或输入 arXiv 链接。
    - 点击 "开始研究"。
4.  **展示**:
    - 实时生成的图文报告。
    - 全屏阅读模式。

---

## 3. Deep Research（深度研究）

**定位**：面向科研领域的深度调研 Agent。支持 "Search-then-Execute" 模式。

### 版本说明

- **基础版本**：自动探索、轻量高效（几分钟完成），支持 Ray 加速文档解析
- **扩展版本 (Beta)**：意图澄清、递归搜索、长上下文压缩、可配置深度和广度

### 演示准备

1.  **安装依赖**：

    ```bash
    # 从源码安装
    git clone https://github.com/modelscope/ms-agent.git
    cd ms-agent
    pip install -r requirements/research.txt
    pip install -e .

    # 或从 PyPI 安装 (>=v1.1.0)
    pip install 'ms-agent[research]'
    ```

2.  **配置搜索引擎**：

    默认使用免费的 arXiv search（无需 API Key）。如需通用搜索引擎：

    **配置 `.env` 文件**：

    ```bash
    cp .env.example .env

    # 使用 Exa 搜索（注册：https://exa.ai，有免费额度）
    EXA_API_KEY=your_exa_api_key

    # 使用 SerpApi 搜索（注册：https://serpapi.com，有免费额度）
    SERPAPI_API_KEY=your_serpapi_api_key

    # 扩展版本需配置 OpenAI 兼容端点（用于查询改写）
    OPENAI_API_KEY=your_api_key
    OPENAI_BASE_URL=https://your-openai-compatible-endpoint/v1
    ```

    **配置 `conf.yaml`**：

    ```yaml
    SEARCH_ENGINE:
      engine: exa
      exa_api_key: $EXA_API_KEY
    ```

### 演示流程 (Python)

进入 `projects/deep_research` 目录。

**基础版本代码示例**：

```python
from ms_agent.llm.openai import OpenAIChat
from ms_agent.tools.search_engine import get_web_search_tool
from ms_agent.workflow.deep_research.principle import MECEPrinciple
from ms_agent.workflow.deep_research.research_workflow import ResearchWorkflow

query = 'Survey of the AI Agent within the recent 3 month'
task_workdir = '/path/to/your_task_dir'

# 使用 ModelScope API（免费）
chat_client = OpenAIChat(
    api_key='xxx-xxx',
    base_url='https://api-inference.modelscope.cn/v1/',
    model='Qwen/Qwen3-235B-A22B-Instruct-2507',
)

search_engine = get_web_search_tool(config_file='conf.yaml')

research_workflow = ResearchWorkflow(
    client=chat_client,
    principle=MECEPrinciple(),
    search_engine=search_engine,
    workdir=task_workdir,
    reuse=False,
    use_ray=False,  # 启用 Ray 加速文档解析
)

research_workflow.run(user_prompt=query)
```

**扩展版本代码示例**：

```python
import asyncio
from ms_agent.llm.openai import OpenAIChat
from ms_agent.tools.search_engine import get_web_search_tool
from ms_agent.workflow.deep_research.research_workflow_beta import ResearchWorkflowBeta

query = 'Survey of the AI Agent within the recent 3 month'
task_workdir = '/path/to/your_workdir'

chat_client = OpenAIChat(
    api_key='xxx-xxx',
    base_url='https://api-inference.modelscope.cn/v1/',
    model='Qwen/Qwen3-235B-A22B-Instruct-2507',
    generation_config={'extra_body': {'enable_thinking': False}}
)

search_engine = get_web_search_tool(config_file='conf.yaml')

research_workflow = ResearchWorkflowBeta(
    client=chat_client,
    search_engine=search_engine,
    workdir=task_workdir,
    use_ray=False,
    enable_multimodal=True
)

asyncio.run(
    research_workflow.run(
        user_prompt=query,
        breadth=4,  # 每层搜索查询数量
        depth=2,    # 最大研究深度
        is_report=True,
        show_progress=True
    )
)
```

**展示重点**：

- 基础版本：快速生成多模态研究报告（几分钟）
- 扩展版本：展示"意图澄清" -> "查询改写" -> "搜索与解析" -> "上下文压缩" -> "递归搜索" -> "报告生成"的完整流程

---

## 4. Code Scratch（代码生成）

**定位**：从需求生成可运行的软件项目代码（主要支持 React 前端和 Node.js 后端）。

### 核心流程

1.  **Architecture（架构设计）**：根据需求生成 PRD、模块设计和文件结构
2.  **Coding（编码）**：多 Worker 并行编码，按模块分组生成代码
3.  **Refine（精炼）**：自动编译检查与错误修复，支持人工反馈优化

### 演示准备

1.  **安装 Python 环境**：

    ```bash
    conda create -n code_scratch python==3.11
    conda activate code_scratch
    pip install -e .
    ```

2.  **安装 Node.js 环境**（必需，否则会导致编译失败和无限循环）：

    **Mac (推荐 Homebrew)**：

    ```bash
    brew install node
    ```

    **Linux/其他平台**：参考 https://nodejs.org/en/download

    **验证安装**：

    ```bash
    npm --version  # 确保有输出版本号
    node --version
    ```

3.  **配置 LLM API**（Code Scratch 配置文件使用 DashScope 作为后端）：

    在 `projects/code_scratch/architecture.yaml`、`coding.yaml`、`refine.yaml` 中已配置：

    ```yaml
    llm:
      service: openai
      model: claude-sonnet-4-5-20250929
      openai_api_key: # 留空时从环境变量读取
      openai_base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
    ```

    配置环境变量：

    ```bash
    export OPENAI_API_KEY="sk-xxx"  # 你的 DashScope API Key
    export OPENAI_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
    ```

    或使用其他 OpenAI 兼容端点（修改 yaml 中的 `openai_base_url`）。

### 演示流程

**命令行一键生成**：

```bash
# 务必在项目根目录（ms-agent）执行
cd /path/to/ms-agent

# 使用 PYTHONPATH 确保导入正确
PYTHONPATH=. ms-agent run \
    --config projects/code_scratch \
    --query 'make a demo website' \
    --trust_remote_code true

# 或直接使用 Python
PYTHONPATH=. python ms_agent/cli/cli.py run \
    --config projects/code_scratch \
    --query '写一个贪吃蛇游戏，使用 HTML5 Canvas' \
    --trust_remote_code true
```

**生成的代码位置**：`output/` 目录（默认）

**观察重点**：

- 终端输出的阶段变化（Architecture -> Coding -> Refine）
- Architecture 阶段生成的 `files.json` 文件列表
- Coding 阶段多 Worker 并行编码过程
- Refine 阶段自动 `npm install` 和 `npm run build/dev` 的编译输出
- 遇到错误时 Refiner 如何分析和分配修复任务

**人工反馈（可选）**：

所有编码和编译完成后，系统会等待人工输入：

1. 运行前后端：`npm run dev`
2. 检查浏览器控制台和后端日志中的错误
3. 输入错误反馈或新增功能需求
4. 系统继续优化代码

### 常见问题排查

**问题 1：npm 相关错误或无限循环**

- **原因**：未安装 Node.js 或 npm 不在 PATH 中
- **解决**：确保 `npm --version` 能正常输出，参考上述"安装 Node.js 环境"步骤

**问题 2：API Key 错误**

- **原因**：未配置 `OPENAI_API_KEY` 或 Key 无效
- **解决**：检查环境变量或 yaml 文件中的 `openai_api_key` 配置

**问题 3：生成代码质量不佳**

- **原因**：模型选择或 temperature 参数不合适
- **解决**：修改各阶段 yaml 中的 `generation_config.temperature`（architecture: 0.3, coding: 0.2, refine: 0.2）

---

## 5. 常见问题 (FAQ)

### 安装与环境

**Q: 缺少依赖模块？**

- A: 请确保安装了对应的 extras：
  - 研究功能：`pip install 'ms-agent[research]'`
  - 代码生成：`pip install 'ms-agent[code]'`
  - 完整安装：`pip install 'ms-agent[research,code]'`

**Q: 如何验证安装是否成功？**

- A: 运行以下命令测试：
  ```bash
  ms-agent --help
  python -c "import ms_agent; print(ms_agent.__version__)"
  ```

### Doc Research

**Q: Doc Research 无法启动？**

- A:
  1. 检查端口 7860 是否被占用，使用 `--server_port` 指定新端口
  2. 如无法访问页面，尝试关闭代理（proxy）
  3. 确认已配置正确的环境变量 `OPENAI_API_KEY` 和 `OPENAI_BASE_URL`

**Q: 上传文件失败？**

- A:
  1. 确保文件格式支持（PDF、TXT、PPT、DOCX）
  2. 检查文件大小限制
  3. 确认 `temp_workspace` 目录有写权限

### Deep Research

**Q: Deep Research 搜索失败？**

- A:
  1. 检查 `.env` 中的搜索引擎 API Key 是否有效（Exa/SerpApi）
  2. 验证 `conf.yaml` 配置是否正确
  3. 如使用 arXiv search，确认网络能访问 arXiv.org

**Q: 扩展版本报错找不到模型？**

- A: 扩展版本需要配置 `OPENAI_API_KEY` 和 `OPENAI_BASE_URL`，用于查询改写阶段

### Code Scratch

**Q: Code Scratch 出现无限循环？**

- A:
  1. **最常见原因**：未安装 Node.js 或 npm 不在 PATH 中
  2. 运行 `npm --version` 验证安装
  3. 参考官方文档安装 Node.js：https://nodejs.org/

**Q: 生成的代码有语法错误？**

- A:
  1. 检查模型配置，推荐使用 `claude-sonnet-4-5` 或 `Qwen3-235B`
  2. 调整 `generation_config.temperature`（architecture: 0.3, coding: 0.2, refine: 0.2）
  3. 确保 `trust_remote_code` 参数设为 `true`

**Q: API Key 错误？**

- A:
  1. 检查环境变量 `OPENAI_API_KEY` 是否正确设置
  2. 确认 `OPENAI_BASE_URL` 与 API Key 匹配
  3. Code Scratch 默认配置使用 DashScope，需要对应的 API Key

### ModelScope API

**Q: 如何获取 ModelScope API Key？**

- A: 访问 https://modelscope.cn/my/myaccesstoken 获取免费 API Key

**Q: ModelScope API 免费额度是多少？**

- A: 每个注册用户每天有一定数量的免费调用额度，详情见：https://modelscope.cn/docs/model-service/API-Inference/intro

**Q: 如何使用其他 LLM 提供商？**

- A: 修改配置文件中的 `openai_base_url` 和 `openai_api_key`，支持任何 OpenAI 兼容的 API 端点

### 性能优化

**Q: 如何加速 Deep Research？**

- A:
  1. 启用 Ray：设置 `use_ray=True`（需要更多 CPU 资源）
  2. 减少 `breadth` 和 `depth` 参数
  3. 使用更快的模型（如 Qwen3-Flash）

**Q: 如何降低 Token 消耗？**

- A:
  1. Doc Research：使用更精确的用户提示词
  2. Deep Research：调低 `breadth` 和 `depth` 参数
  3. Code Scratch：提供更详细的需求描述，减少修复迭代

---

## 6. 参考资源

- **官方文档**：https://ms-agent.readthedocs.io/zh-cn/latest/
- **GitHub 仓库**：https://github.com/modelscope/ms-agent
- **ModelScope 平台**：https://modelscope.cn/
- **API 文档**：https://modelscope.cn/docs/model-service/API-Inference/intro
- **Code Scratch README**：https://github.com/modelscope/ms-agent/blob/main/projects/code_scratch/README.md
- **Deep Research 文档**：https://ms-agent.readthedocs.io/zh-cn/latest/Projects/%E6%B7%B1%E5%BA%A6%E7%A0%94%E7%A9%B6.html
