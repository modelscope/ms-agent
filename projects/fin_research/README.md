# **FinResearch**

This project provides a multi-agent framework for financial research, combining quantitative financial data analysis with qualitative sentiment analysis from online sources to generate professional financial reports.

## 🌟 Features

- **Multi-Agent Architecture** - Orchestrated workflow with specialized agents for task decomposition, data collection, analysis, sentiment research, and report aggregation.

- **Multi-Dimension Analysis** - Covers both financial data indicators and public sentiment dimensions, enabling integrated analysis of structured and unstructured data to produce research reports with broad coverage and clear structure.

- **Financial Data Collection** - Automated collection of stock prices, financial statements, macro indicators, and market data for A-shares, HK, and US markets.

- **Sentiment Research** - Deep research on multi-source information from news/media/communities.

- **Professional Report Generation** - Generates structured, multi-section financial reports with visualizations, following industry-standard analytical frameworks (MECE, SWOT, Pyramid Principle, etc.).

- **Sandboxed Code Execution** - Safe data processing and analysis in isolated Docker containers.


**Related Website:**

- FinResearch official documentation: [FinResearch Doc](https://ms-agent-en.readthedocs.io/en/latest/Projects/FinResearch.html)
- FinResearch中文文档： [金融深度研究](https://ms-agent.readthedocs.io/zh-cn/latest/Projects/fin-research.html)
- DEMO: [FinResearchStudio](https://modelscope.cn/studios/ms-agent/FinResearch)
- Examples: [FinResearchExamples](https://www.modelscope.cn/models/ms-agent/fin_research_examples)


## 📋 Architecture

The workflow consists of five specialized agents orchestrated in a DAG structure:

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

1. **Orchestrator Agent** - Decomposes user queries into three components: task description and scope, financial data tasks, and public sentiment tasks.

2. **Searcher Agent** - Unstructured data collection invokes the Deep Research workflow (`ms-agent/projects/deep_research`) to conduct in-depth sentiment analysis and generate a public opinion report.

3. **Collector Agent** - Structured financial data collection uses data acquisition tools built on `akshare`/`baostock` to gather required financial data according to the orchestrator agent’s analysis task.

4. **Analyst Agent** - Performs quantitative analysis within a Docker sandbox and generates a quantitative analysis report based on the data obtained from the Collector Agent.

5. **Aggregator Agent** - Generates the final comprehensive analysis report by integrating the results of the sentiment and quantitative analyses, producing and validating each chapter to ensure overall logical consistency.

## 🛠️ Installation

To set up the FinancialResearch framework, follow these steps:

### Python Environment

```bash
# Download source code
git clone https://github.com/modelscope/ms-agent.git
cd ms-agent

# Python environment setup
conda create -n fin_research python=3.11
conda activate fin_research
# From PyPI (>=v1.5.0)
pip install 'ms-agent[research]'
# From source code
pip install -r requirements/framework.txt
pip install -r requirements/research.txt
pip install -e .

# Data Interface Dependencies
pip install akshare baostock
```

### Sandbox Setup

The Collector and Analyst agents default use Docker for sandboxed code execution (optional):

```bash
# install ms-enclave (https://github.com/modelscope/ms-enclave)
pip install ms-enclave docker websocket-client

# build the required Docker image, make sure you have installed Docker on your system
bash projects/fin_research/tools/build_jupyter_image.sh
```

If you prefer not to install Docker and related dependencies, you can instead configure the local code execution tool by modifying the default `tools` section in both `analyst.yaml` and `collector.yaml`:

```yaml
tools:
  code_executor:
    mcp: false
    implementation: python_env
    exclude:
      - python_executor
      - shell_executor
      - file_operation
```

With this configuration, code is executed through a Jupyter kernel–based notebook executor that isolates environment variables and supports running shell commands. The required dependencies (including those for data analysis and code execution) will be installed automatically on the first run.

If you want a lighter-weight Python-only execution environment without introducing additional notebook dependencies, you can use:

```yaml
tools:
  code_executor:
    mcp: false
    implementation: python_env
    exclude:
      - notebook_executor
      - file_operation
```

This configuration uses an independent Python executor together with a shell command executor and is suitable for lightweight code execution scenarios.

## 🚀 Quickstart

### Environment Configuration

Configure API keys in your environment or directly in YAML files:

```bash
# LLM API
export OPENAI_API_KEY=your_api_key
export OPENAI_BASE_URL=your-api-url

# Search Engine APIs (for sentiment analysis; you may choose either Exa or SerpApi, both offer a free quota)
# Exa account registration: https://exa.ai; SerpApi account registration: https://serpapi.com
# If you prefer to run the FinResearch project for testing without configuring a search engine, you may skip this step and refer to the Quick Start section.
export EXA_API_KEY=your_exa_api_key
export SERPAPI_API_KEY=your_serpapi_api_key
```

Configure the search engine config file path in `searcher.yaml`:

```yaml
tools:
  search_engine:
    config_file: projects/fin_research/conf.yaml
```

### Running the Workflow

Quickly start the full FinResearch workflow for testing:

```bash
# Run from the ms-agent root directory
PYTHONPATH=. python ms_agent/cli/cli.py run \
  --config projects/fin_research \
  --query 'Please analyze the changes in CATL’s (300750.SZ) profitability over the past four quarters and compare them with its major competitors in the new energy sector (such as BYD, Gotion High-Tech, and CALB). In addition, evaluate the impact of industry policies and lithium price fluctuations to forecast CATL’s performance trends for the next two quarters.' \
  --trust_remote_code true
```

When no search engine service is configured, you can set up a minimal version of the FinResearch workflow for testing (without the public sentiment deep research component) by modifying the workflow.yaml file as follows:

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

After that, start the project from the command line in the same way as before.
Please note that due to incomplete information dimensions, FinResearch may not be able to generate long and detailed analysis reports for complex questions. It is recommended to use this setup for testing purposes only.

Run the FinResearch application:

```bash
# Launch the Gradio service via command line (you can start without additional arguments, specifying only --app_type fin_research)
ms-agent app --app_type fin_research --server_name 0.0.0.0 --server_port 7860 --share

# Alternatively, launch the Gradio service by running a Python script
cd ms-agent/app
python fin_research.py
```

### Examples

Please refer to `projects/fin_research/examples` for more examples.

<https://github.com/user-attachments/assets/2ef0f7a1-985b-4dbd-9d75-da16246e985e>

## 🔧 Developer Guide

### Project Components and Functions

Each component in the FinancialResearch workflow serves a specific purpose:

- **workflow.yaml** - Entry configuration file that defines the entire workflow's execution process, orchestrating the five agents (Orchestrator, Searcher, Collector, Analyst, Aggregator) in the DAG structure.

- **agent.yaml files** (Orchestrator.yaml, searcher.yaml, collector.yaml, analyst.yaml, aggregator.yaml) - Individual agent configuration files that define each agent's behavior, tools, LLM settings, and specific parameters for their roles in the financial analysis pipeline.

- **conf.yaml** - Search engine configuration file that specifies API keys and settings for sentiment analysis tools (Exa, SerpAPI), controlling how the Searcher agent conducts public sentiment research.

- **callbacks/** - Directory containing specialized callback modules for each agent:
  - **orchestrator_callback.py** - Save the output plan to local disk.
  - **collector_callback.py** - Load the output plan from local disk and add it to the user message.
  - **analyst_callback.py** - Load the output plan from local disk and save output data analysis report to local disk.
  - **aggregator_callback.py** - Save the final comprehensive analysis report to local disk.
  - **file_parser.py** - Handles parsing and processing of files include json, python code, etc.

- **tools/** - Utility directory containing:
  - **build_jupyter_image.sh** - Script to build the Docker sandbox environment for secure code execution
  - **principle_skill.py** - Tool for loading analytical frameworks (MECE, SWOT, Pyramid Principle, etc.)
  - **principles/** - Markdown documentation of analytical methodologies used in report generation

- **time_handler.py** - Utility module for injecting current date and time into prompts.
- **searcher.py** - Call `ms-agent/projects/deep_research` to conduct public sentiment searches.
- **aggregator.py** - Aggregate the results of the sentiment and quantitative analyses.

### Customizing Agent Behavior

Each agent's behavior can be customized through its YAML configuration file:

**LLM Configuration:**

```yaml
llm:
  service: openai
  model: qwen3-max  # or qwen3-coder-plus for Analyst
  openai_api_key: your-api-key
  openai_base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
```

**Tool Configuration (Sandbox):**

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

**Search Configuration (searcher.yaml):**

```yaml
breadth: 3  # Number of search queries per depth level
depth: 1    # Maximum research depth
is_report: true  # Generate report or return raw data
```

### Financial Data Scope

The `FinancialDataFetcher` tool supports:

- **Markets**: A-shares (sh./sz.), HK (hk.), US (us.)
- **Indices**: SSE 50, CSI 300 (HS300), CSI 500 (ZZ500)
- **Data Types**: K-line data, financial statements (profit/balance/cash flow), dividends, industry classifications
- **Macro Indicators**: Interest rates, reserve ratios, money supply (China)

Data access is limited by upstream interfaces and may contain gaps or inaccuracies. Please review results critically.

### Output Structure

The workflow generates results in the configured output directory (default: `./output/`):

```text
output/
├── plan.json                           # Task decomposition result
├── financial_data/                     # Collected data files
│   ├── stock_prices_*.csv
│   ├── quarterly_financials_*.csv
│   └── ...
├── sessions/                           # Analysis session artifacts
│   └── session_xxxx/
│       ├── *.png                       # Generated charts
│       └── metrics_*.csv               # Computed metrics
├── memory/                             # Memory for each agent
├── search/                             # Search results from sentiment research
├── resources/                          # Images from sentiment research
├── synthesized_findings.md             # Integrated insights
├── report_outline.md                   # Report structure
├── chapter_1.md                        # Chapter 1 files
├── chapter_2.md                        # Chapter 2 files
├── ...
├── cross_chapter_mismatches.md         # Consistency audit
├── analysis_report.md                  # Data analysis report
├── sentiment_report.md                 # Sentiment analysis report
└── report.md                           # Final comprehensive report
```

## 📝 TODOs

1. Optimize the stability and data coverage of the financial data retrieval tool.

2. Refine the system architecture to reduce token consumption and improve report generation performance.

3. Enhance the visual presentation of output reports and support exporting in multiple file formats.

4. Improve the financial sentiment search pipeline.
