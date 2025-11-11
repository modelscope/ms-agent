# FinancialResearch

This project provides a multi-agent framework for financial research, combining quantitative financial data analysis with qualitative sentiment analysis from online sources to generate professional financial reports.

## 🌟 Features

- **Multi-Agent Architecture** - Orchestrated workflow with specialized agents for task decomposition, data collection, analysis, sentiment research, and report aggregation.

- **Dual-Dimension Analysis** - Integrates both financial data metrics and public sentiment analysis for comprehensive insights.

- **Financial Data Collection** - Automated collection of stock prices, financial statements, macro indicators, and market data for A-shares, HK, and US markets.

- **Sentiment Research** - Leverages deep search workflow (`ms-agent/projects/deep_research`) to analyze market sentiment, news coverage, and social media discussions.

- **Professional Report Generation** - Generates structured, multi-section financial reports with visualizations, following industry-standard analytical frameworks (MECE, SWOT, Pyramid Principle, etc.).

- **Sandboxed Code Execution** - Safe data processing and analysis in isolated Docker containers.

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

2. **Searcher Agent** - Conducts in-depth public sentiment research using ResearchWorkflowBeta (`ms-agent/projects/deep_research`) and generates a public sentiment analysis report.

3. **Collector Agent** - Collects financial data based on the defined financial data tasks, using the FinancialDataFetcher tool built on akshare and baostock.

4. **Analyst Agent** - Performs quantitative analysis within a Docker sandbox and generates a quantitative analysis report based on the data obtained from the Collector Agent.

5. **Aggregator Agent** - Generates the final comprehensive analysis report by integrating the results of the sentiment and quantitative analyses, producing and validating each chapter to ensure overall logical consistency.

## 🛠️ Installation

To set up the FinancialResearch framework, follow these steps:

### Python Environment

```bash
# From source code
git clone https://github.com/modelscope/ms-agent.git
cd ms-agent

# Python environment setup
conda create -n financial_research python=3.11
conda activate financial_research
# From source code
pip install -r requirements/framework.txt
pip install -r requirements/research.txt
pip install -e .
# From PyPI (>=v1.1.0)
pip install 'ms-agent[research]'
```

### Sandbox Setup

The Collector and Analyst agents require Docker for sandboxed execution:

```bash
# install ms-enclave (https://github.com/modelscope/ms-enclave)
pip install ms-enclave

# build the required Docker image, make sure you have installed Docker on your device
bash projects/financial_research/tools/build_jupyter_image.sh
```

## 🚀 Quickstart

### Environment Configuration

1. Configure API keys in your environment or directly in YAML files:

```bash
# LLM API
export OPENAI_API_KEY=your_api_key
export OPENAI_BASE_URL=your-api-url

# Search Engine API (for sentiment analysis, you can choose exa or serpapi)
export EXA_API_KEY=your_exa_api_key
export SERPAPI_API_KEY=your_serpapi_api_key
```

2. Configure the search engine config file path in `searcher.yaml`:

```yaml
tools:
  search_engine:
    config_file: projects/financial_research/conf.yaml
```

### Running the Workflow

```bash
# Run from the ms-agent root directory
PYTHONPATH=. python ms_agent/cli/cli.py run \
  --config projects/financial_research \
  --query 'Please analyze the changes in CATL’s (300750.SZ) profitability over the past four quarters and compare them with its major competitors in the new energy sector (such as BYD, Gotion High-Tech, and CALB). In addition, evaluate the impact of industry policies and lithium price fluctuations to forecast CATL’s performance trends for the next two quarters.' \
  --trust_remote_code true
```

### Examples

Please refer to `projects/financial_research/examples`

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
  openai_api_key: ${OPENAI_API_KEY}
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
      memory_limit: "2g"
      cpu_limit: 2.0
      network_enabled: true
```

**Search Configuration (searcher.yaml):**

```yaml
breadth: 4  # Number of search queries per depth level
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
├── report.md                           # Sentiment analysis report
└── aggregator_report.md                # Final comprehensive report
```

## 📝 TODOs

1. Optimize the stability and data coverage of the financial data retrieval tool.

2. Refine the system architecture to reduce token consumption and improve report generation performance.

3. Enhance the visual presentation of output reports and support exporting in multiple file formats.

4. Improve the financial sentiment search pipeline.
