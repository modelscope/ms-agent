# Agentic Insight v2

Agentic Insight v2提供了一个更具可扩展性的深度研究框架，使智能体能够自主探索并执行复杂任务。

### 🌟 功能特性

Agentic Insight v2 的设计理念围绕以下要点：

- **可扩展的主 agent + 子 agent 架构**：Researcher 负责编排 Searcher/Reporter，并可扩展新的子 agent 与工具。
- **基于文件系统的上下文管理**：通过在磁盘上存储结构化的中间产物来管理上下文，更加灵活、易调试，且支持断点续跑。
- **面向 deep research 优化的工具链**：围绕迭代式研究循环提供专用的 todo、evidence、search、report 工具。
- **基于证据绑定的报告生成**：报告从原始证据出发并进行显式证据绑定，从而提升可信度与可追溯性。

### 🚀 快速开始

#### 前置条件

安装依赖（在仓库根目录执行）：

```bash
# From source code
git clone https://github.com/modelscope/ms-agent.git
pip install -r requirements/research.txt
pip install -e .

# From PyPI (>=v1.1.0)
pip install 'ms-agent[research]'
```

#### 环境变量配置

在仓库根目录创建 `.env` 文件：

```bash
cp projects/deep_research/.env.example .env
```

编辑 `.env` 并设置以下**必需**环境变量：

```bash
# LLM 配置（必需）
OPENAI_API_KEY=your_api_key
OPENAI_BASE_URL=https://your-openai-compatible-endpoint/v1

# 搜索引擎配置（二选一，或使用默认的 arxiv 无需配置）
EXA_API_KEY=your_exa_key              # 推荐，注册：https://exa.ai
# SERPAPI_API_KEY=your_serpapi_key    # 或者选择 SerpApi，注册：https://serpapi.com
```

#### 模型配置（⚠️ 首次运行必读）

v2 使用三个 YAML 配置文件驱动 Researcher、Searcher 和 Reporter 三个 Agent。**在首次运行前，必须根据你的 LLM 服务商修改模型名称**，否则可能会因模型不存在而报错。如果希望每个 Agent 使用不同的模型和供应商，请在对应的 yaml 内独立修改 llm 字段下的配置，否则默认使用 `.env` 中的配置。

##### 需要配置的模型

为了平衡性能和成本，建议采用**分层模型配置**，即根据 Agent 的职责和需求，选择不同的模型和供应商。

| YAML 文件                             | 配置路径                                  | 当前默认值              | 说明                        | 选型建议                                           |
| ----------------------------------- | ------------------------------------- | ------------------ | ------------------------- | ---------------------------------------------- |
| `researcher.yaml`                   | `llm.model`                           | `gpt-5-2025-08-07` | Researcher Agent（主 Agent） | 使用较强的模型（如 `qwen3-max` / `gpt-5`），负责任务规划和协调     |
| `searcher.yaml`                     | `llm.model`                           | `qwen3.5-plus`     | Searcher Agent            | 可使用相同或稍弱的模型（如 `qwen3.5-plus` / `MiniMax-M2.5`） |
| `searcher.yaml`                     | `tools.web_search.summarizer_model`   | `qwen3.5-flash`    | 网页总结模型（可选功能）              | 使用快速便宜的模型（如 `qwen3.5-flash` / `gpt-4.1-mini`）  |
| `reporter.yaml`                     | `llm.model`                           | `qwen3.5-plus`     | Reporter Agent            | 可使用相同或稍弱的模型（如 `qwen3.5-plus` / `MiniMax-M2.5`） |
| `researcher.yaml` / `reporter.yaml` | `self_reflection.quality_check.model` | `qwen3.5-flash`    | 质量检查模型（可选功能）              | 使用快速便宜的模型（如 `qwen3.5-flash` / `gpt-4.1-mini`）  |

##### 常见 LLM 服务商配置示例

根据你使用的服务商，修改 YAML 文件中的模型名称：

**使用 OpenAI：**

