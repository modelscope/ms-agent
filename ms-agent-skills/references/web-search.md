# Web Search Capability

## When to Use

Activate this tool when the user asks to:
- Search the web for information
- Find academic papers or research articles
- Look up current events or recent data
- Gather search results before diving deeper

## Tool: `web_search`

**Granularity:** Tool (atomic)
**Estimated Duration:** seconds

Performs a web search and returns structured results. Supports multiple
search engines and optional full-page content fetching.

### Parameters

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | string | yes | -- | The search query |
| `num_results` | integer | no | 5 | Number of results to return |
| `engine_type` | string | no | `arxiv` | Engine: `arxiv`, `exa`, or `serpapi` |
| `fetch_content` | boolean | no | false | Fetch full page content for each result |

### Engine Selection Guide

| Engine | Best For | API Key Required |
|---|---|---|
| `arxiv` | Academic papers, research | No |
| `exa` | General web, semantic search | Yes (`EXA_API_KEY`) |
| `serpapi` | Google/Bing results | Yes (`SERPAPI_API_KEY`) |

### Examples

**Search for research papers:**
```
web_search(query="transformer architecture improvements 2026", engine_type="arxiv", num_results=10)
```

**General web search with content:**
```
web_search(query="best practices for LLM agent frameworks", engine_type="exa", fetch_content=true, num_results=3)
```

### Response Format

```json
{
  "status": "ok",
  "query": "transformer architecture improvements 2026",
  "engine": "arxiv",
  "count": 5,
  "results": [
    {
      "title": "Paper Title",
      "url": "https://arxiv.org/abs/...",
      "summary": "Brief summary of the paper..."
    }
  ]
}
```

When `fetch_content=true`, each result includes an additional `content`
field with the page text (truncated to 10,000 characters).

## SOP: Quick Information Gathering

### Step 1: Choose the Right Engine

- For academic/research questions → `arxiv`
- For general web info → `exa` or `serpapi`
- If unsure → start with `arxiv`, fall back to `exa`

### Step 2: Execute the Search

```
web_search(query="<user's question>", engine_type="arxiv", num_results=5)
```

### Step 3: Present Results

- Summarize the top 3-5 results for the user
- Include titles, URLs, and key findings
- If the user wants more detail, re-run with `fetch_content=true`

### Step 4: Combine with Deep Research (Optional)

For thorough investigation, use `web_search` for quick preliminary results,
then `submit_research_task` for a comprehensive deep-dive report.

## Notes

- `arxiv` is the default engine because it requires no API key.
- `fetch_content=true` adds latency (fetches each URL via Jina Reader).
  Use it only when summaries are insufficient.
- Results are returned in the engine's default ranking order.
