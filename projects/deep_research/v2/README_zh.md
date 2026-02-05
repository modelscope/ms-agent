
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

#### 环境变量（`.env`）

在仓库根目录执行：

```bash
cp projects/deep_research/.env.example .env
```

编辑 `.env` 并设置：

- `OPENAI_API_KEY`（OpenAI-compatible endpoint 的 key）
- `OPENAI_BASE_URL`（OpenAI-compatible endpoint）
- 二选一：
  - `EXA_API_KEY`（推荐，在 [Exa](https://exa.ai) 注册，提供免费额度）
  - `SERPAPI_API_KEY`（在 [SerpApi](https://serpapi.com) 注册，提供免费额度）

说明：

- v2 配置使用 `<OPENAI_API_KEY>` / `<EXA_API_KEY>` 这类占位符，运行时会自动从环境变量替换。
- 不要在脚本里硬编码 key；请放在 `.env` 中（并确保 `.env` 不提交到仓库）。

#### 运行（Researcher 入口）

```bash
PYTHONPATH=. python ms_agent/cli/cli.py run \
  --config projects/deep_research/v2/researcher.yaml \
  --query "在这里写你的研究问题" \
  --trust_remote_code true \
  --output_dir "output/deep_research/runs"
```

### 关键配置（常改位置）

- `projects/deep_research/v2/researcher.yaml`
  - Researcher 的编排提示词与工作流级别设置。
- `projects/deep_research/v2/searcher.yaml`
  - 搜索引擎（exa/arxiv/serpapi）、抓取/摘要、证据存储等设置。
- `projects/deep_research/v2/reporter.yaml`
  - 报告生成工作流与报告产物目录设置。

### 输出（结果位置）

假设你使用 `--output_dir output/deep_research/runs`：

- **最终报告（面向用户）**：`output/deep_research/runs/final_report.md`
- **Todo 列表**：`output/deep_research/runs/plan.json(.md)`
- **证据库**：`output/deep_research/runs/evidence/`
  - `index.json` 与 `notes/` 会被 Reporter 用来生成引用。
- **Reporter 中间产物**：`output/deep_research/runs/reports/`
  - 大纲、章节、草稿与汇总后的报告产物。
