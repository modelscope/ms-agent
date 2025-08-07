import os
import shutil
from typing import Any, List, Optional

from ms_agent.utils import assert_package_exist
from omegaconf import DictConfig

from modelscope import snapshot_download
from ..llm import LLM, Message
from .base import RAG


class LlamaIndexRAG(RAG):
    """LlamaIndexRAG class to implement the RAG of llama-index

    The configuration needed in the config yaml:
        - name: LlamaIndexRAG
        - embedding: An embedding model, required, default `Qwen/Qwen3-Embedding-0.6B`
        - chunk_size: The chunk_size of splitting, default `512`
        - chunk_overlap: The overlap of each chunk, default `50`
        - retrieve_only: retrieve only will stop using the llm, only use embedding model,
            thus, query methods will not be available. Default `False`
        - storage_dir: The directory to store and load index files, default `./llama_index`
        If not retrieve_only, the llm model will be the same with the model configured in the `llm` fields.
    """

    def __init__(self, config: DictConfig):
        super().__init__(config)

        self._validate_config(config)
        self.embedding_model = getattr(config.rag, 'embedding',
                                       'Qwen/Qwen3-Embedding-0.6B')
        self.llm_model = getattr(config.rag, 'llm', None)
        self.chunk_size = getattr(config.rag, 'chunk_size', 512)
        self.chunk_overlap = getattr(config.rag, 'chunk_overlap', 50)
        self.retrieve_only = getattr(config.rag, 'retrieve_only', False)
        self.storage_dir = getattr(config.rag, 'storage_dir', './llama_index')
        self._validate_requirements()

        self._setup_embedding_model(config)

        from llama_index.core import Settings
        from llama_index.core.node_parser import SentenceSplitter
        # Set node parser
        Settings.node_parser = SentenceSplitter(
            chunk_size=self.chunk_size, chunk_overlap=self.chunk_overlap)

        # If retrieve only, don't set LLM
        if self.retrieve_only:
            Settings.llm = None
        else:
            from llama_index.core.llms import CustomLLM
            from llama_index.core.base.llms.types import LLMMetadata
            from llama_index.core.llms.callbacks import llm_completion_callback
            from llama_index.core.base.llms.types import CompletionResponse
            self._llm_instance = LLM.from_config(self.config)

            class MSCustomLLM(CustomLLM):

                @property
                def metadata(_self) -> LLMMetadata:
                    return LLMMetadata(
                        context_window=65536,  # TODO temp value
                        num_output=4096,
                        model_name=self.config.llm.model,
                    )

                @llm_completion_callback()
                def complete(_self, prompt: str,
                             **kwargs) -> CompletionResponse:
                    message: Message = self._llm_instance.generate(
                        messages=[Message(role='user', content=prompt)],
                        stream=False,
                        **kwargs)
                    return CompletionResponse(text=message.content)

                @llm_completion_callback()
                def stream_complete(_self,
                                    prompt: str,
                                    formatted: bool = False,
                                    **kwargs: Any):
                    for message in self._llm_instance.generate(
                            messages=[Message(role='user', content=prompt)],
                            stream=True,
                            **kwargs):
                        yield CompletionResponse(text=message.content)

            Settings.llm = MSCustomLLM()

        self.index = None
        self.query_engine = None

    def _validate_requirements(self):
        assert_package_exist(
            'llama_index',
            'Please install llama_index to support llama-index-rag:\n'
            '> pip install -U llama-index-core llama-index-embeddings-huggingface '
            'llama-index-llms-openai llama-index-llms-replicate\n')

    def _validate_config(self, config: DictConfig):
        """Validate configuration parameters"""
        if not hasattr(config, 'rag') or not hasattr(config.rag, 'embedding'):
            raise ValueError(
                'Missing rag.embedding parameter in configuration')

        chunk_size = getattr(config.rag, 'chunk_size', 512)
        if chunk_size <= 0:
            raise ValueError('chunk_size must be greater than 0')

    def _setup_embedding_model(self, config: DictConfig):
        from llama_index.core import (Settings)
        from llama_index.embeddings.huggingface import HuggingFaceEmbedding
        try:
            use_hf = getattr(config, 'use_huggingface', False)
            if not use_hf:
                self.embedding_model = snapshot_download(self.embedding_model)

            Settings.embed_model = HuggingFaceEmbedding(
                model_name=self.embedding_model, device='cpu')

        except Exception as e:
            raise RuntimeError(f'Failed to load embedding model: {e}')

    async def add_documents(self, documents: List[str]):
        if not documents:
            raise ValueError('Document list cannot be empty')
        from llama_index.core import (Document, VectorStoreIndex)
        docs = [Document(text=doc) for doc in documents]
        self.index = VectorStoreIndex.from_documents(docs)
        if not self.retrieve_only:
            await self._setup_query_engine()

    async def add_documents_from_files(self, file_paths: List[str]):
        if not file_paths:
            raise ValueError('File path list cannot be empty')

        from llama_index.core import VectorStoreIndex
        from llama_index.core.readers import SimpleDirectoryReader
        documents = []
        for file_path in file_paths:
            if not os.path.exists(file_path):
                raise ValueError(f'File {file_path} does not exist')

            if os.path.isfile(file_path):
                reader = SimpleDirectoryReader(input_files=[file_path])
            else:
                reader = SimpleDirectoryReader(input_dir=file_path)

            docs = reader.load_data()
            documents.extend(docs)

        self.index = VectorStoreIndex.from_documents(documents)

        if not self.retrieve_only:
            await self._setup_query_engine()

    async def _setup_query_engine(self):
        if self.index is None:
            return

        from llama_index.core import Settings
        # Check if LLM is set
        if Settings.llm is None and not self.retrieve_only:
            return

        self.query_engine = self.index.as_query_engine(
            similarity_top_k=5, response_mode='compact')

    async def _retrieve(self,
                        query: str,
                        limit: int = 5,
                        score_threshold: float = 0.0,
                        **filters) -> List[dict]:
        if self.index is None:
            return []

        if not query.strip():
            return []

        from llama_index.core.retrievers import VectorIndexRetriever
        retriever = VectorIndexRetriever(
            index=self.index, similarity_top_k=limit)

        nodes = retriever.retrieve(query)

        results = []
        for node in nodes:
            if node.score >= score_threshold:
                results.append({
                    'text': node.node.text,
                    'score': float(node.score),
                    'metadata': node.node.metadata,
                    'node_id': node.node.node_id
                })

        return results

    async def retrieve(self,
                       query: str,
                       limit: int = 5,
                       score_threshold: float = 0.0,
                       **filters) -> List[dict]:
        if self.retrieve_only:
            return await self._retrieve(query, limit, score_threshold,
                                        **filters)

        from llama_index.core import Settings
        from llama_index.core.postprocessor import SimilarityPostprocessor
        from llama_index.core.query_engine import RetrieverQueryEngine
        from llama_index.core.retrievers import VectorIndexRetriever
        if self.index is None or Settings.llm is None:
            return []

        retriever = VectorIndexRetriever(
            index=self.index, similarity_top_k=limit)

        postprocessor = SimilarityPostprocessor(
            similarity_cutoff=score_threshold)

        query_engine = RetrieverQueryEngine(
            retriever=retriever, node_postprocessors=[postprocessor])

        response = query_engine.query(query)

        results = []
        for node in response.source_nodes:
            results.append({
                'text': node.node.text,
                'score': float(node.score),
                'metadata': node.node.metadata,
                'node_id': node.node.node_id
            })

        return results

    async def hybrid_search(self, query: str, top_k: int = 5) -> List[dict]:
        """Hybrid retrieval: Vector retrieval + BM25"""
        if self.index is None:
            return []

        from llama_index.core.retrievers import VectorIndexRetriever
        # Try to import BM25 related modules
        try:
            from llama_index.retrievers.bm25 import BM25Retriever
            from llama_index.core.retrievers import QueryFusionRetriever
            bm25_available = True
        except ImportError:
            bm25_available = False

        # Vector retriever
        vector_retriever = VectorIndexRetriever(
            index=self.index, similarity_top_k=top_k)

        if not bm25_available:
            # Use vector retrieval only
            nodes = vector_retriever.retrieve(query)
        else:
            # Use hybrid retrieval
            try:
                bm25_retriever = BM25Retriever.from_defaults(
                    docstore=self.index.docstore, similarity_top_k=top_k)

                fusion_retriever = QueryFusionRetriever(
                    retrievers=[vector_retriever, bm25_retriever],
                    similarity_top_k=top_k,
                    num_queries=1)

                nodes = fusion_retriever.retrieve(query)

            except Exception:  # noqa
                nodes = vector_retriever.retrieve(query)

        results = []
        for node in nodes:
            results.append({
                'text': node.node.text,
                'score': float(node.score),
                'metadata': node.node.metadata,
                'node_id': node.node.node_id
            })

        return results

    async def query(self, query: str) -> str:
        if self.query_engine is None:
            if self.retrieve_only:
                raise ValueError(
                    'Current mode is retrieve only, question answering not supported'
                )
            else:
                raise ValueError(
                    'Query engine not initialized, please add documents and set LLM first'
                )

        try:
            response = self.query_engine.query(query)
            return str(response)
        except Exception as e:
            return f'Query failed, error: {e}'

    async def save_index(self, persist_dir: Optional[str] = None):
        """Save index"""
        if self.index is None:
            raise ValueError('No index to save, please add documents first')

        save_dir = persist_dir or self.storage_dir

        os.makedirs(save_dir, exist_ok=True)
        self.index.storage_context.persist(persist_dir=save_dir)

    async def load_index(self, persist_dir: Optional[str] = None):
        """Load index"""
        load_dir = persist_dir or self.storage_dir

        if not os.path.exists(load_dir):
            raise FileNotFoundError(
                f'Index directory does not exist: {load_dir}')

        from llama_index.core import (StorageContext, load_index_from_storage)
        storage_context = StorageContext.from_defaults(persist_dir=load_dir)
        self.index = load_index_from_storage(storage_context)

        # Re-setup query engine
        if not self.retrieve_only:
            await self._setup_query_engine()

    def get_index_info(self) -> dict:
        """Get index information"""
        if self.index is None:
            return {'status': 'not_initialized'}

        doc_count = len(self.index.docstore.docs)
        return {
            'status': 'initialized',
            'document_count': doc_count,
            'retrieve_only': self.retrieve_only,
            'chunk_size': self.chunk_size,
            'chunk_overlap': self.chunk_overlap,
            'embedding_model': self.embedding_model
        }

    async def remove_all_documents(self):
        """Remove all documents from the index"""
        # Clear the index
        self.index = None

        # Clear the query engine
        self.query_engine = None

        # If storage directory exists, optionally clean it up
        if hasattr(self, 'storage_dir') and os.path.exists(self.storage_dir):
            shutil.rmtree(self.storage_dir, ignore_errors=True)
            os.makedirs(self.storage_dir, exist_ok=True)

    async def clear_storage(self, persist_dir: Optional[str] = None):
        """Clear the persistent storage directory"""
        clear_dir = persist_dir or self.storage_dir
        if os.path.exists(clear_dir):
            shutil.rmtree(clear_dir)
            os.makedirs(clear_dir, exist_ok=True)
