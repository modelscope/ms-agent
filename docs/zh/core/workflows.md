# 工作流

工作流把明确的阶段和依赖写成配置。它适合步骤可预先定义的任务；如果需要模型自主选择分工，则使用[子智能体](subagents.md)。

## Chain 与 DAG

| 类型 | 选择依据 |
| --- | --- |
| ChainWorkflow | 顺序推进，适合前一步产出交给下一步 |
| DagWorkflow | 有分支、汇合和依赖；当前执行器按拓扑顺序逐个 await 节点 |

```{mermaid}
flowchart TD
 A[规划] --> B[资料检索]
 A --> C[数据采集]
 C --> D[分析]
 B --> E[汇总]
 D --> E
```

配置中的节点名表示阶段，`agent_config`指向节点配置，`next`定义后续节点。FinResearch使用以上类型的依赖关系；图中分支表示依赖，不表示当前执行器并发运行它们。

## 两阶段配置

保存为 `workflow.yaml`，并在同目录放入可运行的 `draft.yaml`、`review.yaml`：

```yaml
draft:
  agent_config: draft.yaml
  next: [review]
review:
  agent_config: review.yaml
```

```bash
ms-agent run --config ./workflow.yaml --query '整理并复核这份资料'
```

省略 `type` 默认选择 ChainWorkflow。当前 Chain 实现会把显式顶层 `type` 当作节点，因此本例不要添加 `type: ChainWorkflow`；这是现有实现限制。DAG 可使用 `type: DagWorkflow`，但不提供节点并发保证。

配置加载会识别 `workflow.yaml/yml`、`simple_workflow.yaml/yml` 等约定名称。不要任意改文件名后仍假设CLI会按工作流运行；也可以显式使用 `WorkflowLoader`。

## 自定义节点与恢复

Chain节点省略 `agent_config` 时沿用前一个Agent解析后的完整配置，不是只继承模型名；首节点应提供明确配置。节点的 `tag` 默认取节点名，用于运行标识及日志/会话区分。DAG节点应分别提供自己的配置，汇合时接收各父节点的输出。

节点可使用LLMAgent或CodeAgent，自定义Python节点需要可信外部代码开关。可参考仓库 `examples/workflow/custom_code.py`；不是任意函数都能作为节点自动接入。

明确输出目录和中间文件依赖，避免并行节点覆盖同一路径。缓存恢复与会话恢复的语义不同；检查已生成产物、配置变化及节点状态再重跑。`ResearchWorkflow` 在通用加载器中的分支未实现，不要把它当作DeepResearch v1的通用启动方式。

下一步：[CodeGenesis](../applications/code-genesis.md)、[FinResearch](../applications/fin-research.md)。实现：`workflow/loader.py`、`chain_workflow.py`、`dag_workflow.py`。
