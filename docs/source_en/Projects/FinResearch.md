# FinResearch

Ms-Agent’s FinancialResearch project is a multi-agent workflow tailored for financial market research. It combines quantitative market/data analysis with in-depth online information research to automatically produce a structured, professional research report.

## Overview

### Features

- **Multi-agent collaboration**: Five specialized agents—Orchestrator / Searcher / Collector / Analyst / Aggregator—work together to complete the end-to-end flow from task decomposition to report aggregation.
- **Multi-dimensional research**: Covers both quantitative “financial data” and qualitative “news/sentiment,” yielding more complete and explainable conclusions.
- **Financial data collection**: Automatically fetches market quotes, financial statements, macro indicators, and market data for A-shares, Hong Kong stocks, and U.S. stocks. Uses the `FinancialDataFetcher` tool.
- **In-depth sentiment research**: Reuses the deep research workflow (`ms-agent/projects/deep_research`) to analyze multi-source information from news/media/communities.
- **Secure and reproducible**: Quantitative analysis runs inside a Docker-based sandbox to ensure environment isolation and reproducibility.
- **Professional report output**: Adheres to methodologies such as MECE, SWOT, and the Pyramid Principle, generates content chapter by chapter, and performs cross-chapter consistency checks.

### Architecture

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

- **Orchestrator**: Splits the user task into three parts: tasks and scope, financial data tasks, and sentiment research tasks.
- **Searcher**: Invokes `ms-agent/projects/deep_research` to conduct in-depth sentiment research and produces a sentiment analysis report.
- **Collector**: Collects financial data (e.g., statements, macro indicators) according to the task list using `FinancialDataFetcher` (akshare/baostock).
- **Analyst**: Performs quantitative analysis in a sandbox and outputs a data analysis report with visualizations.
- **Aggregator**: Consolidates sentiment and quantitative results, generates chaptered content with consistency checks, and produces the final comprehensive report.

## How to Use

### Python Environment

```bash
# Download source code
git clone https://github.com/modelscope/ms-agent.git
cd ms-agent

# Python environment setup
conda create -n financial_research python=3.11
conda activate financial_research
# From PyPI (>=v1.4.1)
pip install 'ms-agent[research]'
# From source code
pip install -r requirements/framework.txt
pip install -r requirements/research.txt
pip install -e .

# Data Interface Dependencies
pip install akshare baostock
```

### Sandbox Environment

```bash
pip install ms-enclave  # https://github.com/modelscope/ms-enclave
bash projects/financial_research/tools/build_jupyter_image.sh
```

### Environment Variables

Configure API keys in your system environment or in YAML.

```bash
# LLM API (example)
export OPENAI_API_KEY=your_api_key
export OPENAI_BASE_URL=your-api-url

# Search Engine APIs (for sentiment analysis; you may choose either Exa or SerpApi, both offer a free quota)
# Exa account registration: https://exa.ai; SerpApi account registration: https://serpapi.com
# If you prefer to run the FinResearch project for testing without configuring a search engine, you may skip this step and refer to the Quick Start section.
export EXA_API_KEY=your_exa_api_key
export SERPAPI_API_KEY=your_serpapi_api_key
```

Specify search engine configuration in `searcher.yaml`:

```yaml
tools:
  search_engine:
    config_file: projects/financial_research/conf.yaml
```

### Quick Start

Quickly start the full FinResearch workflow for testing:

```bash
# Run from the ms-agent project root
PYTHONPATH=. python ms_agent/cli/cli.py run \
  --config projects/financial_research \
  --query "Analyze CATL (300750.SZ): changes in profitability over the last four quarters and comparison with major competitors in the new energy sector; factoring in industrial policy and lithium price fluctuations, forecast the next two quarters." \
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

## Developer Guide

### Components

- `workflow.yaml`: Workflow entry. Orchestrates execution of the Orchestrator / Searcher / Collector / Analyst / Aggregator agents based on DagWorkflow.
- `agent.yaml` (`orchestrator.yaml`, `searcher.yaml`, `collector.yaml`, `analyst.yaml`, `aggregator.yaml`): Defines each agent (or workflow)’s behavior, tools, LLM parameters, and prompts (roles and responsibilities).
- `conf.yaml`: Search engine configuration, including API keys and parameters for Exa / SerpAPI.
- `callbacks/`: Callback modules for each agent.
  - `orchestrator_callback.py`: Save the task plan locally.
  - `collector_callback.py`: Load the task plan from local storage and add it to user messages.
  - `analyst_callback.py`: Load the task plan and save the quantitative analysis report locally.
  - `aggregator_callback.py`: Save the final comprehensive report locally.
  - `file_parser.py`: Parse and process code/JSON text.
- `tools/`: Tooling.
  - `build_jupyter_image.sh`: Build the Docker environment required by the sandbox.
  - `principle_skill.py`: Load analysis methodologies such as MECE / SWOT / Pyramid Principle.
  - `principles/`: Markdown documents for the methodologies used in report generation.
- Other key modules:
  - `time_handler.py`: Inject current date/time into prompts to reduce hallucinations.
  - `searcher.py`: Invoke the deep research project to run sentiment search.
  - `aggregator.py`: Aggregate sentiment and data analysis results to generate the final report.

### Configuration Examples

LLM configuration example:

```yaml
llm:
  service: openai
  model: qwen3-max  # For Analyst, qwen3-coder-plus is also available
  openai_api_key: ${OPENAI_API_KEY}
  openai_base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
```

Sandbox (tool) configuration example:

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

Search configuration example (`searcher.yaml`):

```yaml
breadth: 4  # Number of queries generated per layer
depth: 1    # Maximum search depth
is_report: true  # Output report instead of raw data
```

### Output Structure

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

### Data Coverage

Data access is limited by upstream interfaces and may contain gaps or inaccuracies. Please review results critically.

- **Markets**: A-shares (`sh.`/`sz.`), Hong Kong (`hk.`), U.S. (`us.`)
- **Indices**: SSE 50, CSI 300 (HS300), CSI 500 (ZZ500)
- **Data types**: K-line, financial statements (P/L, balance sheet, cash flow), dividends, industry classification
- **Macro**: Interest rates, reserve requirement ratio, money supply (China)
