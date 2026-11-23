# Agentic Insight / DeepResearch

DeepResearch combines iterative search, evidence organization, and report writing. The project retains Agentic Insight v2 and the v1 basic/extended pipelines. Their configurations, tools, and Python APIs are not interchangeable.

## Choose a version

| Path | Design | Use it for |
| --- | --- | --- |
| v2 | Researcher coordinates Searcher/Reporter; evidence and intermediate work are files | Extensible multi-round research |
| v1 basic | Search-then-execute with parsing and key-information extraction | Existing applications and the older pipeline |
| v1 extended | Clarification, recursive search, compaction, reporting | Integrations using ResearchWorkflowBeta |

```{mermaid}
flowchart TD
 A[Question and budget] --> B[Researcher plans]
 B --> C[Searcher retrieves]
 C --> D[Evidence and artifacts]
 D --> B
 B --> E[Reporter writes]
 D --> E
 E --> F[Review citations and report]
```

File-backed evidence supports inspection and continued work; it does not eliminate citation errors. Read historical benchmarks with their model combinations and submitted versions since each ranking belongs to that particular submission.

## Before running v2

Install `pip install -e '.[research]'` from the source root. Configure `OPENAI_API_KEY` and `OPENAI_BASE_URL` in a local environment/dotenv file and review:

- `researcher.yaml`: main research model, reflection, quality checks.
- `searcher.yaml`: search model/engines, webpage summarization, budgets.
- `reporter.yaml`: writing model and checks.

These files live in `projects/deep_research/v2/`. Every selected model must be available at the endpoint; summarization and quality checks make additional calls. **The current Searcher configuration defaults to Tavily and needs `TAVILY_API_KEY`.** To use another search service, configure `tools.web_search` in `searcher.yaml` explicitly and provide that service's credentials.

```bash
ms-agent run --config projects/deep_research/v2/researcher.yaml \
  --query 'Compare two public backup approaches, with citations and limitations' \
  --output_dir ./research-output --trust_remote_code true
```

Start with a bounded topic, inspect search evidence and report paths, then expand the budget. `run_benchmark.sh` is an evaluation entry point requiring data, models, and credentials, not a prerequisite-free single-task tutorial.

## v1 compatibility

The basic pipeline uses `ResearchWorkflow`; the extended pipeline uses `ResearchWorkflowBeta` in `ms_agent/workflow/deep_research/`. FinResearch still uses the extended v1 pipeline for sentiment research; keep the v1 interfaces and configuration when maintaining these integrations.

Legacy search configuration uses structures such as `SEARCH_ENGINE`, distinct from v2 `tools.web_search`. Find query-rewriting and other model selections in the project configuration and the corresponding Workflow initialization parameters. Consult the [project documentation](https://github.com/modelscope/ms-agent/tree/main/projects/deep_research) when maintaining v1 integrations.

## Results and limitations

Inspect plans, search evidence, drafts, and final reports in the selected output directory. Open files at the artifact paths reported in the run log; individual tools generate their own filenames. Check whether citations support conclusions, source dates align, and research steps actually finished.

Sources change or fail, and parsing/model calls cost resources. A report is not automatic fact verification. A real research run needs working model, search, and parsing services. Run the bounded example above, then inspect its evidence and report. For benchmark reproduction, follow `run_benchmark.sh` with the matching dataset, models, service credentials, and budget.

Next: [v2 configuration](https://github.com/modelscope/ms-agent/blob/main/projects/deep_research/v2/README.md), [Retrieval](../core/retrieval.md), [Workflows](../core/workflows.md).
