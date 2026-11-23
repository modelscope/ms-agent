# FinResearch

FinResearch将金融结构化数据和舆情资料组织成研究报告。五个角色按DAG协作，使数据采集、分析和报告聚合可以分别检查。输出是研究辅助材料，不是交易指令或投资建议。

## 角色和依赖

```{mermaid}
flowchart TD
 A[Orchestrator · 任务范围] --> B[Searcher · 舆情研究]
 A --> C[Collector · 金融数据]
 C --> D[Analyst · 定量分析]
 B --> E[Aggregator · 综合报告]
 D --> E
```

Searcher当前调用DeepResearch v1的 `ResearchWorkflowBeta`，不是v2。Collector通过金融数据工具获取资料，Analyst执行分析，Aggregator合并结论。数据源限制、缺失值和时间口径必须人工确认。

## 安装与配置

在源码根目录完成基础环境后：

```bash
pip install -e '.[research]'
pip install akshare baostock
```

若保留 Collector、Analyst 和 Aggregator 默认的 Docker 沙箱环境，安装相应沙箱依赖并构建镜像：

```bash
pip install ms-enclave docker websocket-client
bash projects/fin_research/tools/build_jupyter_image.sh
```

不使用 Docker 时，在 `collector.yaml`、`analyst.yaml` 和 `aggregator.yaml` 中替换整个 `tools.code_executor` 块：

```yaml
tools:
  code_executor:
    mcp: false
    implementation: python_env
    include: [shell_executor]
```

同步修改提示：Collector / Analyst 改用 shell 运行分析脚本，移除 Notebook、重置内核和持久变量要求；Aggregator 将 `/data` 改成实际本地输出目录。Collector / Analyst 的 `<DATA_ROOT>` 会按模式解析。每条命令独立启动，应自行加载模块和数据；提前安装分析依赖。本地执行直接访问宿主资源，不提供 Docker 隔离。

各角色YAML分别配置LLM，通常使用 `OPENAI_API_KEY/OPENAI_BASE_URL`。Searcher的 `tools.search_engine.config_file`指向 `conf.yaml`，其中再配置 `SEARCH_ENGINE`和所需Exa/SerpAPI凭据。不要只配置LLM而遗漏搜索服务。

## 运行一个研究任务

```bash
ms-agent run --config projects/fin_research/workflow.yaml \
  --query '分析一家公司的公开财报，列明数据日期、来源和不确定性' \
  --output_dir ./finance-output --trust_remote_code true
```

输出包含规划、采集数据、分析稿、舆情稿和报告等，以实际日志和文件为准。只测试数据分析时可在副本workflow中移除Searcher分支，但这是缩小范围的测试，不等同于完整研究结果。

## 调整方法论与报告

- 节点配置分别为 `orchestrator/searcher/collector/analyst/aggregator.yaml`，不存在一个统管这些节点的 `agent.yaml`。
- 方法论位于 `tools/specs/principle_specs/`，写作规范位于 `tools/specs/writing_specs/`；加载逻辑在 `spec_loader.py/spec_constant.py`。
- Searcher的breadth/depth控制研究范围；扩大它们会增加检索和模型调用。
- 检查汇总稿是否忠实引用分析数据，不把一致性检查写成消除所有错误的保证。

更多样例和现有功能见[项目目录](https://github.com/modelscope/ms-agent/tree/main/projects/fin_research)。未来工作流优化独立推进，本次文档保留现有入口及历史价值。
