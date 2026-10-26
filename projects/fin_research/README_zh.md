# **金融深度研究**

本项目实现了一个面向金融市场研究的多智能体（Multi-Agent）工作流，结合定量金融数据分析与来自互联网的定性舆情分析，自动生成专业的金融研究报告。

## 🌟 功能特性

- **多智能体架构**：通过多个专用智能体的编排实现工作流，从而完成任务拆解、数据收集、量化分析、舆情研究与最终报告生成。

- **多维度分析**：涵盖金融数据指标与公众舆情两个维度，实现结构化与非结构化数据的融合分析，产出覆盖面广、结构清晰的研究报告。

- **金融数据采集**：支持模型自动获取A股、港股、美股等市场的行情、财报、宏观指标与市场数据。

- **舆情深度研究**：新闻/媒体/社区等多源舆情深度分析。

- **专业报告生成**：按业界常用方法论（MECE、SWOT、金字塔原理等）生成多章节、结构化、图文并茂的专业报告。

- **安全代码执行**：在隔离的 Docker 沙箱中执行数据处理与分析，保证环境安全与可复现性。

## 📋 架构

工作流由 5 个专用智能体构成：

```text
                    ┌─────────────┐
                    │ Orchestrator│
                    │   Agent     │
                    └──────┬──────┘
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
      ┌──────────────┐          ┌──────────────┐
      │   Searcher   │          │  Collector   │
      │    Agent     │          │    Agent     │
      └──────┬───────┘          └──────┬───────┘
             │                         │
             │                         ▼
             │                  ┌──────────────┐
             │                  │   Analyst    │
             │                  │    Agent     │
             │                  └──────┬───────┘
             │                         │
             └────────────┬────────────┘
                          ▼
                   ┌──────────────┐
                   │  Aggregator  │
                   │    Agent     │
                   └──────────────┘
```

1. **Orchestrator Agent（编排智能体）**：将用户问题拆解为任务描述与范围、金融数据分析任务、舆情研究任务三部分。

2. **Searcher Agent（搜索智能体）**：非结构化数据搜集，依据编排智能体的舆情研究任务，调用深度研究工作流（`ms-agent/projects/deep_research`）进行舆情深度检索与研究，生成舆情分析报告。

3. **Collector Agent（数据采集智能体）**：金融结构化数据搜集，依据编排智能体的金融数据分析任务，使用基于 `akshare`/`baostock` 实现的数据获取工具采集所需金融数据。

4. **Analyst Agent（数据分析智能体）**：在沙箱中进行数据的量化分析，基于 Collector 获取的数据生成量化分析报告与可视化结果。

5. **Aggregator Agent（报告生成智能体）**：将舆情与量化两类分析结果进行整合、逐章生成报告并进行校验，产出结构完整、逻辑一致的综合研究报告。

## 🛠️ 安装

请按如下步骤完成环境搭建：

### Python 环境

```bash
# 源码下载
git clone https://github.com/modelscope/ms-agent.git
cd ms-agent

# Python 环境
conda create -n fin_research python=3.11
conda activate fin_research
# 从 PyPI 安装（>=v1.5.0）
pip install 'ms-agent[research]'
# 从源码安装
pip install -r requirements/framework.txt
pip install -r requirements/research.txt
pip install -e .

# 数据接口依赖
pip install akshare baostock
```

### 沙箱环境

Collector、Analyst 和 Aggregator 默认在 Docker 沙箱中执行代码，并通过输出目录共享数据和报告。运行前，请先安装沙箱依赖并构建镜像：

```bash
# 安装 ms-enclave（https://github.com/modelscope/ms-enclave）
pip install ms-enclave docker websocket-client

# 构建所需 Docker 镜像（确保系统已安装并运行 Docker）
bash projects/fin_research/tools/build_jupyter_image.sh
```

如需完全使用本地环境，请将 `collector.yaml`、`analyst.yaml` 和 `aggregator.yaml` 中的整个 `tools.code_executor` 配置块替换为：

```yaml
tools:
  code_executor:
    mcp: false
    implementation: python_env
    include:
      - shell_executor
```

同时调整提示词，使其与本地执行方式一致：

- Collector 和 Analyst：通过 `shell_executor` 完成数据分析和文件操作，移除 Notebook 专用工具、内核重置及变量跨调用保留等要求。每次命令独立运行，需在本次调用中准备所需模块和数据。
- Aggregator：将提示词中的沙箱路径 `/data` 改为本地输出目录。Collector 和 Analyst 的 `<DATA_ROOT>` 占位符会根据执行模式自动替换。

本地模式直接使用宿主机资源，不提供沙箱隔离。运行前，请在本地执行环境中安装所需分析依赖。

## 🚀 快速开始

### 环境变量配置

在系统环境或 YAML 中配置 API Key：

```bash
# LLM API（系统环境配置示例）
export OPENAI_API_KEY=your_api_key
export OPENAI_BASE_URL=your-api-url

# 搜索引擎（用于舆情研究，可选 exa 或 serpapi），下列服务均提供一定的免费额度，请注册并配置API Key
# exa账号注册地址为https://exa.ai，SerpApi账号注册地址为https://serpapi.com
# 如果不希望配置搜索引擎就启动FinResearch项目进行测试，可跳过并参考快速启动一节
export EXA_API_KEY=your_exa_api_key
export SERPAPI_API_KEY=your_serpapi_api_key
```

在 `searcher.yaml` 指定搜索引擎配置文件的路径：

```yaml
tools:
  search_engine:
    config_file: projects/fin_research/conf.yaml
```

### 运行工作流

快速启动完整FinResearch工作流进行测试：