```yaml
# Agent 配置
llm:
  service: openai
  model: gpt-5-2025-08-07
  openai_api_key: <OPENAI_API_KEY>
  openai_base_url: <OPENAI_BASE_URL>

# 同时修改 quality_check 和 summarizer_model（默认使用openai兼容供应商）：
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

**使用其他兼容端点：** 请参考服务商文档中的模型标识符。

#### 搜索引擎配置

编辑 `searcher.yaml`，配置搜索引擎：

```yaml
tools:
  web_search:
    engines:
      - exa      # 或 serpapi（需要在 .env 配置对应的 API key）
      - arxiv    # arxiv 无需 API key，始终可用
    api_key: <EXA_API_KEY>  # 使用 EXA 时
    # 或使用 SerpApi 时，额外配置（取消注释）：
    # serpapi_provider: google  # 可选：google, bing, baidu
```

**默认配置：** 如果不配置搜索引擎 API key，系统会使用 `arxiv`（仅限学术文献搜索）。

#### 高级配置（可选）

##### 网页摘要功能

默认开启，用于压缩长网页内容以减少上下文膨胀、加速搜索调研过程、节约成本：

```yaml
tools:
  web_search:
    enable_summarization: true
    summarizer_model: qwen3.5-flash  # 可换成更便宜的模型
    max_content_chars: 200000 # 允许进行摘要的最大内容字符数，超过后会截断
    summarizer_max_workers: 15
    summarization_timeout: 360
```

**注意：** 摘要功能会额外调用 LLM，消耗更多 token，但能显著减少 Searcher Agent 的上下文长度。

##### 质量检查功能

Researcher 和 Reporter 都配置了质量检查机制，用于检查报告生成质量：

```yaml
self_reflection:
  enabled: true
  max_retries: 2  # 最大检查次数
  quality_check:
    enabled: true
    model: qwen3.5-flash
```

##### Prefix Cache（提示词缓存）

用于显式触发缓存创建和命中，提高速度、降低成本（仅部分服务商和模型支持）：

```yaml
generation_config:
  force_prefix_cache: true  # 自动检测服务商是否支持
  prefix_cache_roles: [system, user, assistant, tool] # 显式申请缓存的位置
```

**支持的服务商：** DashScope、Anthropic、部分其他服务商。如遇错误，请设为 `false`。

#### 配置文件位置

v2 的三个 YAML 配置文件位于：

- `projects/deep_research/v2/researcher.yaml` - Researcher 主 Agent 配置
- `projects/deep_research/v2/searcher.yaml` - Searcher 搜索 Agent 配置
- `projects/deep_research/v2/reporter.yaml` - Reporter 报告生成 Agent 配置

**占位符说明：** YAML 中的 `<OPENAI_API_KEY>` / `<EXA_API_KEY>` 等占位符会在运行时自动从 `.env` 环境变量替换，**请勿在 YAML 中硬编码 API key**以降低泄露风险。

#### 运行

##### 命令行运行

```bash
PYTHONPATH=. python ms_agent/cli/cli.py run \
  --config projects/deep_research/v2/researcher.yaml \
  --query "在这里写你的研究问题" \
  --trust_remote_code true \
  --output_dir "output/deep_research/runs" \
  --load_cache true  # 加载上一次运行的缓存继续运行
```

##### Benchmark 脚本

我们提供了 `run_benchmark.sh`，支持运行单条 demo query 或复现完整 benchmark 测试结果。
**以下所有命令均需在仓库根目录下执行。**

**模式一 — 单条 demo query**（无需额外配置）：

```bash
bash projects/deep_research/v2/run_benchmark.sh
```

当 `DR_BENCH_ROOT` **未设置**时，脚本会运行一条内置的 demo query，结果保存至 `output/deep_research/benchmark_run/`。

**模式二 — 完整 benchmark 全量测试**（需要 benchmark 数据集）：

```bash
DR_BENCH_ROOT=/path/to/deep_research_bench bash projects/deep_research/v2/run_benchmark.sh
```

当 `DR_BENCH_ROOT` **已设置**时，脚本会从 `$DR_BENCH_ROOT/data/prompt_data/query.jsonl` 读取全部 query，通过 `dr_bench_runner.py` 并行执行。可通过环境变量覆盖默认参数：

```bash
DR_BENCH_ROOT=/path/to/deep_research_bench \
  WORKERS=3 \
  LIMIT=5 \
  MODEL_NAME=ms_deepresearch_v2_benchmark \
  WORK_ROOT=temp/benchmark_runs \
  OUTPUT_JSONL=/path/to/ms_deepresearch_v2_benchmark.jsonl \
  bash projects/deep_research/v2/run_benchmark.sh
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `WORKERS` | `2` | 并行 worker 数量 |
| `LIMIT` | `0` | 最多运行多少条 query（`0` = 全部） |
| `MODEL_NAME` | `ms_deepresearch_v2_benchmark` | 实验名称，用于输出文件命名 |
| `WORK_ROOT` | `temp/benchmark_runs` | 中间结果工作目录（默认使用临时目录） |
| `OUTPUT_JSONL` | `$DR_BENCH_ROOT/data/test_data/raw_data/<MODEL_NAME>.jsonl` | 输出 JSONL 路径 |

