
# Agentic Insight v2

Agentic Insight v2 provides a more scalable framework for deep research, enabling agents to autonomously explore and execute complex tasks.

### 🌟 Features

Agentic Insight v2 is designed around:

- **Extensible main-agent + sub-agent architecture**: a Researcher orchestrates Searcher/Reporter and can be extended with new sub agents and tools.
- **File-system based context management**: flexible, debuggable, and resume-friendly context via structured artifacts on disk.
- **Deep-research optimized toolchain**: dedicated todo, evidence, search, and report tools tuned for iterative research loops.
- **Evidence-bound report generation**: reports are generated from raw evidence with explicit bindings for higher trustworthiness.

### 🚀 Quickstart

#### Prerequisites

Install dependencies (from repo root):

```bash
# From source code
git clone https://github.com/modelscope/ms-agent.git
pip install -r requirements/research.txt
pip install -e .

# From PyPI (>=v1.1.0)
pip install 'ms-agent[research]'
```

#### Environment variables (`.env`)

From repo root:

```bash
cp projects/deep_research/.env.example .env
```

Edit `.env` and set:

- `OPENAI_API_KEY` (key of OpenAI-compatible endpoint)
- `OPENAI_BASE_URL` (OpenAI-compatible endpoint)
- One of:
  - `EXA_API_KEY` (recommended, register at [Exa](https://exa.ai), free quota available)
  - `SERPAPI_API_KEY` (register at [SerpApi](https://serpapi.com), free quota available)

Notes:

- v2 configs use placeholders like `<OPENAI_API_KEY>` / `<EXA_API_KEY>`, which are replaced from environment variables at runtime.
- Do not hardcode keys in scripts; keep them in `.env` (and never commit `.env`).

#### Run (Researcher entry)

```bash
PYTHONPATH=. python ms_agent/cli/cli.py run \
  --config projects/deep_research/v2/researcher.yaml \
  --query "Write your research question here" \
  --trust_remote_code true \
  --output_dir "output/deep_research/runs"
```

### Key configs (what to edit)

- `projects/deep_research/v2/researcher.yaml`
  - Researcher orchestration prompt and workflow-level settings.
- `projects/deep_research/v2/searcher.yaml`
  - Search engines (exa/arxiv/serpapi), fetching/summarization, evidence store settings.
- `projects/deep_research/v2/reporter.yaml`
  - Report generation workflow and report artifacts directory.

### Outputs (where to find results)

Given `--output_dir output/deep_research/runs`:

- **Final report (user-facing)**: `output/deep_research/runs/final_report.md`
- **Todo list**: `output/deep_research/runs/plan.json(.md)`
- **Evidence store**: `output/deep_research/runs/evidence/`
  - `index.json` and `notes/` are used by Reporter to cite sources.
- **Reporter artifacts**: `output/deep_research/runs/reports/`
  - Outline, chapters, draft, and the assembled report artifact.
