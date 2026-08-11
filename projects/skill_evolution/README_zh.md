# **Skill Evolution**

[English](README.md)

Skill Evolution 是一个基于任务信号自动优化本地技能库的工作流。它适用于可以自动评测的任务：系统先用当前技能完成任务并生成轨迹，再根据评测结果反思成功/失败模式，最后由技能管理 Agent 更新技能，并通过验证集决定是否接受这次更新。

当前项目提供了完整的 **SearchQA** 基线实现，用于验证技能演化主流程：使用当前技能进行 rollout、计算评测分数、从轨迹中抽取共性模式、更新相关技能，并只保留能提升验证集表现的技能状态。

## 🌟 特性

- **基于信号的技能演化** - 使用任务 rollout 和 evaluator 分数作为优化信号，迭代改进技能库。
- **反思驱动更新** - 按被查看的技能对成功/失败轨迹分组，由 Reflector Agent 总结可泛化的共性模式。
- **微观与宏观技能管理** - 每个训练 step 基于反思结果创建或编辑技能；每个 epoch 末对整个技能库进行合并、压缩或删除等结构维护。
- **验证集门控** - 只有当验证分数超过上一个已接受状态时才接受 step 更新；被拒绝的更新会作为负面上下文，帮助后续更新避免重复错误。
- **SearchQA 基线** - 内置问答数据加载、rollout 环境，以及 exact match/F1 评测实现。
- **异步并发执行** - 使用 semaphore 控制并发，批量执行 rollout 和 evaluation。
- **状态安全** - 配置初始化使用深拷贝隔离状态；rollout 失败时保持结果索引对齐；反思后清空轨迹缓冲区，降低状态泄漏和过拟合风险。

## 📋 架构

```text
                 ┌────────────────────┐
                 │    初始技能库      │
                 └─────────┬──────────┘
                           │
                           ▼
                 ┌────────────────────┐
                 │   初始验证基线     │
                 └─────────┬──────────┘
                           │
          ┌────────────────┴────────────────┐
          ▼                                 ▼
┌──────────────────┐              ┌──────────────────┐
│ Rollout Agent    │              │ Task Evaluator   │
│ 使用当前技能     │─────────────▶│ 评测轨迹得分     │
└────────┬─────────┘              └────────┬─────────┘
         │                                 │
         ▼                                 ▼
┌──────────────────┐              ┌──────────────────┐
│ Reflector Agent  │─────────────▶│ Micro Skill Mgr  │
│ 总结共性模式     │              │ 创建/编辑技能    │
└──────────────────┘              └────────┬─────────┘
                                           │
                                           ▼
                                  ┌──────────────────┐
                                  │ Validation Gate  │
                                  │ 接受/拒绝更新    │
                                  └────────┬─────────┘
                                           │
                                           ▼
                                  ┌──────────────────┐
                                  │ Macro Skill Mgr  │
                                  │ epoch 级维护     │
                                  └──────────────────┘
```

### 主要组件

- `skill_evolution_workflow.py` - 核心异步演化流程，负责初始化、rollout、评测、反思、技能更新、验证门控、宏观技能管理和最终测试。
- `run.py` - 使用 SearchQA 任务的示例入口。
- `config.yaml` - 工作流级训练配置和 Agent 配置入口。
- `agents/rollout.yaml` - 使用当前技能库解决任务样本的 Agent。
- `agents/reflector.yaml` - 从成功/失败轨迹中抽取共性模式的 Agent。
- `agents/micro_skill_manager.yaml` - 根据反思结果创建或编辑技能的 Agent。
- `agents/macro_skill_manager.yaml` - 在每个 epoch 后检查整个技能库并做结构维护的 Agent。
- `tasks/base.py` - 数据集、rollout 环境、评测器的抽象接口。
- `tasks/searchqa.py` - SearchQA 数据加载、rollout 环境和评测器。
- `utils.py` - 异步编排和评测日志工具。

## 🛠️ 安装

在 `ms-agent` 仓库根目录执行：

```bash
git clone https://github.com/modelscope/ms-agent.git
cd ms-agent

conda create -n skill_evolution python=3.11
conda activate skill_evolution

# 从 PyPI 安装
pip install 'ms-agent'

# 或从源码安装
pip install -e .
```

配置 OpenAI 兼容模型服务。默认 YAML 使用 DashScope 兼容接口，并将 key 留空。

