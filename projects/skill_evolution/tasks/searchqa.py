import json
import os
import string
import re
from collections import Counter
from dataclasses import dataclass
from typing import List, Optional

from ms_agent.agent import Agent
from ms_agent.llm import Message
from ms_agent.utils import logger

from .base import (
    BaseDataItem, BaseDataset, BaseEvaluationResult, BaseEvaluator, BaseRolloutEnv
)

logger = logger.get_logger(__name__)


@dataclass
class SearchQADataItem(BaseDataItem):
    """Data item for SearchQA task."""

    answers: List[str]


@dataclass
class SearchQAEvaluationResult(BaseEvaluationResult):
    """Evaluation result for SearchQA task."""

    f1_score: float
    prediction: str
    answers: List[str]


class SearchQADataset(BaseDataset):

    SYSTEM_PROMPT = (
        "You are an expert question answering assistant.\n\n"
        "# Task Format\nYou will receive a CONTEXT containing document passages and a QUESTION.\n"
        "Read the context carefully and answer the question based on the information provided.\n\n"
        "# Answer Format\nThink step by step, then provide your final answer inside <answer>...</answer> tags.\n"
        "Keep your answer concise — typically a few words or a short phrase.\n"
        "Do not repeat the question. Do not include unnecessary explanation in the answer tags.\n\n"
        "Example:\n<answer>Abraham Lincoln</answer>"
    )

    def load_data(self, data_path: str) -> List[SearchQADataItem]:
        """Load SearchQA data from the specified path."""
        # check if data_path is ends with .json
        if not data_path.endswith(".json"):
            raise ValueError(f"Expected a .json file for SearchQA dataset, got: {data_path}")

        with open(data_path, encoding="utf-8") as f:
            data = json.load(f)
        
        data_items = []
        for item in data:
            question, context = item["question"], item["context"]
            query = f"## Context\n{context}\n\n## Question\n{question}"
            data_item = SearchQADataItem(
                id=item["id"],
                system=self.SYSTEM_PROMPT,
                query=query,
                answers=item["answers"]
            )
            data_items.append(data_item)
        logger.info(f"Loaded {len(data_items)} items from {data_path}")
        return data_items


class SearchQAEvaluator(BaseEvaluator):

    # adapted from https://github.com/microsoft/SkillOpt/blob/9969a8f393f3b5ece29715e6e5b07deb5be90741/skillopt/envs/searchqa/evaluator.py
    
    def _normalize_answer(self, answer: str) -> str:
        """Normalize answer string (SQuAD convention)."""
        answer = answer.lower()
        answer = "".join(ch for ch in answer if ch not in string.punctuation)
        answer = re.sub(r"\b(a|an|the)\b", " ", answer)
        answer = " ".join(answer.split())
        return answer.strip()

    def _extract_answer(self, response: str) -> str:
        matches = re.findall(r"<answer>(.*?)</answer>", response, re.DOTALL | re.IGNORECASE)
        if matches:
            return matches[-1].strip()
        lines = [ln.strip() for ln in response.strip().splitlines() if ln.strip()]
        if lines:
            return lines[-1]
        return response.strip()

    def _exact_match(self, prediction: str, gold_answers: List[str]) -> float:
        norm_pred = self._normalize_answer(prediction)
        for gold_answer in gold_answers:
            if self._normalize_answer(gold_answer) == norm_pred:
                return 1.0
        return 0.0

    def _f1_score(self, prediction: str, gold_answers: List[str]) -> float:
        """Token-level F1 (SQuAD-style), max across all gold answers."""
        norm_pred = self._normalize_answer(prediction)
        pred_tokens = norm_pred.split()

        if not pred_tokens:
            for gold_answer in gold_answers:
                if not self._normalize_answer(gold_answer).split():
                    return 1.0
            return 0.0

        best_f1 = 0.0
        for gold_answer in gold_answers:
            gold_tokens = self._normalize_answer(gold_answer).split()
            if not gold_tokens:
                continue
            common = Counter(pred_tokens) & Counter(gold_tokens)
            n_common = sum(common.values())
            if n_common == 0:
                continue
            precision = n_common / len(pred_tokens)
            recall = n_common / len(gold_tokens)
            f1 = 2 * precision * recall / (precision + recall)
            best_f1 = max(best_f1, f1)

        return best_f1

    async def evaluate(
        self,
        messages: List[Message],
        data_item: SearchQADataItem,
        evaluation_output_dir: Optional[str] = None
    ) -> SearchQAEvaluationResult:
        """Evaluate based on the interaction messages and the corresponding data item.

        Returns a BaseEvaluationResult instance containing the evaluation metrics.
        """
        # when messages[-1] is tool_call, messages[-1].content may be None
        response = messages[-1].content if messages and messages[-1].content else ""
        prediction = self._extract_answer(response)

        score = self._exact_match(prediction, data_item.answers)
        f1_score = self._f1_score(prediction, data_item.answers)

        evaluation_result = SearchQAEvaluationResult(
            messages=messages,
            score=score,
            status="success" if score > 0 else "failure",
            f1_score=f1_score,
            prediction=prediction,
            answers=data_item.answers
        )

        # save if evaluation_output_dir is provided
        if evaluation_output_dir:
            os.makedirs(evaluation_output_dir, exist_ok=True)
            output_path = os.path.join(evaluation_output_dir, f"{data_item.id}.json")
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(evaluation_result.to_dict(), f, ensure_ascii=False, indent=4)
        return evaluation_result


class SearchQARolloutEnv(BaseRolloutEnv):
    """Rollout environment for SearchQA task."""

    async def run(self, agent: Agent, data_item: SearchQADataItem) -> List[Message]:
        """Rollout the agent on a single data item and return the interaction messages."""
        messages = await agent.run("Please check the `question_answering_skill`")
        # for next query
        messages.append(Message(role="user", content=data_item.query))
        return await agent.run(messages)
