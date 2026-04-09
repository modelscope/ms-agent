# Agentic Insight v2

Agentic Insight v2 provides a more scalable framework for deep research, enabling agents to autonomously explore and execute complex tasks.

> 🏆 **Benchmark**: **#2 Open-Source** (#5 Overall) on [DeepResearch Bench](https://github.com/Ayanami0730/deep_research_bench) — **55.31** with the submitted version (Qwen3.5-Plus + GPT 5.2). See [Leaderboard](https://huggingface.co/spaces/muset-ai/DeepResearch-Bench-Leaderboard).

### 🌟 Features

Agentic Insight v2 is designed around:

- **Extensible main-agent + sub-agent architecture**: a Researcher orchestrates Searcher/Reporter and can be extended with new sub-agents and tools.
- **File-system based context management**: flexible, debuggable, and resume-friendly context via structured artifacts on disk.
- **Deep-research optimized toolchain**: dedicated todo, evidence, search, and report tools tuned for iterative research loops.
- **Evidence-bound report generation**: reports are generated from raw evidence with explicit bindings for higher trustworthiness and traceability.

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

#### Environment Variables

Create `.env` file in repository root:

```bash
cp projects/deep_research/.env.example .env
```

Edit `.env` and set the following **required** environment variables:

```bash
# LLM Configuration (Required)
OPENAI_API_KEY=your_api_key
OPENAI_BASE_URL=https://your-openai-compatible-endpoint/v1

# Search Engine Configuration (choose one, or use default arxiv with no config needed)
EXA_API_KEY=your_exa_key              # Recommended, register at: https://exa.ai
# SERPAPI_API_KEY=your_serpapi_key    # Or choose SerpApi, register at: https://serpapi.com
```

#### Model Configuration (⚠️ Required for First Run)

v2 uses three YAML config files to drive the Researcher, Searcher, and Reporter agents. **Before first run, you must modify model names according to your LLM provider**, otherwise you may get model-not-found errors. If you want each agent to use a different model or provider, modify the `llm` section in the corresponding YAML independently; otherwise the defaults from `.env` are used.

##### Models to Configure

For balanced performance and cost, we recommend a **tiered model configuration** — choosing different models for each agent based on its role and requirements.

| YAML File | Config Path | Current Default | Description | Recommendation |
|-----------|-------------|-----------------|-------------|----------------|
| `researcher.yaml` | `llm.model` | `gpt-5-2025-08-07` | Researcher Agent (main agent) | Use a stronger model (e.g. `qwen3-max` / `gpt-5`) for task planning and coordination |
| `searcher.yaml` | `llm.model` | `qwen3.5-plus` | Searcher Agent | Can use same or slightly weaker model (e.g. `qwen3.5-plus` / `MiniMax-M2.5`) |
| `searcher.yaml` | `tools.web_search.summarizer_model` | `qwen3.5-flash` | Web page summarization model (optional) | Use a fast, cheap model (e.g. `qwen3.5-flash` / `gpt-4.1-mini`) |
| `reporter.yaml` | `llm.model` | `qwen3.5-plus` | Reporter Agent | Can use same or slightly weaker model (e.g. `qwen3.5-plus` / `MiniMax-M2.5`) |
| `researcher.yaml` / `reporter.yaml` | `self_reflection.quality_check.model` | `qwen3.5-flash` | Quality check model (optional) | Use a fast, cheap model (e.g. `qwen3.5-flash` / `gpt-4.1-mini`) |

##### Common LLM Provider Examples

Modify model names in YAML files according to your provider:

**Using OpenAI:**

```yaml
# Agent configuration
llm:
  service: openai
  model: gpt-5-2025-08-07
  openai_api_key: <OPENAI_API_KEY>
  openai_base_url: <OPENAI_BASE_URL>

# Also modify quality_check and summarizer_model (defaults to OpenAI-compatible provider):
tools:
  web_search:
    summarizer_model: qwen3.5-flash
    summarizer_api_key: <OPENAI_API_KEY>
    summarizer_base_url: <OPENAI_BASE_URL>

self_reflection:
  quality_check:
    enabled: true
    model: qwen3-flash
    openai_api_key: <OPENAI_API_KEY>
    openai_base_url: <OPENAI_BASE_URL>
```

**Other Compatible Endpoints:** Refer to your provider's documentation for model identifiers.

#### Search Engine Configuration

Edit `searcher.yaml` to configure search engines:

```yaml
tools:
  web_search:
    engines:
      - exa      # or serpapi (requires corresponding API key in .env)
      - arxiv    # arxiv requires no API key, always available
    api_key: <EXA_API_KEY>  # When using EXA
    # Or when using SerpApi, add (uncomment):
    # serpapi_provider: google  # Options: google, bing, baidu
```

**Default:** If no search engine API key is configured, system will use `arxiv` (academic literature search only).

#### Advanced Configuration (Optional)

##### Web Page Summarization

Enabled by default to compress long web content, reducing context bloat, speeding up research, and saving cost:

```yaml
tools:
  web_search:
    enable_summarization: true
    summarizer_model: qwen3.5-flash  # Can switch to a cheaper model
    max_content_chars: 200000 # Max content chars allowed for summarization; content beyond this is truncated
    summarizer_max_workers: 15
    summarization_timeout: 360
```

**Note:** Summarization makes additional LLM calls consuming more tokens, but significantly reduces the Searcher Agent's context length.

##### Quality Check

Both Researcher and Reporter have quality check mechanisms for verifying report generation quality:

```yaml
self_reflection:
  enabled: true
  max_retries: 2  # Max check rounds
  quality_check:
    enabled: true
    model: qwen3.5-flash
```

