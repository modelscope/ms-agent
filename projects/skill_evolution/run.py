import asyncio

from tasks.base import BaseDataset, BaseEvaluator, BaseRolloutEnv
from skill_evolution_workflow import SkillEvolutionWorkflow


async def run_workflow(
    config_file: str,
    init_skills_path: str,
    workdir: str,
    train_set: BaseDataset,
    val_set: BaseDataset,
    test_set: BaseDataset,
    rollout_env: BaseRolloutEnv,
    evaluator: BaseEvaluator,
):
    skill_evolution_workflow = SkillEvolutionWorkflow(
        config_file=config_file,
        init_skills_path=init_skills_path,
        workdir=workdir,
    )
    await skill_evolution_workflow.run(
        train_set=train_set,
        val_set=val_set,
        test_set=test_set,
        rollout_env=rollout_env,
        evaluator=evaluator,
    )
    # import os
    # data_batch = train_set.get_batch(batch_size=10)
    # await skill_evolution_workflow._train_step(
    #     current_skills_path=init_skills_path,
    #     data_batch=data_batch,
    #     rollout_env=rollout_env,
    #     evaluator=evaluator,
    #     sub_workdir=os.path.join(workdir, "train_step")
    # )

if __name__ == "__main__":
    from tasks.searchqa import SearchQADataset, SearchQAEvaluator, SearchQARolloutEnv

    train_set = SearchQADataset(data_path="../../../data/minimal_searchqa_split/train/items.json", is_train=True)
    val_set = SearchQADataset(data_path="../../../data/minimal_searchqa_split/val/items.json", is_train=False)
    test_set = SearchQADataset(data_path="../../../data/minimal_searchqa_split/test/items.json", is_train=False)
    rollout_env = SearchQARolloutEnv()
    evaluator = SearchQAEvaluator()

    config_file = "./config.yaml"

    coroutine = run_workflow(
        config_file=config_file,
        init_skills_path="../../../results/msagent_searchqa_qwen36flash/init_skills",
        workdir="../../../results/msagent_searchqa_qwen36flash/workdir",
        train_set=train_set,
        val_set=val_set,
        test_set=test_set,
        rollout_env=rollout_env,
        evaluator=evaluator,
    )
    asyncio.run(coroutine)
