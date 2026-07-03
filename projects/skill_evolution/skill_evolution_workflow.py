import asyncio
import json
import os
import re
import shutil
from collections import defaultdict, deque
from typing import Deque, Dict, List

from omegaconf import DictConfig

from ms_agent.config import Config
from ms_agent.agent.loader import AgentLoader
from ms_agent.llm import Message
from ms_agent.utils import get_logger

from tasks.base import (
    BaseDataItem, BaseDataset, BaseEvaluationResult, BaseEvaluator, BaseRolloutEnv
)
from utils import (
    collect_and_log_evaluation_results,
    format_evaluation_result,
    gather_with_semaphore
)

logger = get_logger(__name__)


class SkillEvolutionWorkflow:
    """Workflow for skill evolution.

    Args:
        config_file (str): Path to the configuration file.
        init_skills_path (str): Path to the initial skills directory.
        trust_remote_code (bool): Whether to allow loading of remote code. Defaults to False.
        workdir (str): Working directory for the workflow. Defaults to `./output`.
    """
    SKILL_VIEW_TOOL_NAME = "skills---skill_view"

    WORKFLOW_NAME = "SkillEvolutionWorkflow"

    def __init__(
        self,
        config_file: str,
        init_skills_path: str,
        workdir: str = "./output",
    ):
        # prepare config
        self.config = Config.from_task(config_file)
        self.agents_config = self.config.get("agents", DictConfig({}))
        self.train_config = self.config.get("train", DictConfig({}))
        self.init_skills_path = init_skills_path
        self.workdir = workdir

        # prepare detailed training config
        self.train_config.num_epochs = self.train_config.get("num_epochs", 1)
        self.train_config.batch_size = self.train_config.get("batch_size", 10)
        self.train_config.max_workers = self.train_config.get("max_workers", 1)
        self.train_config.reflection_trigger_size = self.train_config.get("reflection_trigger_size", 2)
        self.train_config.reflection_group_size = self.train_config.get("reflection_group_size", 4)
        self.train_config.rejected_update_buffer_size = self.train_config.get("rejected_update_buffer_size", 3)

        # prepare runtime
        self._prepare_agents()
        self.semaphore = asyncio.Semaphore(self.train_config.max_workers)
        # {viewed_skills: {status: [trajectories in string]}}
        self.trajectories_buffer: Dict[str, Dict[str, List[str]]] = defaultdict(lambda: defaultdict(list))
        # {viewed_skills: deque of rejected updates in string}
        self.recent_rejected_update_buffer: Dict[str, Deque[str]] = defaultdict(
            lambda: deque(maxlen=self.train_config.rejected_update_buffer_size)
        )

    def _prepare_agents(self):
        """Prepare the configurations for different agents used in the workflow."""
        self.rollout_agent_config = self._get_agent_config("rollout")
        self.reflector_agent_config = self._get_agent_config("reflector")
        self.micro_skill_manager_agent_config = self._get_agent_config("micro_skill_manager")
        self.macro_skill_manager_agent_config = self._get_agent_config("macro_skill_manager")

    def _get_agent_config(self, agent_name: str) -> DictConfig:
        """Get the configuration for agents.

        Args:
            agent_name (str): The name of the agent.

        Returns:
            DictConfig: The configuration for agents.
        """
        if agent_name not in self.agents_config:
            raise ValueError(f"Agent {agent_name} not found in configuration.")

        agent_config = self.agents_config[agent_name].get("agent_config")
        if isinstance(agent_config, str):
            return Config.from_task(os.path.join(self.config.local_dir, agent_config))
        else:
            return agent_config

    async def _build_and_run_rollout_agent(
        self,
        current_skills_path: str,
        data_item: BaseDataItem,
        rollout_env: BaseRolloutEnv,
        rollout_output_dir: str,
    ) -> List[Message]:
        """Build and run the rollout agent for a given data item."""
        # inject prompt config and skills config into rollout agent config
        rollout_agent_config = self.rollout_agent_config.copy()
        rollout_agent_config["prompt"] = {
            "system": data_item.system
        }
        rollout_agent_config["skills"].update({
            "path": current_skills_path,
        })
        rollout_agent_config["output_dir"] = rollout_output_dir
        # build and run
        agent = AgentLoader.build(
            config=rollout_agent_config,
            tag="rollout_agent",
        )
        outputs = await rollout_env.run(agent, data_item)
        return outputs

    async def _build_and_run_reflector_agent(
        self,
        query: str,
        reflector_output_dir: str
    ) -> List[Message]:
        """Build and run the reflector agent for a given query."""
        reflector_agent_config = self.reflector_agent_config.copy()
        reflector_agent_config["output_dir"] = reflector_output_dir
        # build and run
        agent = AgentLoader.build(
            config=reflector_agent_config,
            tag="reflector_agent",
        )
        outputs = await agent.run(query)
        return outputs

    async def _build_and_run_skill_manager_agent(
        self,
        agent_config: DictConfig,
        current_skills_path: str,
        query: str,
        skill_manager_output_dir: str
    ) -> List[Message]:
        """Build and run the skill manager agent for a given query."""
        # inject skills config into skill manager agent config
        skill_manager_agent_config = agent_config.copy()
        skill_manager_agent_config["skills"].update({
            "path": current_skills_path,
        })
        skill_manager_agent_config["output_dir"] = skill_manager_output_dir
        # build and run
        agent = AgentLoader.build(
            config=skill_manager_agent_config,
            tag="skill_manager_agent",
        )
        outputs = await agent.run(query)
        return outputs

    async def run(
        self,
        train_set: BaseDataset,
        val_set: BaseDataset,
        test_set: BaseDataset,
        rollout_env: BaseRolloutEnv,
        evaluator: BaseEvaluator,
    ):
        """Run the skill evolution workflow.

        Args:
            train_set (BaseDataset): Training dataset.
            val_set (BaseDataset): Validation dataset.
            test_set (BaseDataset): Test dataset.
            rollout_env (BaseRolloutEnv): Environment for conducting rollouts.
            evaluator (BaseEvaluator): Evaluator for assessing model performance.
        """
        # initial validation
        # init skills are copied to workdir/init/skills, rollout results are saved to workdir/init/rollout_results
        sub_workdir = os.path.join(self.workdir, "init")
        os.makedirs(sub_workdir, exist_ok=True)
        current_skills_path = os.path.join(sub_workdir, "skills")
        shutil.copytree(self.init_skills_path, current_skills_path, dirs_exist_ok=True)

        current_score = await self._validate_or_test(
            current_skills_path=current_skills_path,
            val_test_set=val_set,
            rollout_env=rollout_env,
            evaluator=evaluator,
            sub_workdir=sub_workdir,
        )

        best_skills_path, best_score = current_skills_path, current_score
        last_skills_path, last_score = current_skills_path, current_score

        # training loop
        num_steps = (len(train_set) + self.train_config.batch_size - 1) // self.train_config.batch_size
        for epoch in range(1, self.train_config.num_epochs + 1):
            for step in range(1, num_steps + 1):
                sub_workdir = os.path.join(self.workdir, f"epoch_{epoch:02d}", f"step_{step:04d}")
                os.makedirs(sub_workdir, exist_ok=True)
                current_skills_path = os.path.join(sub_workdir, "skills")
                shutil.copytree(last_skills_path, current_skills_path, dirs_exist_ok=True)

                # a train step consists of rollout, evaluation, reflection and skill management
                data_batch = train_set.get_batch(self.train_config.batch_size)
                await self._train_step(
                    current_skills_path=current_skills_path,
                    data_batch=data_batch,
                    rollout_env=rollout_env,
                    evaluator=evaluator,
                    sub_workdir=os.path.join(sub_workdir, "train_step"),
                    step_num=step
                )

                current_score = await self._validate_or_test(
                    current_skills_path=current_skills_path,
                    val_test_set=val_set,
                    rollout_env=rollout_env,
                    evaluator=evaluator,
                    sub_workdir=os.path.join(sub_workdir, "validation"),
                )

                # accept: update best skills if current score is better
                if current_score > best_score:
                    best_score = current_score
                    best_skills_path = current_skills_path
                    logger.info(f"New best skills found at {best_skills_path} with score {best_score:.4f}")
                # accept: update last skills if current score is better
                if current_score > last_score:
                    last_score = current_score
                    last_skills_path = current_skills_path
                    logger.info(f"Updated last skills at {last_skills_path} with score {last_score:.4f}")
                # reject: if current score is worse than last score, we will reject the current skills
                # and update the recent rejected update buffer for the corresponding viewed skills
                else:
                    # TODO
                    pass

            # after all steps in the epoch, we will call marco_skill_manager
            # to examine the entire skill set and decide whether to merge or remove skills
            sub_workdir = os.path.join(self.workdir, f"epoch_{epoch:02d}", f"step_final")
            os.makedirs(sub_workdir, exist_ok=True)
            current_skills_path = os.path.join(sub_workdir, "skills")
            shutil.copytree(last_skills_path, current_skills_path, dirs_exist_ok=True)

            # build and run macro skill manager agent
            # TODO

            current_score = await self._validate_or_test(
                current_skills_path=current_skills_path,
                val_test_set=val_set,
                rollout_env=rollout_env,
                evaluator=evaluator,
                sub_workdir=sub_workdir,
            )

            # update best skills if current score is better
            if current_score > best_score:
                best_score = current_score
                best_skills_path = current_skills_path
                logger.info(f"New best skills found at {best_skills_path} with score {best_score:.4f}")
            # force update last skills to the current skills after macro skill management
            last_skills_path, last_score = current_skills_path, current_score

        # final test
        # 1. init skills
        test_init_workdir = os.path.join(self.workdir, "test", "init")
        os.makedirs(test_init_workdir, exist_ok=True)
        test_init_skills_path = os.path.join(test_init_workdir, "skills")
        shutil.copytree(self.init_skills_path, test_init_skills_path, dirs_exist_ok=True)
        logger.info(f"Testing with initial skills from {test_init_skills_path}")

        test_init_score = await self._validate_or_test(
            current_skills_path=test_init_skills_path,
            val_test_set=test_set,
            rollout_env=rollout_env,
            evaluator=evaluator,
            sub_workdir=test_init_workdir,
        )

        # 2. last skills
        test_last_workdir = os.path.join(self.workdir, "test", "last")
        os.makedirs(test_last_workdir, exist_ok=True)
        test_last_skills_path = os.path.join(test_last_workdir, "skills")
        shutil.copytree(last_skills_path, test_last_skills_path, dirs_exist_ok=True)
        logger.info(f"Testing with last skills from {test_last_skills_path}")

        test_last_score = await self._validate_or_test(
            current_skills_path=test_last_skills_path,
            val_test_set=test_set,
            rollout_env=rollout_env,
            evaluator=evaluator,
            sub_workdir=test_last_workdir,
        )

        # 3. best skills
        test_best_workdir = os.path.join(self.workdir, "test", "best")
        os.makedirs(test_best_workdir, exist_ok=True)
        test_best_skills_path = os.path.join(test_best_workdir, "skills")
        shutil.copytree(best_skills_path, test_best_skills_path, dirs_exist_ok=True)
        logger.info(f"Testing with best skills from {test_best_skills_path}")

        test_best_score = await self._validate_or_test(
            current_skills_path=test_best_skills_path,
            val_test_set=test_set,
            rollout_env=rollout_env,
            evaluator=evaluator,
            sub_workdir=test_best_workdir,
        )

        # 4. log final results
        logger.info(f"Test Results:\n"
                    f"Initial Skills Score: {test_init_score:.4f} (from {test_init_skills_path})\n"
                    f"Last Skills Score: {test_last_score:.4f} (from {test_last_skills_path})\n"
                    f"Best Skills Score: {test_best_score:.4f} (from {test_best_skills_path})")

    async def _rollout(
        self,
        current_skills_path: str,
        data_batch: List[BaseDataItem],
        rollout_env: BaseRolloutEnv,
        rollout_output_dir: str,
    ) -> List[List[Message]]:
        """Rollout the current skills on a batch of data items.

        Args:
            current_skills_path (str): Path to the current skills directory.
            data_batch (list[BaseDataItem]): A batch of data items to rollout.
            rollout_env (BaseRolloutEnv): Environment for conducting rollouts.
            rollout_output_dir (str): Directory to save rollout results.

        Returns:
            list: A list of rollout results for each data item in the batch.
        """
        os.makedirs(rollout_output_dir, exist_ok=True)
        coroutines = [
            self._build_and_run_rollout_agent(
                current_skills_path=current_skills_path,
                data_item=data_item,
                rollout_env=rollout_env,
                rollout_output_dir=os.path.join(rollout_output_dir, data_item.id)
            )
            for data_item in data_batch
        ]
        return await gather_with_semaphore(self.semaphore, coroutines)
            
    async def _evaluate(
        self,
        data_batch: List[BaseDataItem],
        rollout_results: List[List[Message]],
        evaluator: BaseEvaluator,
        evaluation_output_dir: str
    ) -> List[BaseEvaluationResult]:
        """Evaluate the rollout results for a batch of data items.

        Args:
            data_batch (list[BaseDataItem]): A batch of data items.
            rollout_results (list): Rollout results corresponding to the data items.
            evaluator (BaseEvaluator): Evaluator for assessing model performance.
            evaluation_output_dir (str): Directory to save evaluation results.

        Returns:
            list: A list of evaluation results for each data item in the batch.
        """
        os.makedirs(evaluation_output_dir, exist_ok=True)
        coroutines = [
            evaluator.evaluate(messages, data_item, evaluation_output_dir)
            for messages, data_item in zip(rollout_results, data_batch)
        ]
        evaluation_results = await gather_with_semaphore(self.semaphore, coroutines)
        return evaluation_results

    async def _reflect(
        self,
        viewed_skills_queries: Dict[str, list[str]],
        reflector_output_dir: str
    ) -> Dict[str, list[str]]:
        """Reflect on the viewed skills and their corresponding queries.

        Args:
            viewed_skills_queries (dict): A dictionary mapping viewed skills to their corresponding queries.
            reflector_output_dir (str): Directory to save reflection results.

        Returns:
            dict: A dictionary mapping viewed skills to their corresponding reflection results.
        """
        os.makedirs(reflector_output_dir, exist_ok=True)
        reflection_results = dict()
        for viewed_skills, queries in viewed_skills_queries.items():
            coroutines = [
                self._build_and_run_reflector_agent(
                    query=query,
                    reflector_output_dir=os.path.join(reflector_output_dir, viewed_skills, f"group_{i:04d}")
                )
                for i, query in enumerate(queries)
            ]
            results = await gather_with_semaphore(self.semaphore, coroutines)
            results = [messages[-1].content for messages in results]
            reflection_results[viewed_skills] = results
        return reflection_results

    async def _micro_skill_manage(
        self,
        current_skills_path: str,
        micro_skill_manage_queries: Dict[str, str],
        micro_skill_manager_output_dir: str
    ):
        """Perform micro skill management at each step based on the reflection results.

        Args:
            micro_skill_manage_queries (dict): A dictionary mapping viewed skills to their corresponding management queries.
            micro_skill_manager_output_dir (str): Directory to save micro skill management results.
        """
        os.makedirs(micro_skill_manager_output_dir, exist_ok=True)
        coroutines = [
            self._build_and_run_skill_manager_agent(
                agent_config=self.micro_skill_manager_agent_config,
                current_skills_path=current_skills_path,
                query=query,
                skill_manager_output_dir=os.path.join(micro_skill_manager_output_dir, viewed_skills)
            )
            for viewed_skills, query in micro_skill_manage_queries.items()
        ]
        await gather_with_semaphore(self.semaphore, coroutines)

    def _extract_viewed_skills_from_messages(self, messages: List[Message]) -> str:
        """Extract the set of viewed skills from the rollout messages.

        Args:
            messages (list[Message]): Rollout messages.

        Returns:
            str: A string representation of the viewed skill ids, sorted and joined by underscores.
        """
        viewed_skills = set()
        for message in messages:
            tool_calls = message.tool_calls
            if not tool_calls:
                continue
            for tool_call in tool_calls:
                if tool_call.get("tool_name", "") == self.SKILL_VIEW_TOOL_NAME:
                    try:
                        skill_id = json.loads(tool_call["arguments"])["skill_id"]
                        viewed_skills.add(skill_id)
                    except Exception as e:
                        logger.warning(f"Failed to extract skill_id from tool_call arguments: "
                                       f"{tool_call['arguments']}. Error: {e}")
                        continue
        # if there is no viewed skill, skills (always=true) work or no skill works
        if not viewed_skills:
            viewed_skills.add("always-or-no-skill")

        # return a string representation of the viewed skill ids, sorted and joined by underscores
        return re.sub(r"[^\w\-]", "_", "_".join(sorted(viewed_skills)))

    def _update_trajectories_buffer(
        self,
        evaluation_results: List[BaseEvaluationResult]
    ):
        """Update the trajectories buffer with the latest evaluation results.

        Args:
            evaluation_results (list[BaseEvaluationResult]): A list of evaluation results.
        """
        for evaluation_result in evaluation_results:
            messages = evaluation_result.messages
            viewed_skills = self._extract_viewed_skills_from_messages(messages)
            status = evaluation_result.status
            formatted_trajectories = format_evaluation_result(evaluation_result)
            # update the buffer
            self.trajectories_buffer[viewed_skills][status].append(formatted_trajectories)

    def _format_viewed_skills_queries(self) -> Dict[str, list[str]]:
        viewed_skills_queries = defaultdict(list)
        for status in ["success", "failure"]:
            for viewed_skills, status_dict in self.trajectories_buffer.items():
                trajectories = status_dict.get(status, [])
                if len(trajectories) < self.train_config.reflection_trigger_size:
                    continue
                # group trajectories into chunks of size reflection_group_size
                for i in range(0, len(trajectories), self.train_config.reflection_group_size):
                    end = min(i + self.train_config.reflection_group_size, len(trajectories))
                    group_trajectories = trajectories[i:end]
                    # format the group trajectories into a single query for reflection
                    query = "Trajectories:\n\n" + "\n\n---\n\n".join(group_trajectories)
                    viewed_skills_queries[viewed_skills].append(query)
        return viewed_skills_queries

    def _format_micro_skill_manage_queries(
        self,
        reflection_results: Dict[str, list[str]]
    ) -> Dict[str, str]:
        micro_skill_manage_queries = dict()
        for viewed_skills, reflections in reflection_results.items():
            # format the reflections into a single query for micro skill management
            query = "Reflections:\n" + "\n\n---\n\n".join(reflections)
            # add recent rejected updates to the query
            rejected_updates = list(self.recent_rejected_update_buffer[viewed_skills])
            if rejected_updates:
                rejected_updates_str = "\n\n---\n\n".join(rejected_updates)
                query += f"\n\nRecent Rejected Updates:\n{rejected_updates_str}"
            micro_skill_manage_queries[viewed_skills] = query
        return micro_skill_manage_queries

    async def _train_step(
        self,
        current_skills_path: str,
        data_batch: list[BaseDataItem],
        rollout_env: BaseRolloutEnv,
        evaluator: BaseEvaluator,
        sub_workdir: str,
        step_num: int = 0,
    ):
        """Perform a single training step consisting of rollout, evaluation, reflection, and skill management.

        Args:
            current_skills_path (str): Path to the current skills directory.
            data_batch (list[BaseDataItem]): A batch of data items for training.
            rollout_env (BaseRolloutEnv): Environment for conducting rollouts.
            evaluator (BaseEvaluator): Evaluator for assessing model performance.
            sub_workdir (str): Sub-directory within the working directory to save rollout and evaluation results.
            step_num (int): The current step number in the training loop. Defaults to 0.
        """
        # rollout
        rollout_results = await self._rollout(
            current_skills_path=current_skills_path,
            data_batch=data_batch,
            rollout_env=rollout_env,
            rollout_output_dir=os.path.join(sub_workdir, "rollout_results")
        )

        # evaluate
        evaluation_results = await self._evaluate(
            data_batch=data_batch,
            rollout_results=rollout_results,
            evaluator=evaluator,
            evaluation_output_dir=os.path.join(sub_workdir, "evaluation_results")
        )

        # collect and log
        collect_and_log_evaluation_results(
            evaluation_results=evaluation_results,
            context=f"Train Step {step_num:04d}"
        )

        # group, format trajectories and update trajectories buffer
        self._update_trajectories_buffer(evaluation_results)

        # build queries for reflection based on the trajectories buffer
        viewed_skills_queries = self._format_viewed_skills_queries()
        reflection_results = await self._reflect(
            viewed_skills_queries=viewed_skills_queries,
            reflector_output_dir=os.path.join(sub_workdir, "reflection_results")
        )

        # build and run micro skill manager agent
        micro_skill_manage_queries = self._format_micro_skill_manage_queries(reflection_results)
        await self._micro_skill_manage(
            current_skills_path=current_skills_path,
            micro_skill_manage_queries=micro_skill_manage_queries,
            micro_skill_manager_output_dir=os.path.join(sub_workdir, "micro_skill_manager_results")
        )

    async def _validate_or_test(
        self,
        current_skills_path: str,
        val_test_set: BaseDataset,
        rollout_env: BaseRolloutEnv,
        evaluator: BaseEvaluator,
        sub_workdir: str,
    ) -> float:
        """Validate or test the model with the current skills.

        Args:
            current_skills_path (str): Path to the current skills directory.
            val_test_set (BaseDataset): Validation or test dataset.
            rollout_env (BaseRolloutEnv): Environment for conducting rollouts.
            evaluator (BaseEvaluator): Evaluator for assessing model performance.
            sub_workdir (str): Sub-directory within the working directory to save rollout results.

        Returns:
            float: The average evaluation score across the dataset.
        """
        data_items = val_test_set.get_batch(len(val_test_set))
        # rollout
        rollout_results = await self._rollout(
            current_skills_path=current_skills_path,
            data_batch=data_items,
            rollout_env=rollout_env,
            rollout_output_dir=os.path.join(sub_workdir, "rollout_results")
        )
        # evaluate
        evaluation_results = await self._evaluate(
            data_batch=data_items,
            rollout_results=rollout_results,
            evaluator=evaluator,
            evaluation_output_dir=os.path.join(sub_workdir, "evaluation_results")
        )
        # collect and log
        avg_score = collect_and_log_evaluation_results(
            evaluation_results=evaluation_results,
            context=f"Validation/Test [{sub_workdir}]"
        )
        return avg_score
