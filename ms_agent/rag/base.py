# Copyright (c) Alibaba, Inc. and its affiliates.
from abc import ABC, abstractmethod
from typing import Any, List


class RAG(ABC):
    """The base class for rags"""

    def __init__(self, config):
        self.config = config

    @abstractmethod
    async def add_documents(self, documents: List[str]) -> bool:
        """Add document to Rag

        Args:
            documents(`List[str]`): The content of the document

        Returns:
            success or not
        """
        pass

    @abstractmethod
    async def query(self, query: str) -> str:
        """Search documents

        Args:
            query(`str`): The query to search for
        Returns:
            The query result
        """
        pass

    @abstractmethod
    async def retrieve(self,
                       query: str,
                       limit: int = 5,
                       score_threshold: float = 0.7,
                       **filters) -> List[Any]:
        """Retrieve documents

        Args:
            query(`str`): The query to search for
            limit(`int`): The number of documents to return
            score_threshold(`float`): The score threshold
            **filters: Any extra filters

        Returns:
            List of documents
        """
        pass
