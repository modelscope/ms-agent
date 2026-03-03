---
slug: Workflow
title: Workflow
description: Ms-Agent Workflow
---

# Workflow

MS-Agent supports workflow execution. Workflows are also configured by yaml files. Workflows are composed of different Agents to complete more complex tasks. Currently, MS-Agent's workflow supports two types of Agents:

- LLMAgent: This Agent is introduced in [Basic Agent](./LLMAgent.md), which is a basic Agent loop that integrates LLM reasoning
- CodeAgent: Contains only a run method, which is a pure code execution process that can provide custom code implementation

## ChainWorkFlow

ChainWorkFlow is a sequential chain workflow. It requires a workflow.yaml as the startup configuration. An example of this configuration is as follows:

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

- custom_code.py

```python
from ms_agent.agent import CodeAgent

class CustomCode(CodeAgent):

    async def run(self, inputs):
        ...
```

- step3.yaml
```yaml
llm:
  ...

generation_config:
  ...
```

In the above workflow, there are three steps. Step 1 and Step 3 both use LLMAgent, Step 2 is a custom code step that requires providing a file named custom_code.py to execute custom operations.
All steps can provide independent configs. If not provided, they inherit the config file from the previous step.

## Example

1. An example of a translation workflow: https://www.modelscope.cn/models/ms-agent/simple_workflow
