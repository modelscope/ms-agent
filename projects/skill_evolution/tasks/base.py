import random
from abc import abstractmethod, ABC
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Literal, Optional

from ms_agent.agent import Agent
from ms_agent.llm import Message


@dataclass
class BaseDataItem(ABC):
    """Base class for data items used in tasks."""

    id: str
    system: Optional[str] = field(default=None, kw_only=True)
    query: str


@dataclass
class BaseEvaluationResult:
    """Base class for evaluation results."""

    messages: List[Message]
    score: float
    status: Literal["success", "failure"]

    def to_dict(self) -> Dict:
        return asdict(self)


class BaseDataset(ABC):
    """Base class for datasets used in tasks."""

    def __init__(self, data_path: str, is_train: bool = True):
        self.data_path = data_path
        self.is_train = is_train
        self.data = self.load_data(self.data_path)
        # shuffle if training data
        if self.is_train:
            random.shuffle(self.data)
        self.current_index = 0

    @abstractmethod
    def load_data(self) -> list[BaseDataItem]:
        """Load data from the specified path and return a list of BaseDataItem instances."""
        pass

    def __len__(self) -> int:
        return len(self.data)

    def __getitem__(self, index: int) -> BaseDataItem:
        return self.data[index]

    def get_batch(self, batch_size: int) -> list[BaseDataItem]:
        """Get a batch of data items."""
        if self.current_index + batch_size >= len(self.data):
            batch = self.data[self.current_index :]
            self.current_index = 0  # reset for next epoch
        else:
            batch = self.data[self.current_index : self.current_index + batch_size]
            self.current_index += batch_size
        return batch


class BaseEvaluator(ABC):

    @abstractmethod
    async def evaluate(
        self, 
        messages: List[Message], 
        data_item: BaseDataItem,
        evaluation_output_dir: Optional[str] = None
    ) -> BaseEvaluationResult:
        """Evaluate based on the interaction messages and the corresponding data item.

        Returns a BaseEvaluationResult instance containing the evaluation metrics.
        """
        pass


class BaseRolloutEnv(ABC):
    """Base class for rollout environments used in tasks."""

    @abstractmethod
    async def run(self, agent: Agent, data_item: BaseDataItem) -> List[Message]:
        """Rollout the agent on a single data item and return the interaction messages."""
        pass