##### Prefix Cache (Prompt Caching)

Explicitly triggers cache creation and hits to improve speed and reduce cost (only supported by some providers and models):

```yaml
generation_config:
  force_prefix_cache: true  # Auto-detects provider support
  prefix_cache_roles: [system, user, assistant, tool] # Roles to explicitly request caching for
```

**Supported Providers:** DashScope, Anthropic, and some others. If encountering errors, set to `false`.

#### Configuration File Locations

v2's three YAML config files are located at:

- `projects/deep_research/v2/researcher.yaml` - Researcher main agent config
- `projects/deep_research/v2/searcher.yaml` - Searcher search agent config
- `projects/deep_research/v2/reporter.yaml` - Reporter report generation config

**Placeholder Note:** Placeholders like `<OPENAI_API_KEY>` / `<EXA_API_KEY>` in YAMLs are automatically replaced from `.env` environment variables at runtime. **Do not hardcode API keys in YAMLs** to reduce leak risk.

#### Run

##### Command Line

```bash
PYTHONPATH=. python ms_agent/cli/cli.py run \
  --config projects/deep_research/v2/researcher.yaml \
  --query "Write your research question here" \
  --trust_remote_code true \
  --output_dir "output/deep_research/runs" \
  --load_cache true  # Load cache from previous run to resume
```

##### Benchmark Script

We provide `run_benchmark.sh` to run a single demo query or reproduce the full benchmark suite.
**All commands below must be run from the repository root directory.**

**Mode 1 — Single demo query** (no extra setup required):

```bash
bash projects/deep_research/v2/run_benchmark.sh
```

When `DR_BENCH_ROOT` is **not** set, the script runs a single built-in demo query and saves results to `output/deep_research/benchmark_run/`.

**Mode 2 — Full benchmark suite** (requires the benchmark dataset):

```bash
DR_BENCH_ROOT=/path/to/deep_research_bench bash projects/deep_research/v2/run_benchmark.sh
```

When `DR_BENCH_ROOT` is set, the script reads all queries from `$DR_BENCH_ROOT/data/prompt_data/query.jsonl` and runs them in parallel via `dr_bench_runner.py`. You can override additional parameters:

```bash
DR_BENCH_ROOT=/path/to/deep_research_bench \
  WORKERS=3 \
  LIMIT=5 \
  MODEL_NAME=my_experiment \
  WORK_ROOT=temp/benchmark_runs \
  OUTPUT_JSONL=/path/to/ms_deepresearch_v2_benchmark.jsonl \
  bash projects/deep_research/v2/run_benchmark.sh
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `WORKERS` | `2` | Number of parallel workers |
| `LIMIT` | `0` | Max queries to run (`0` = all) |
| `MODEL_NAME` | `ms_deepresearch_v2_benchmark` | Experiment name for output file |
| `WORK_ROOT` | `temp/benchmark_runs` | Working directory for intermediate results |
| `OUTPUT_JSONL` | `$DR_BENCH_ROOT/data/test_data/raw_data/<MODEL_NAME>.jsonl` | Output JSONL path |

**Note:** The script automatically reads API keys from `.env` in the repository root. Ensure environment variables are properly configured before running.

#### Run in WebUI

You can also use Agentic Insight v2 from the built-in WebUI:

```bash
ms-agent ui
```

Then open `http://localhost:7860`, select **Deep Research**, and make sure you have configured:

- `OPENAI_API_KEY` / `OPENAI_BASE_URL` (LLM settings)
- Either `EXA_API_KEY` or `SERPAPI_API_KEY` (search tools)

You can set them via `.env` or in WebUI **Settings**. WebUI run artifacts are stored under `webui/work_dir/<session_id>/`.

### Outputs (Where to Find Results)

Given `--output_dir output/deep_research/runs`:

- **Final report (user-facing)**: `output/deep_research/runs/final_report.md`
- **Plan list**: `output/deep_research/runs/plan.json(.md)`
- **Evidence store**: `output/deep_research/runs/evidence/`
  - `index.json` and `notes/` are used by Reporter to generate the report.
- **Reporter artifacts**: `output/deep_research/runs/reports/`
  - Outline, chapters, draft, and the assembled report artifact.

### ❓ Troubleshooting

| Error Type | Possible Cause | Solution |
|-----------|---------------|----------|
| `Model not found` / `Invalid model` | Model name in YAML doesn't match API endpoint | Check and modify `llm.model`, `summarizer_model`, and `quality_check.model` in the three YAMLs to match your provider |
| `Invalid API key` / `Unauthorized` | API key in `.env` is incorrect or expired | Verify `OPENAI_API_KEY` in `.env` is correct, or regenerate API key |
| `Search engine error` / `EXA_API_KEY not found` | Search engine API key not configured | Add `EXA_API_KEY` or `SERPAPI_API_KEY` to `.env`, or modify `searcher.yaml` to use only `arxiv` |
| 400 error / `Invalid request body` | Some generation parameters incompatible | Remove unsupported fields from `generation_config` in the YAML |
| `Timeout` / Timeout errors | Network issues or request too long | Check network connection, or increase `tool_call_timeout` value in the YAML |
| Output too short or incomplete | Model generation parameters limiting | Add or increase `max_tokens` value in `generation_config` in the YAML |
| Stuck mid-execution | Sub-agent in infinite loop or waiting | Check log files in `output_dir` to see which agent is stuck; may need to adjust `max_chat_round` |
| `.env` file not found | `.env` in wrong location | Ensure `.env` is in **repository root**, not in `projects/deep_research/` or `v2/` directories |

#### Getting Help

- Report issues: [GitHub Issues](https://github.com/modelscope/ms-agent/issues)
