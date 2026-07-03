import asyncio
from typing import List

from ms_agent.utils import get_logger

from tasks.base import BaseEvaluationResult

logger = get_logger(__name__)


async def worker(semaphore: asyncio.Semaphore, coroutine):
    """A worker that runs a coroutine with a semaphore to limit concurrency."""
    async with semaphore:
        try:
            return await coroutine
        except Exception as e:
            logger.error(f"Error in worker: {e}", exc_info=True)
            return None


async def gather_with_semaphore(semaphore: asyncio.Semaphore, coroutines: List):
    """Gather results from coroutines with a semaphore to limit concurrency."""
    tasks = [worker(semaphore, coroutine) for coroutine in coroutines]
    results = await asyncio.gather(*tasks)
    filtered_results = [result for result in results if result is not None]
    return filtered_results


def collect_and_log_evaluation_results(
    evaluation_results: List[BaseEvaluationResult],
    context: str,
) -> float:
    """Collect and log the evaluation results.

    Args:
        evaluation_results (list[BaseEvaluationResult]): A list of evaluation results.
        context (str): Context for logging (e.g., "Train Step", "Validation", "Test").

    Returns:
        float: The average evaluation score across the dataset.
    """
    total_score, total_success = 0.0, 0
    for result in evaluation_results:
        total_score += result.score
        total_success += 1 if result.status == "success" else 0
    num_results = len(evaluation_results)
    
    avg_score = total_score / num_results if evaluation_results else 0.
    success_rate = total_success / num_results if evaluation_results else 0.
    logger.info(f"{context} Evaluation results: avg_score={avg_score:.4f}, "
                f"success_rate={success_rate:.2%} [{total_success}/{num_results}]")
    return avg_score


def format_evaluation_result(evaluation_result: BaseEvaluationResult) -> str:
    """Format the evaluation result into a string representation.

    Args:
        evaluation_result (BaseEvaluationResult): The evaluation result to format.

    Returns:
        str: A string representation of the evaluation result.
    """
    messages_str = "\n".join(f"{message.role}: {message.content}" for message in evaluation_result.messages)
    other_str = "\n".join(f"{key}: {value}" for key, value in evaluation_result.to_dict().items() if key != "messages")
    return f"{messages_str}\n\n{other_str}"
