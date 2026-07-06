# Document Research Capability

## When to Use

Activate this capability when the user asks to:
- Analyze or summarize one or more documents (PDF, TXT, PPT, DOCX)
- Research and produce a report from URLs (web pages, arxiv papers)
- Compare multiple papers or documents
- Generate a multimodal report with extracted images and tables
- Deep-dive into a specific document or set of documents

## Async Tools (Recommended)

### Tool: `submit_doc_research_task`

Starts document research in the background. Returns immediately with a `task_id`.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | string | yes | -- | Research prompt about the documents |
| `urls` | string | no | -- | Newline or comma-separated URLs |
| `file_paths` | string | no | -- | Comma-separated local file paths |
| `output_dir` | string | no | auto | Directory for outputs |

At least one of `urls` or `file_paths` should be provided alongside the query.
If neither is provided, the workflow will attempt web search based on the query.

**Returns:**
```json
{
  "task_id": "a1b2c3d4",
  "status": "running",
  "output_dir": "/path/to/output/doc_research_20260407_143000",
  "message": "Document research task a1b2c3d4 started..."
}
```

### Tool: `check_doc_research_progress`

Polls the status of a document research task.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `task_id` | string | yes | The task_id from submit_doc_research_task |

**Returns:**
```json
{
  "task_id": "a1b2c3d4",
  "status": "running",
  "report_available": false,
  "images": 0
}
```

### Tool: `get_doc_research_report`

Retrieves the final markdown report.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `task_id` | string | yes | -- | The task_id from submit_doc_research_task |
| `max_chars` | integer | no | 50000 | Max characters to return |

**Returns (on completion):**
```json
{
  "task_id": "a1b2c3d4",
  "status": "completed",
  "report_path": "/path/to/report.md",
  "report_content": "# Research Report\n\n...",
  "truncated": false,
  "images": 5
}
```

## SOP Workflow

### Step 1: Gather Inputs

Ask the user:
- What documents or URLs to analyze?
- What aspects to focus on?
- Any comparison or specific analysis angle?

### Step 2: Submit the Task

**Single document analysis:**
```
submit_doc_research_task(
    query="Deeply analyze and summarize the following document",
    urls="https://arxiv.org/pdf/2504.17432"
)
```

**Multi-document comparison:**
```
submit_doc_research_task(
    query="Compare Qwen3 and Qwen2.5, what optimizations are there?",
    urls="https://arxiv.org/abs/2505.09388\nhttps://arxiv.org/abs/2412.15115"
)
```

**Local file analysis:**
```
submit_doc_research_task(
    query="Summarize the key findings from these reports",
    file_paths="/path/to/report1.pdf,/path/to/report2.docx"
)
```

Tell the user:
> "I've started analyzing the documents (ID: a1b2c3d4). This typically
> takes 5-20 minutes depending on document count and size."

### Step 3: Check Progress

```
check_doc_research_progress(task_id="a1b2c3d4")
```

### Step 4: Retrieve Report

```
get_doc_research_report(task_id="a1b2c3d4")
```

Present key findings and highlight extracted images/tables.

## Supported Input Formats

| Format | Extension | Notes |
|---|---|---|
| PDF | .pdf | Full parsing with image/table extraction |
| Plain text | .txt | Direct text content |
| PowerPoint | .ppt, .pptx | Slide content extraction |
| Word | .doc, .docx | Document content extraction |
| Web URLs | http(s)://... | Web page content fetching |
| arXiv | arxiv.org/... | Paper PDF auto-download |

## Output Structure

```
output_dir/
├── report.md          # Final markdown report
└── resources/         # Extracted images and tables
    ├── abc123.png
    └── def456.png
```

## Report Features

- Structured following the **MECE principle** (Mutually Exclusive,
  Collectively Exhaustive)
- Embedded images and tables from source documents
- LaTeX math formula rendering
- Multi-document comparison when multiple inputs provided

## Prerequisites

- `pip install 'ms-agent[research]'` for document parsing dependencies
- LLM API key configured (`OPENAI_API_KEY`)

## Notes

- The report includes extracted images with relative paths to the
  `resources/` directory.
- For very large documents, processing time increases proportionally.
- The workflow supports both search-based (no files, just a query) and
  document-based (files/URLs provided) research modes.
- Ray can be used for parallel document parsing:
  `pip install "ray[default]"` and set `RAG_EXTRACT_USE_RAY=1`.
