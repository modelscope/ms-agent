# Skill Evolution

Skill Evolution is a separate workflow that improves local skills from execution traces and evaluation signals. It targets tasks with automated evaluation, not universal self-improvement in ordinary conversations.

## Accept updates through validation

```{mermaid}
flowchart TD
 A[Initial skills and validation baseline] --> B[Run task rollouts]
 B --> C[Evaluate traces]
 C --> D[Reflector extracts patterns]
 D --> E[Skill manager edits skills]
 E --> F{Validation improves?}
 F -->|Yes| G[Accept new skill state]
 F -->|No| H[Keep previous state and feedback]
 G --> B
 H --> B
```

The project supplies a SearchQA baseline with datasets, rollout environment, and EM/F1 scoring. Step-level edits differ from epoch-level consolidation. Validation gates reduce ineffective updates; they do not guarantee generalization to unseen task families.

## Prepare inputs

In the source environment, inspect `projects/skill_evolution/config.yaml` and models in `agents/`. Prepare separate train/validation/test datasets and an initial skill library containing `question_answering_skill/SKILL.md`.

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

`run.py` contains example data/result paths. Update `SearchQADataset.data_path`, `init_local_skills_path`, and `workdir` before running; these are not generic CLI arguments.

```bash
cd projects/skill_evolution
python run.py
```

Run from the project directory for its local imports. Keep credentials in environment/local configuration, not traces or skill text. Use isolated skills and application-home directories rather than modifying your everyday library.

## Results and cost

Inspect rollouts, evaluation, reflection, accept/reject records, and final skill state—not only training scores. Keep validation/test splits separate; repeated tuning against the test set changes how results can be interpreted.

Concurrency, epochs, models, and dataset size affect cost. Start with a small baseline before scaling. Full experiments require budgeted model calls and are different from installation or unit tests.

See the [project guide](https://github.com/modelscope/ms-agent/blob/main/projects/skill_evolution/README.md). Related: [Skills](../core/skills.md), [Workflows](../core/workflows.md).
