# Skill Evolution

Skill Evolution是根据任务轨迹和评测信号优化本地技能库的独立工作流。它适合有可自动评测目标的任务，不表示普通聊天会话会自动完成通用技能进化。

## 以验证集决定是否接受更新

```{mermaid}
flowchart TD
 A[初始技能和验证基线] --> B[Rollout执行任务]
 B --> C[评测轨迹]
 C --> D[Reflector总结模式]
 D --> E[技能管理Agent修改技能]
 E --> F{验证分数提高?}
 F -->|是| G[接受新技能状态]
 F -->|否| H[保留旧状态并记录反馈]
 G --> B
 H --> B
```

项目提供SearchQA基线，包括数据集、执行环境和EM/F1评测。训练step的局部修改与epoch级合并/整理是不同阶段，验证门控用于降低无效更新，不保证在未知任务上都提升。

## 准备输入

在当前源码环境中，检查 `projects/skill_evolution/config.yaml`和 `agents/`中的模型配置。准备相互分离的train/val/test数据，以及含 `question_answering_skill/SKILL.md` 的初始技能库。

```json
[
  {
    "id": "example_001",
    "question": "Who wrote Pride and Prejudice?",
    "context": "Pride and Prejudice is a novel by Jane Austen.",
    "answers": ["Jane Austen"]
  }
]
```

`run.py`带有示例数据和结果路径。运行前必须修改 `SearchQADataset.data_path`、`init_local_skills_path`和`workdir`为实际路径，不能直接当成通用CLI参数。

```bash
cd projects/skill_evolution
python run.py
```

从项目目录运行可满足其本地模块导入。模型Key使用环境变量或本地配置，日志和技能内容不要包含凭据。用隔离技能目录和应用home测试，不直接修改日常使用的技能库。

## 结果与成本

检查每步rollout、评测、反思、接受/拒绝记录和最终技能状态，不只看训练集分数。验证集和测试集应保持独立，反复观察测试集再调参会影响结果解释。

并发数、轮次、模型选择和数据量都会影响费用。先做小样本基线，再扩大实验；这与安装/单模块测试不同，完整运行需要有预算的模型调用。

详见[项目说明](https://github.com/modelscope/ms-agent/blob/main/projects/skill_evolution/README_zh.md)。相关：[Skills](../core/skills.md)、[工作流](../core/workflows.md)。