**注意：** 脚本会从仓库根目录的 `.env` 自动读取 API keys，请确保已正确配置环境变量。

#### 在 WebUI 中使用

你也可以在内置 WebUI 中使用 Agentic Insight v2：

```bash
ms-agent ui
```

然后打开 `http://localhost:7860`，选择 **Deep Research**，并确保已配置：

- `OPENAI_API_KEY` / `OPENAI_BASE_URL`（LLM 配置）
- 二选一：`EXA_API_KEY` 或 `SERPAPI_API_KEY`（搜索工具）

你可以通过 `.env` 或 WebUI 的 **Settings** 进行配置。WebUI 的运行产物会保存在 `webui/work_dir/<session_id>/` 下。

### 输出（结果位置）

假设你使用 `--output_dir output/deep_research/runs`：

- **最终报告（面向用户）**：`output/deep_research/runs/final_report.md`
- **计划列表**：`output/deep_research/runs/plan.json(.md)`
- **证据库**：`output/deep_research/runs/evidence/`
  - `index.json` 与 `notes/` 会被 Reporter 用来生成报告。
- **Reporter 中间产物**：`output/deep_research/runs/reports/`
  - 大纲、章节、草稿与汇总后的报告产物。

### ❓ 故障排查

| 错误类型                                            | 可能原因                      | 解决方法                                                                               |
| ----------------------------------------------- | ------------------------- | ---------------------------------------------------------------------------------- |
| `Model not found` / `Invalid model`             | YAML 中的模型名与 API 端点不匹配     | 检查并修改三个 YAML 文件的 `llm.model`、`summarizer_model` 和 `quality_check.model`，确保与你的服务商匹配 |
| `Invalid API key` / `Unauthorized`              | `.env` 中的 API key 不正确或已过期 | 检查 `.env` 中的 `OPENAI_API_KEY` 是否正确，或重新生成 API key                                   |
| `Search engine error` / `EXA_API_KEY not found` | 搜索引擎 API key 未配置          | 在 `.env` 添加 `EXA_API_KEY` 或 `SERPAPI_API_KEY`，或修改 `searcher.yaml` 仅使用 `arxiv`      |
| 请求 400 错误 / `Invalid request body`              | 某些生成参数不兼容                 | 在对应 YAML 的 `generation_config` 中删除不支持的字段                                           |
| `Timeout` / 超时错误                                | 网络问题或请求时间过长               | 检查网络连接，或在对应 YAML 中增加 `tool_call_timeout` 的值                                        |
| 输出内容过短或不完整                                      | 模型生成参数限制                  | 在对应 YAML 的 `generation_config` 中添加或增大 `max_tokens` 的值                              |
| 运行到一半卡住                                         | 某个子 Agent 陷入死循环或等待        | 检查 `output_dir` 下的日志文件，查看是哪个 Agent 卡住，可能需要调整 `max_chat_round`                      |
| 找不到 `.env` 文件                                   | `.env` 文件位置不正确            | 确保 `.env` 文件在**仓库根目录**，而不是 `projects/deep_research/` 或 `v2/` 目录下                   |

#### 获取更多帮助

- 报告问题：[GitHub Issues](https://github.com/modelscope/ms-agent/issues)
