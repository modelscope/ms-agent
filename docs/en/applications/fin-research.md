# FinResearch

FinResearch combines structured financial data and sentiment research into reports. Five roles cooperate through a DAG so collection, analysis, and aggregation can be inspected separately. Output is research assistance, not trading instructions or investment advice.

## Roles and dependencies

```{mermaid}
flowchart TD
 A[Orchestrator · scope] --> B[Searcher · sentiment research]
 A --> C[Collector · financial data]
 C --> D[Analyst · quantitative analysis]
 B --> E[Aggregator · report]
 D --> E
```

Searcher currently calls DeepResearch v1 `ResearchWorkflowBeta`, not v2. Collector retrieves financial data, Analyst runs analysis, and Aggregator combines findings. Confirm data availability, missing values, dates, and accounting conventions.

## Install and configure

After basic source installation, run from the repository root:

```bash
pip install -e '.[research]'
pip install akshare baostock
```

Collector, Analyst, and Aggregator use Docker sandboxes by default. Keeping them requires sandbox dependencies and the image:

```bash
pip install ms-enclave docker websocket-client
bash projects/fin_research/tools/build_jupyter_image.sh
```

Without Docker, replace the entire `tools.code_executor` block in `collector.yaml`, `analyst.yaml`, and `aggregator.yaml`:

```yaml
tools:
  code_executor:
    mcp: false
    implementation: python_env
    include: [shell_executor]
```

Update prompts too: Collector/Analyst must use shell scripts rather than Notebook tools, kernel resets, or persistent variables. Replace Aggregator's `/data` path with the local output directory; Collector/Analyst resolve `<DATA_ROOT>` by mode. Each command starts independently and must load its modules/data. Install analysis dependencies beforehand. Local execution accesses host resources directly, without Docker isolation.

Configure each role's LLM, normally through `OPENAI_API_KEY/OPENAI_BASE_URL`. Searcher's `tools.search_engine.config_file` points to `conf.yaml`, whose `SEARCH_ENGINE` configuration supplies Exa/SerpAPI credentials. LLM credentials alone do not configure search.

## Run research

```bash
ms-agent run --config projects/fin_research/workflow.yaml \
  --query 'Analyze a company public filing, stating dates, sources, and uncertainty' \
  --output_dir ./finance-output --trust_remote_code true
```

Output includes planning, collected data, analytical/sentiment drafts, and reports; follow actual logs and paths. Removing Searcher from a copied workflow tests a narrower data-analysis path, not the complete research system.

## Customize methodology and reports

- Roles have separate `orchestrator/searcher/collector/analyst/aggregator.yaml` files, not one shared `agent.yaml`.
- Methodologies live in `tools/specs/principle_specs/`; writing rules in `tools/specs/writing_specs/`. Loading is handled by `spec_loader.py/spec_constant.py`.
- Searcher breadth/depth controls research scope and cost.
- Verify that reports accurately reference analytical data. Consistency checks do not guarantee error-free conclusions.

See the [project directory](https://github.com/modelscope/ms-agent/tree/main/projects/fin_research) for examples and capabilities. Future workflow modernization is separate from preserving the current documented entry points.
