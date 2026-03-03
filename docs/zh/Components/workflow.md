---
slug: workflow
title: 工作流
description: Ms-Agent 工作流：支持多智能体组合执行复杂任务
---

# 工作流

MS-Agent支持工作流执行。工作流同样由yaml文件所配置。工作流由不同的Agent组合而成，完成一个更复杂的任务。目前MS-Agent的工作流支持两类Agent：

- LLMAgent：这个Agent的介绍在[基础智能体](./llm-agent)中，是融合的LLM推理的基本Agent循环
- CodeAgent：仅包含一个run方法，是纯代码的执行流程，可以提供自定义代码实现

## ChainWorkFlow

ChainWorkFlow是一个顺序执行的链式工作流。需要一个workflow.yaml作为启动配置。该配置的样例如下：

- workflow.yaml

```yaml
step1:
  next:
    - step2
  agent_config: step1.yaml


step2:
  next:
    - step3
  agent_config: step2.yaml

step3:
  agent_config: step3.yaml
```

- step1.yaml
```yaml
llm:
  ...

generation_config:
  ...
```

- step2.yaml
```yaml
code_file: custom_code
```

- step3.yaml
```yaml
llm:
  ...

generation_config:
  ...
```

在上面的工作流中，有三个步骤。其中步骤2是一个自定义代码步骤，需要提供一个名为custom_code.py的文件来执行自定义操作。
workflow中的每个后续步骤可以提供独立的config。如果不提供，则继承前序的config文件。

## Example

1. An example of a translation workflow: https://www.modelscope.cn/models/ms-agent/simple_workflow
