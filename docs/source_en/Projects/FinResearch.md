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

# Search engines (used for sentiment research; choose exa or serpapi)
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

```bash
# Run from the ms-agent project root
PYTHONPATH=. python ms_agent/cli/cli.py run \
  --config projects/financial_research \
  --query "Analyze CATL (300750.SZ): changes in profitability over the last four quarters and comparison with major competitors in the new energy sector; factoring in industrial policy and lithium price fluctuations, forecast the next two quarters." \
  --trust_remote_code true
```

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
├── plan.json                           # Task decomposition results
├── financial_data/                     # Financial data
│   ├── stock_prices_*.csv
│   ├── quarterly_financials_*.csv
│   └── ...
├── sessions/                           # Analysis session artifacts (charts/metrics)
├── memory/                             # Agent memories
├── search/                             # Sentiment search results
├── resources/                          # Images for sentiment analysis
├── synthesized_findings.md             # Consolidated key findings
├── report_outline.md                   # Report outline
├── chapter_*.md                        # Chapters
├── cross_chapter_mismatches.md         # Cross-chapter consistency checks
├── analysis_report.md                  # Quantitative analysis report
├── report.md                           # Sentiment analysis report
└── aggregator_report.md                # Final comprehensive report
```

### Data Coverage

Data access is limited by upstream interfaces and may contain gaps or inaccuracies. Please review results critically.

- **Markets**: A-shares (`sh.`/`sz.`), Hong Kong (`hk.`), U.S. (`us.`)
- **Indices**: SSE 50, CSI 300 (HS300), CSI 500 (ZZ500)
- **Data types**: K-line, financial statements (P/L, balance sheet, cash flow), dividends, industry classification
- **Macro**: Interest rates, reserve requirement ratio, money supply (China)
