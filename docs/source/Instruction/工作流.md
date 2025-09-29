# 工作流

MS-Agent支持工作流执行。工作流同样由yaml文件所配置。工作流由不同的Agent组合而成，完成一个更复杂的任务。目前MS-Agent的工作流支持两类Agent：

- LLMAgent：这个Agent的介绍在[基础智能体](./基础智能体.md)中，是融合的LLM推理的基本Agent循环
- CodeAgent：仅包含一个run方法，是纯代码的执行流程，可以提供自定义代码实现

## ChainWorkFlow

ChainWorkFlow是一个顺序执行的链式工作流。需要一个workflow.yaml作为启动配置。该配置的样例如下：

```yaml
step1:
  next:
    - step2
  agent_config: step1.yaml
  agent:
    name: LLMAgent
    kwargs:
      tag: step1


step2:
  next:
    - step3
  agent:
    name: CodeAgent
    kwargs:
      code_file: custom_code
      tag: step2


step3:
  agent:
    name: LLMAgent
    kwargs:
      tag: step3
```

在上面的工作流中，有三个步骤。步骤1和步骤3都使用了LLMAgent，并且步骤1提供了step1.yaml。步骤2是一个自定义代码步骤，需要提供一个名为custom_code.py的文件来执行自定义操作。
步骤2和步骤3可以提供独立的config。如果不提供，则继承前序的config文件。
