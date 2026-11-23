# Workflows

Workflows express known stages and dependencies as configuration. Use them when the process can be defined in advance; use [subagents](subagents.md) when the model should choose how to delegate.

## Chain and DAG

| Type | Choose it when |
| --- | --- |
| ChainWorkflow | Stages run in sequence, passing work onward |
| DagWorkflow | Branches and joins have explicit dependencies; the current executor awaits nodes sequentially in topological order |

```{mermaid}
flowchart TD
 A[Plan] --> B[Research]
 A --> C[Collect data]
 C --> D[Analyze]
 B --> E[Aggregate]
 D --> E
```

Node names identify stages, `agent_config` selects their configurations, and `next` declares successors. FinResearch uses this kind of dependency graph. Branches represent dependencies, not concurrent execution in the current executor.

## Two-stage configuration

Save as `workflow.yaml` alongside runnable `draft.yaml` and `review.yaml` files:

```yaml
draft:
  agent_config: draft.yaml
  next: [review]
review:
  agent_config: review.yaml
```

```bash
ms-agent run --config ./workflow.yaml --query 'Organize and review this material'
```

Omitting `type` selects ChainWorkflow. The current Chain implementation treats an explicit top-level `type` as a node, so do not add `type: ChainWorkflow` to this example. This is an existing implementation limitation. DAG uses `type: DagWorkflow`, without a node-concurrency guarantee.

Configuration loading recognizes conventional names such as `workflow.yaml/yml` and `simple_workflow.yaml/yml`. Do not rename the file arbitrarily and assume the CLI will still select workflow execution. You can use `WorkflowLoader` explicitly.

## Custom nodes and recovery

A Chain node omitting `agent_config` reuses the previous agent's complete resolved configuration, not just its model name. Give the first node explicit configuration. A node's `tag` defaults to its name and identifies execution/log/session context. DAG nodes need their own configurations; joins receive parent outputs.

Nodes can use LLMAgent or CodeAgent. External Python nodes require trusted-code permission; see `examples/workflow/custom_code.py`. Arbitrary functions are not automatically workflow nodes.

Choose output directories and intermediate-file dependencies deliberately. Concurrent nodes should not overwrite the same path. Cache recovery differs from conversation recovery: inspect artifacts, configuration changes, and node state before rerunning. The generic loader's `ResearchWorkflow` branch is unimplemented; it is not a general entry point for DeepResearch v1.

Next: [CodeGenesis](../applications/code-genesis.md), [FinResearch](../applications/fin-research.md). Implementation: `workflow/loader.py`, `chain_workflow.py`, `dag_workflow.py`.