```bash
# 在 ms-agent 根目录执行
PYTHONPATH=. python ms_agent/cli/cli.py run \
  --config projects/fin_research \
  --query '请分析宁德时代（300750.SZ）近四个季度盈利能力变化，并与新能源领域主要竞争对手（如比亚迪、国轩高科、中创新航）进行对比；结合产业政策与锂价波动，预测其未来两季度业绩趋势。' \
  --trust_remote_code true
```

在没有配置搜索引擎服务的情况下，允许配置最小版本FinResearch工作流进行测试（无舆情深度研究部分），需要修改workflow.yaml文件如下：

```bash
type: DagWorkflow

orchestrator:
  next:
    - collector
  agent_config: orchestrator.yaml

collector:
  next:
    - analyst
  agent_config: collector.yaml

analyst:
  next:
    - aggregator
  agent_config: analyst.yaml

aggregator:
  agent_config: aggregator.yaml
```

随后在命令行中按之前相同的方式启动即可。需要注意的是，由于信息维度不全面，FinResearch可能无法对复杂问题给出篇幅较长、内容丰富的分析报告，建议仅用于测试。

运行FinResearch应用：

```bash
# 使用命令行的方式启动Gradio服务（可以不带参数启动，只使用--app_type fin_research）
ms-agent app --app_type fin_research --server_name 0.0.0.0 --server_port 7860 --share

# 使用Python脚本的方式启动Gradio服务
cd ms-agent/app
python fin_research.py
```

### 样例

更多内容请参考`projects/fin_research/examples`。

<https://github.com/user-attachments/assets/2ef0f7a1-985b-4dbd-9d75-da16246e985e>

## 🔧 开发指南

### 组件说明

- `workflow.yaml`：工作流配置入口，编排 Orchestrator / Searcher / Collector / Analyst / Aggregator 五个智能体的执行流程，基于DagWorkflow运行。

- `agent.yaml`（`orchestrator.yaml`、`searcher.yaml`、`collector.yaml`、`analyst.yaml`、`aggregator.yaml`）：定义各智能体（或者工作流）的行为、工具、LLM 参数和提示词（角色与职责）。

- `conf.yaml`：搜索引擎配置，包含 Exa / SerpAPI 等搜索工具的 API Key 与参数设置。

- `callbacks/`：各智能体专属的callback模块：
  - `orchestrator_callback.py`：保存任务规划到本地。
  - `collector_callback.py`：从本地加载任务规划并添加至用户消息。
  - `analyst_callback.py`：从本地加载任务规划并保存量化分析报告到本地。
  - `aggregator_callback.py`：保存最终综合分析报告到本地。
  - `file_parser.py`：代码/JSON文本的解析与处理。

- `tools/`：工具目录：
  - `build_jupyter_image.sh`：构建沙箱所需的 Docker 环境。
  - `principle_skill.py`：加载 MECE / SWOT / 金字塔原理等分析方法论。
  - `principles/`：报告生成所用方法论的 Markdown 文档。

- 其他关键模块：
  - `time_handler.py`：注入当前日期和时间到提示词中，避免出现幻觉。
  - `searcher.py`：调用深度研究项目进行舆情检索。
  - `aggregator.py`：聚合舆情与数据分析两类结果并生成最终报告。

### 自定义智能体配置

**LLM 配置示例：**

```yaml
llm:
  service: openai
  model: qwen3-max  # Analyst 可选 qwen3-coder-plus
  openai_api_key: your-api-key
  openai_base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
```

**工具（沙箱）配置示例：**

```yaml
tools:
  code_executor:
    sandbox:
      mode: local
      type: docker_notebook
      image: jupyter-kernel-gateway:version1
      timeout: 120
      memory_limit: "1g"
      cpu_limit: 2.0
      network_enabled: true
```

**搜索配置（`searcher.yaml`）示例：**

```yaml
breadth: 3  # 每层搜索生成的查询数
depth: 1    # 最大搜索深度
is_report: true  # 输出报告而非简短回答
```

### 金融数据支持

`FinancialDataFetcher`工具支持：

- **市场**：A股（sh./sz.）、港股（hk.）、美股（us.）
- **指数**：上证50、沪深300（HS300）、中证500（ZZ500）
- **数据类型**：K线行情、三大财报（利润/资产负债/现金流）、分红、行业分类
- **宏观指标**：利率、存款准备金率、货币供应量（中国）

受到数据接口限制，可能存在一定的缺失和错误，请注意甄别。

### 输出目录结构

工作流将在配置的输出目录（默认：`./output/`）生成如下成果：

```text
output/
├── plan.json                           # 任务拆解结果
├── financial_data/                     # 采集的金融数据
│   ├── stock_prices_*.csv
│   ├── quarterly_financials_*.csv
│   └── ...
├── sessions/                           # 数据分析智能体的会话目录
│   └── session_xxxx/
│       ├── *.png                       # 绘制的图表
│       └── metrics_*.csv               # 计算指标
├── memory/                             # 各智能体的记忆存储目录
├── search/                             # 舆情研究搜索结果
├── resources/                          # 舆情研究文档解析获取的图片
├── synthesized_findings.md             # 关键发现整合
├── report_outline.md                   # 报告大纲
├── chapter_1.md                        # 第1章内容
├── chapter_2.md                        # 第2章内容
├── ...
├── cross_chapter_mismatches.md         # 跨章节一致性校验结果
├── analysis_report.md                  # 数据分析报告
├── sentiment_report.md                 # 舆情分析报告
└── report.md                           # 最终综合报告
```

## 📝 TODOs

1. 提升金融数据抓取工具的稳定性与覆盖度。
2. 持续优化工作流架构以降低 Token 消耗、提升报告生成性能。
3. 加强报告的可视化呈现，支持多格式导出。
4. 优化舆情搜索与研究pipeline，优化信息源管理。
