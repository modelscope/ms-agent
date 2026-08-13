# **Skill Evolution**

[中文版](README_zh.md)

Skill Evolution is a signal-driven workflow for improving an agent's local skill library through rollout, evaluation, reflection, and skill management. It is designed for tasks where the agent can be evaluated automatically and where reusable task-solving knowledge can be represented as MS-Agent skills.

The current project includes a complete baseline implementation for **SearchQA**. SearchQA is used to validate the core evolution loop: run the agent with the current skills, score the trajectory, reflect on common success/failure patterns, update the relevant skills, and keep only skill changes that improve validation performance.

## 🌟 Features

- **Signal-Driven Skill Evolution** - Uses task rollouts and evaluator scores as optimization signals for iterative skill updates.
- **Reflection-Based Updates** - Groups successful and failed trajectories by viewed skills, then asks a reflector agent to identify common, generalizable patterns.
- **Micro and Macro Skill Management** - Performs step-level skill edits from reflection results and epoch-level library maintenance such as merging, compression, or deletion.
- **Validation-Gated State Updates** - Accepts a step update only when validation score improves over the previous accepted skill state; rejected updates are retained as negative context for future edits.
- **SearchQA Baseline** - Provides dataset, rollout environment, and exact-match/F1 evaluator implementations for question answering over supplied context.
- **Concurrent Async Execution** - Runs rollout and evaluation batches with semaphore-controlled concurrency.
- **State Safety** - Uses isolated configuration hydration, preserves rollout-result alignment on failures, and clears trajectory buffers after reflection to reduce state leakage and overfitting.

## 📋 Architecture

```text
                 ┌────────────────────┐
                 │  Initial Skills    │
                 └─────────┬──────────┘
                           │
                           ▼
                 ┌────────────────────┐
                 │ Validation Baseline│
                 └─────────┬──────────┘
                           │
          ┌────────────────┴────────────────┐
          ▼                                 ▼
┌──────────────────┐              ┌──────────────────┐
│ Rollout Agent    │              │ Task Evaluator   │
│ + current skills │─────────────▶│ score trajectory │
└────────┬─────────┘              └────────┬─────────┘
         │                                 │
         ▼                                 ▼
┌──────────────────┐              ┌──────────────────┐
│ Reflector Agent  │─────────────▶│ Micro Skill Mgr  │
│ common patterns  │              │ create/edit      │
└──────────────────┘              └────────┬─────────┘
                                           │
                                           ▼
                                  ┌──────────────────┐
                                  │ Validation Gate  │
                                  │ accept/reject    │
                                  └────────┬─────────┘
                                           │
                                           ▼
                                  ┌──────────────────┐
                                  │ Macro Skill Mgr  │
                                  │ epoch cleanup    │
                                  └──────────────────┘
```

### Main Components

- `skill_evolution_workflow.py` - The core asynchronous evolution loop. It handles initialization, rollout, evaluation, reflection, skill updates, validation gating, macro skill management, and final testing.
- `run.py` - Example entry point using the SearchQA task.
- `config.yaml` - Workflow-level training and agent configuration.
- `agents/rollout.yaml` - Agent used to solve task items with the current skill library.
- `agents/reflector.yaml` - Agent that extracts common patterns from successful or failed trajectories.
- `agents/micro_skill_manager.yaml` - Agent that creates or edits skills based on reflection output.
- `agents/macro_skill_manager.yaml` - Agent that inspects the whole skill library after each epoch and performs structural maintenance.
- `tasks/base.py` - Abstract interfaces for datasets, rollout environments, and evaluators.
- `tasks/searchqa.py` - SearchQA dataset loader, rollout environment, and evaluator.
- `utils.py` - Async orchestration and evaluation logging utilities.

## 🛠️ Installation

Run from the `ms-agent` repository root.

```bash
git clone https://github.com/modelscope/ms-agent.git
cd ms-agent

conda create -n skill_evolution python=3.11
conda activate skill_evolution

# From PyPI
pip install 'ms-agent'

# Or from source
pip install -e .
```

Configure an OpenAI-compatible model endpoint. The default YAML files use DashScope-compatible settings and leave the key empty.

```bash
export OPENAI_API_KEY=your_api_key
export OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

You can also set `llm.openai_api_key`, `llm.openai_base_url`, and `llm.model` directly in the files under `agents/`.

## 🚀 Quickstart

### 1. Prepare SearchQA Data

The example in `run.py` expects three JSON files:

```text
/path/to/data/minimal_searchqa_split/
├── train/items.json
├── val/items.json
└── test/items.json
```

Each `items.json` file should contain a list of items:

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

If your data is stored elsewhere, edit the dataset paths in `run.py`.

### 2. Prepare Initial Skills

Provide an initial local skill directory and update `init_local_skills_path` in `run.py`.

```text
init_skills/
└── question_answering_skill/
    └── SKILL.md
```

The SearchQA rollout environment first asks the agent to check `question_answering_skill`, so the initial skill library should include a relevant QA skill. The workflow also automatically includes `~/.ms_agent/skills` when that directory exists.

### 3. Configure Training

Edit `config.yaml` to control the evolution loop:

```yaml
train:
  num_epochs: 1
  batch_size: 40
  max_workers: 10
  reflection_trigger_size: 1
  reflection_group_size: 4
  rejected_update_buffer_size: 3
```

- `num_epochs` - Number of passes over the training set.
- `batch_size` - Number of training items per evolution step.
- `max_workers` - Maximum concurrent rollout/evaluation tasks.
- `reflection_trigger_size` - Minimum buffered trajectories for a viewed-skill group before reflection.
- `reflection_group_size` - Number of trajectories bundled into one reflection query.
- `rejected_update_buffer_size` - Number of recent rejected updates retained per viewed-skill group.

### 4. Run the Workflow

From `projects/skill_evolution`:

```bash
cd projects/skill_evolution
python run.py
```

`run.py` uses local relative paths for data and outputs. For a new experiment, update these values first:

```python
train_set = SearchQADataset(data_path="/path/to/train/items.json", is_train=True)
val_set = SearchQADataset(data_path="/path/to/val/items.json", is_train=False)
test_set = SearchQADataset(data_path="/path/to/test/items.json", is_train=False)

init_local_skills_path = "/path/to/init_skills"
workdir = "/path/to/workdir"
```

## 📁 Output Structure

Each run writes intermediate skills, rollouts, evaluation files, reflection outputs, and skill-manager outputs under `workdir`.

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

The final test compares:

- **Initial Skills** - The original skill set.
- **Last Skills** - The final accepted skill state after training and macro management.
- **Best Skills** - The validation-best skill state observed during training.

## 🔧 Extending to New Tasks

To use the workflow for another task, implement the three interfaces in `tasks/base.py`:

1. **Dataset** - Subclass `BaseDataset` and return task-specific `BaseDataItem` objects from `load_data`.
2. **Rollout Environment** - Subclass `BaseRolloutEnv` and define how the agent interacts with one data item.
3. **Evaluator** - Subclass `BaseEvaluator` and return a `BaseEvaluationResult` with a scalar `score` and `success`/`failure` status.

Then instantiate your dataset, rollout environment, and evaluator in a script following `run.py`.

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

## Notes

- Skill updates are performed through MS-Agent skill tools. `micro_skill_manager` can create and edit skills; `macro_skill_manager` can create, edit, and delete skills.
- The validation gate compares against the previous accepted score. A rejected update is not used as the next training state, and its update details can be fed back to avoid repeated mistakes.
- Rollout failures are converted into dummy failed evaluations while preserving batch alignment, so a single failed rollout does not corrupt the mapping between data items and results.