```bash
export OPENAI_API_KEY=your_api_key
export OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

也可以直接在 `agents/` 目录下的 YAML 文件中设置 `llm.openai_api_key`、`llm.openai_base_url` 和 `llm.model`。

## 🚀 快速开始

### 1. 准备 SearchQA 数据

`run.py` 示例默认读取以下三个 JSON 文件：

```text
/path/to/data/minimal_searchqa_split/
├── train/items.json
├── val/items.json
└── test/items.json
```

每个 `items.json` 是一个列表，格式如下：

```json
[
  {
    "id": "example_001",
    "question": "Who wrote Pride and Prejudice?",
    "context": "Pride and Prejudice is a novel by Jane Austen...",
    "answers": ["Jane Austen"]
  }
]
```

如果数据在其他目录，请修改 `run.py` 中的 dataset 路径。

### 2. 准备初始技能

准备一个初始本地技能目录，并修改 `run.py` 中的 `init_local_skills_path`。

```text
init_skills/
└── question_answering_skill/
    └── SKILL.md
```

SearchQA 的 rollout 环境会先要求 Agent 检查 `question_answering_skill`，因此初始技能库应包含一个相关的问答技能。工作流还会在 `~/.ms_agent/skills` 存在时自动加载该目录。

### 3. 配置训练参数

修改 `config.yaml` 控制演化循环：

```yaml
train:
  num_epochs: 1
  batch_size: 40
  max_workers: 10
  reflection_trigger_size: 1
  reflection_group_size: 4
  rejected_update_buffer_size: 3
```

- `num_epochs` - 遍历训练集的轮数。
- `batch_size` - 每个演化 step 使用的训练样本数。
- `max_workers` - rollout/evaluation 的最大并发数。
- `reflection_trigger_size` - 某个技能分组至少积累多少条轨迹后触发反思。
- `reflection_group_size` - 每次反思请求中打包的轨迹数量。
- `rejected_update_buffer_size` - 每个技能分组保留的最近被拒绝更新数量。

### 4. 运行工作流

在 `projects/skill_evolution` 目录执行：

```bash
cd projects/skill_evolution
python run.py
```

`run.py` 使用本地相对路径读取数据并写入输出。开始新实验前，建议先修改这些值：

```python
train_set = SearchQADataset(data_path="/path/to/train/items.json", is_train=True)
val_set = SearchQADataset(data_path="/path/to/val/items.json", is_train=False)
test_set = SearchQADataset(data_path="/path/to/test/items.json", is_train=False)

init_local_skills_path = "/path/to/init_skills"
workdir = "/path/to/workdir"
```

## 📁 输出目录

每次运行都会在 `workdir` 下写入中间技能、rollout 结果、评测文件、反思结果和技能管理结果。

```text
workdir/
├── init/
│   ├── skills/
│   ├── rollout_results/
│   └── evaluation_results/
├── epoch_01/
│   ├── step_0001/
│   │   ├── skills/
│   │   ├── train_step/
│   │   │   ├── rollout_results/
│   │   │   ├── evaluation_results/
│   │   │   ├── reflection_results/
│   │   │   └── micro_skill_manager_results/
│   │   └── validation/
│   └── step_final/
│       ├── skills/
│       └── macro_skill_manager/
└── test/
    ├── init/
    ├── last/
    └── best/
```

最终测试会比较三组技能：

- **Initial Skills** - 原始技能库。
- **Last Skills** - 训练和宏观管理后的最终技能状态。
- **Best Skills** - 训练过程中验证集表现最好的技能状态。

## 🔧 扩展到新任务

如需将工作流用于其他任务，实现 `tasks/base.py` 中的三个接口即可：

1. **Dataset** - 继承 `BaseDataset`，在 `load_data` 中返回任务专属的 `BaseDataItem`。
2. **Rollout Environment** - 继承 `BaseRolloutEnv`，定义 Agent 如何与单个样本交互。
3. **Evaluator** - 继承 `BaseEvaluator`，返回包含标量 `score` 和 `success`/`failure` 状态的 `BaseEvaluationResult`。

然后参考 `run.py` 实例化你的数据集、rollout 环境和评测器。

```python
workflow = SkillEvolutionWorkflow(
    config_file="projects/skill_evolution/config.yaml",
    init_local_skills_path="path/to/init_skills",
    workdir="path/to/workdir",
)

await workflow.run(
    train_set=train_set,
    val_set=val_set,
    test_set=test_set,
    rollout_env=rollout_env,
    evaluator=evaluator,
)
```

## 注意事项

- 技能更新通过 MS-Agent 的技能工具完成。`micro_skill_manager` 可以创建和编辑技能；`macro_skill_manager` 可以创建、编辑和删除技能。
- 验证门控会和上一个已接受分数比较。被拒绝的更新不会作为下一步训练状态，其更新细节可作为后续更新的反例上下文。
- rollout 失败会被转换成 dummy failed evaluation，同时保持 batch 索引对齐，避免单个失败样本破坏数据项与评测结果的映射。
