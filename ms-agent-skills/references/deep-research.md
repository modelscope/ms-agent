# Deep Research Capability

## When to Use

Activate this capability when the user asks to:
- Research a topic in depth or do a "deep dive"
- Investigate a complex question requiring multiple sources
- Perform a literature review or technology survey
- Produce a comprehensive report with citations

## Async Tools (Recommended)

The async trio is the recommended interface for MCP clients. It does NOT
block the calling agent -- research runs as a background subprocess.

### Tool: `submit_research_task`

Starts research in the background. Returns immediately with a `task_id`.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `query` | string | yes | The research question or topic |
| `config_path` | string | no | Path to researcher.yaml (uses bundled default) |
| `output_dir` | string | no | Where to write outputs (auto-generated if omitted) |

**Returns:**
```json
{
  "task_id": "a1b2c3d4",
  "status": "running",
  "output_dir": "/path/to/output/deep_research_20260318_143000",
  "message": "Research task a1b2c3d4 started. Use check_research_progress..."
}
```

### Tool: `check_research_progress`

Polls the status of a running task. Call periodically (e.g. every 2-5 min).

| Parameter | Type | Required | Description |
|---|---|---|---|
| `task_id` | string | yes | The task_id from submit_research_task |

**Returns (running):**
```json
{
  "task_id": "a1b2c3d4",
  "task_type": "research",
  "status": "running",
  "created_at": "2026-03-18T14:30:00",
  "query": "AI agent frameworks 2026",
  "output_dir": "/path/to/output/deep_research_20260318_143000",
  "evidence_notes": 23,
  "evidence_analyses": 5,
  "report_available": false,
  "log_tail": "..."
}
```

**Returns (terminal):**
```json
{
  "task_id": "a1b2c3d4",
  "task_type": "research",
  "status": "completed",
  "created_at": "2026-03-18T14:30:00",
  "completed_at": "2026-03-18T15:15:00",
  "query": "AI agent frameworks 2026",
  "output_dir": "/path/to/output/deep_research_20260318_143000",
  "evidence_notes": 45,
  "evidence_analyses": 12,
  "report_available": true,
  "report_path": "/path/to/final_report.md"
}
```

Status values: `running`, `completed`, `failed`, `cancelled`. When terminal,
includes `completed_at`; when `failed`, includes `error`. Progress fields
(`evidence_notes`, `evidence_analyses`, `report_available`, `log_tail`) are
merged from the output directory while running or after completion.

### Tool: `get_research_report`

Retrieves the full report content once the task is completed.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `task_id` | string | yes | The task_id from submit_research_task |
| `max_chars` | integer | no | Max characters to return (default: 50000) |

**Returns (on completion):**
```json
{
  "task_id": "a1b2c3d4",
  "status": "completed",
  "report_path": "/path/to/final_report.md",
  "report_content": "# Research Report\n\n...",
  "truncated": false
}
```

**Returns (still running):**
```json
{
  "task_id": "a1b2c3d4",
  "status": "running",
  "message": "Research is still in progress. Evidence collected so far: 23 notes, 5 analyses. Please check again later."
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
  "output_dir": "/path/to/output/deep_research_20260318_143000"
}
```

## SOP Workflow (Async)

### Step 1: Clarify the Research Question

Before submitting, ask the user:
- What specific aspect should the research focus on?
- Any preferred sources or constraints?
- Target audience for the report?

### Step 2: Submit the Task

```
submit_research_task(query="<refined research question>")
```

Tell the user:

> "I've started a deep research task (ID: a1b2c3d4). This typically takes
> 20-60 minutes as it performs multiple rounds of web search, evidence
> collection, and report generation. I'll check on its progress and share
> the results when it's ready. Feel free to ask me other things in the meantime."

### Step 3: Periodically Check Progress

Every few minutes (or when the user asks about it):

```
check_research_progress(task_id="a1b2c3d4")
```

Report back: "Research is ongoing -- 23 evidence notes collected so far."

### Step 4: Retrieve the Report

When `check_research_progress` returns `status: "completed"`:

```
get_research_report(task_id="a1b2c3d4")
```

Then:
1. Provide an executive summary (3-5 key findings)
2. Highlight notable sources and evidence quality
3. Offer to dive deeper into specific sections

### Step 5: Handle Failures

If `status: "failed"`, check the `error` field:
- Missing API key: check the provider selected by the research configuration. The default OpenAI-compatible configuration uses `OPENAI_API_KEY`; a custom `config_path` may select another provider or supply credentials directly.
- Config not found: verify ms-agent installation
- Network errors: suggest retry

## Sync Tool: `deep_research`

A synchronous version is available but **not recommended** for MCP clients
because it blocks for 20–60 minutes (most MCP tool timeouts are 30 seconds).
Use only from direct Python API calls or environments with very long timeouts.
Prefer the async submit/check/get trio.

**Estimated Duration:** descriptor `hours`; typical wall-clock 20–60 minutes.

### Parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `query` | string | yes | The research question or topic |
| `config_path` | string | no | Path to researcher.yaml (uses bundled default) |
| `output_dir` | string | no | Where to write outputs (auto-generated if omitted) |

### Returns

On success:

```json
{
  "status": "completed",
  "output_dir": "/path/to/output/deep_research_20260318_143000",
  "report_path": "/path/to/final_report.md"
}
```

On failure:

```json
{
  "status": "failed",
  "output_dir": "/path/to/output/deep_research_20260318_143000",
  "error": "..."
}
```

Config not found:

```json
{
  "status": "failed",
  "error": "Config not found: ..."
}
```

## Output Directory Structure

The capability wrapper inspects evidence counts under `evidence/notes/*.md` and
`evidence/analyses/*.md`, and locates the report via `final_report.md` first,
then falls back to the first `report.md` found via recursive search.

```
output_dir/
├── final_report.md          # Primary report path (preferred)
├── report.md                # Fallback if final_report.md is absent
├── evidence/
│   ├── notes/               # Counted by check_research_progress
│   └── analyses/            # Counted by check_research_progress
└── ms_agent.log             # Subprocess stderr (log_tail in progress polls)
```

Other pipeline artifacts (e.g. `evidence/index.json`, `reports/outline.json`,
`reports/chapters/`) may exist but are **pipeline-internal** — the capability
wrapper does not read or count them.

## Architecture

The deep research pipeline runs as an unmodified subprocess. Async task
tracking is handled by the shared `AsyncTaskManager` — the same mechanism
used by agent delegation and other long-running capabilities.

```
submit_research_task()
    │
    ├── AsyncTaskManager.submit(task_type="research", ...)
    ├── Launches subprocess (fire-and-forget)
    └── Returns task_id immediately
         │
         ▼
    Background subprocess:
    ┌──────────────────────┐
    │   Researcher Agent   │ ← Unchanged v2 code
    │   ├── Searcher       │
    │   └── Reporter       │
    └──────────────────────┘
         │
         ▼ (AsyncTaskManager updates task status on completion)

check_research_progress(task_id)
    └── AsyncTaskManager.check() + counts evidence files

get_research_report(task_id)
    └── Reads final_report.md (or fallback report.md) content
```
