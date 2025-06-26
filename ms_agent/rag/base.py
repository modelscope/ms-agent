# Copyright (c) Alibaba, Inc. and its affiliates.
from abc import abstractmethod
from typing import Any, List

from ms_agent.llm import Message


class Rag:
    """The base class for rags"""

    def __init__(self, config):
        self.config = config

    @abstractmethod
    async def add_document(self, url: str, content: str, **metadata) -> bool:
        """Add document to Rag

        Args:
            url(`str`): The url of the document
            content(`str`): The content of the document
            **metadata: Metadata information

        Returns:
            success or not
        """
        pass

    @abstractmethod
    async def search_documents(self,
                               query: str,
                               limit: int = 5,
                               score_threshold: float = 0.7,
                               **filters) -> List[Any]:
        """Search documents in Rag

        Args:
            query(`str`): The query to search for
            limit(`int`): The number of documents to return
            score_threshold(`float`): The score threshold
            **filters: Any extra filters

        Returns:
            List of documents
        """
        pass

    @abstractmethod
    async def delete_document(self, url: str) -> bool:
        """Delete document from Rag

        Args:
            url(`str`): The url of the document

        Returns:
            bool: True if the document was successfully deleted
        """
        pass

    @abstractmethod
    async def run(self, inputs: List[Message]) -> List[Message]:
        pass
