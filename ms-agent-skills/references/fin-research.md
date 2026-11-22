# Financial Research Capability

## When to Use

Activate this capability when the user asks to:
- Analyze stocks, financial statements, or market data
- Compare companies across financial metrics
- Research market sentiment for specific sectors or companies
- Generate comprehensive financial analysis reports
- Investigate profitability, valuations, or macro indicators

## Async Tools (Recommended)

### Tool: `submit_fin_research_task`

Starts financial research in the background. Returns immediately with a `task_id`.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | string | yes | -- | Financial research question |
| `config_path` | string | no | bundled | Path to fin_research config directory |
| `output_dir` | string | no | auto | Directory for research outputs |

**Returns:**
```json
{
  "task_id": "a1b2c3d4",
  "status": "running",
  "output_dir": "/path/to/output/fin_research_20260407_143000",
  "message": "Financial research task a1b2c3d4 started..."
}
```

### Tool: `check_fin_research_progress`

Polls status and reports data collection/analysis progress.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `task_id` | string | yes | The task_id from submit_fin_research_task |

**Returns (running):**
```json
{
  "task_id": "a1b2c3d4",
  "task_type": "fin_research",
  "status": "running",
  "created_at": "2026-04-07T14:30:00",
  "query": "Analyze CATL profitability...",
  "output_dir": "/path/to/output/fin_research_20260407_143000",
  "chapters": 2,
  "data_files": 8,
  "charts": 5,
  "has_plan": true,
  "has_analysis_report": true,
  "has_sentiment_report": false,
  "report_available": false,
  "log_tail": "..."
}
```

**Returns (terminal):**
```json
{
  "task_id": "a1b2c3d4",
  "task_type": "fin_research",
  "status": "completed",
  "created_at": "2026-04-07T14:30:00",
  "completed_at": "2026-04-07T15:20:00",
  "chapters": 5,
  "data_files": 12,
  "charts": 8,
  "has_plan": true,
  "has_analysis_report": true,
  "has_sentiment_report": true,
  "report_available": true
}
```

Status values: `running`, `completed`, `failed`, `cancelled`. When terminal,
includes `completed_at`; when `failed`, includes `error`.

### Tool: `get_fin_research_report`

Retrieves the final comprehensive report.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `task_id` | string | yes | -- | The task_id from submit_fin_research_task |
| `max_chars` | integer | no | 50000 | Max characters to return |

**Returns (on completion):**
```json
{
  "task_id": "a1b2c3d4",
  "status": "completed",
  "report_path": "/path/to/report.md",
  "report_content": "# Financial Analysis Report\n\n...",
  "truncated": false,
  "output_dir": "/path/to/output/fin_research_20260407_143000",
  "chapters": 5,
  "data_files": 12,
  "charts": 8,
  "has_plan": true,
  "has_analysis_report": true,
  "has_sentiment_report": true
}
```

**Returns (still running):**
```json
{
  "task_id": "a1b2c3d4",
  "status": "running",
  "message": "Financial research is still in progress. Progress: 2 chapters, 8 data files, 5 charts generated."
}
```

**Returns (failed):**
```json
{
  "task_id": "a1b2c3d4",
  "status": "failed",
  "error": "..."
}
```

**Returns (completed but report missing):**
```json
{
  "task_id": "a1b2c3d4",
  "status": "completed",
  "error": "Report file not found in output directory",
  "output_dir": "/path/to/output/fin_research_20260407_143000"
}
```

## SOP Workflow

### Step 1: Clarify the Research Scope

Ask the user:
- Which company/stock (include ticker symbol if possible)?
- What time period to analyze?
- Specific metrics or comparisons needed?
- Markets of interest (A-shares, HK, US)?

### Step 2: Submit the Task

```
submit_fin_research_task(
    query="Analyze CATL (300750.SZ) profitability over the past four quarters and compare with BYD and Gotion High-Tech"
)
```

Tell the user:
> "I've started a financial research task (ID: a1b2c3d4). This typically
> takes 20-60 minutes as it collects financial data, runs quantitative
> analysis, performs sentiment research, and generates a comprehensive report."

### Step 3: Monitor Progress

```
check_fin_research_progress(task_id="a1b2c3d4")
```

Report: "Data collection complete (8 CSV files), 2 chapters generated,
quantitative analysis report ready."

### Step 4: Retrieve and Present the Report

```
get_fin_research_report(task_id="a1b2c3d4")
```

## Sync Tool: `fin_research`

Synchronous version that blocks until financial research completes. **Not
recommended for MCP clients** — prefer the async trio.

**Estimated Duration:** descriptor `hours`; typical wall-clock 20–60 minutes.

### Parameters

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | string | yes | -- | Financial research question |
| `config_path` | string | no | bundled | Path to fin_research config directory |
| `output_dir` | string | no | auto | Directory for research outputs |

### Returns

On success:

```json
{
  "status": "completed",
  "output_dir": "/path/to/output/fin_research_20260407_143000",
  "report_path": "/path/to/report.md"
}
```

On failure:

```json
{
  "status": "failed",
  "output_dir": "/path/to/output/fin_research_20260407_143000",
  "error": "..."
}
```

## Architecture

The workflow is a 5-agent DAG:

```
           Orchestrator
          /            \
     Searcher       Collector
         \             |
          \         Analyst
           \         /
          Aggregator
```

1. **Orchestrator** - Decomposes the query into data tasks and sentiment tasks
2. **Searcher** - Sentiment analysis via deep research on news/media
3. **Collector** - Structured financial data collection (akshare/baostock)
4. **Analyst** - Quantitative analysis in Docker sandbox with visualizations
5. **Aggregator** - Integrates all findings into a comprehensive report

## Output Structure

```
output_dir/
├── plan.json                # Task decomposition
├── financial_data/          # Collected CSV data files
├── sessions/                # Analysis artifacts (charts, metrics)
├── analysis_report.md       # Quantitative analysis report
├── sentiment_report.md      # Sentiment analysis report
├── chapter_1.md ... N.md    # Individual chapters
└── report.md                # Final comprehensive report
```

## Supported Markets and Data

| Market | Ticker Format | Examples |
|--------|--------------|----------|
| A-shares (China) | XXXXXX.SZ/.SH | 300750.SZ, 600519.SH |
| Hong Kong | XXXXX.HK | 00700.HK |
| US | Symbol | AAPL, TSLA |

Data types: K-line, financial statements, dividends, industry classifications,
macro indicators (interest rates, money supply).

## Prerequisites

### Capability descriptor (declared)

The MCP capability declares **`OPENAI_API_KEY`** as its only static
`requires.env` entry. This is the LLM credential needed to run the workflow.

### Runtime project prerequisites (not in descriptor)

These are needed for full functionality but are validated at runtime, not
declared on the capability descriptor:

- **Docker** (optional): For sandboxed code execution. Build image with:
  `bash projects/fin_research/tools/build_jupyter_image.sh` — path is relative
  to the **ms-agent repository root** and is unavailable when only the skill
  package is copied into another agent host.
- **Search engines** (optional): For sentiment analysis, configure
  `EXA_API_KEY` or `SERPAPI_API_KEY`. Without search, only quantitative
  analysis is available.
- **Data dependencies**: `pip install akshare baostock`

## Notes

- Without a search engine configured, the workflow runs in minimal mode
  (quantitative only, no sentiment research).
- Data access depends on upstream APIs (akshare/baostock) and may have gaps.
- The Docker sandbox is optional; a Jupyter kernel-based executor is the
  fallback.
- Reports follow industry-standard frameworks: MECE, SWOT, Pyramid Principle.
