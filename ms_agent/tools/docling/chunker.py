from typing import Iterable, Iterator, List

from docling_core.transforms.chunker import BaseChunk, DocChunk
from docling_core.transforms.chunker.hierarchical_chunker import (
    ChunkingDocSerializer, ChunkingSerializerProvider)
from docling_core.transforms.chunker.hybrid_chunker import HybridChunker
from docling_core.transforms.chunker.tokenizer.base import BaseTokenizer
from docling_core.transforms.chunker.tokenizer.huggingface import \
    HuggingFaceTokenizer
from docling_core.transforms.serializer.markdown import MarkdownParams
from docling_core.types import DoclingDocument
from docling_core.types.doc import DocItemLabel
from ms_agent.utils.logger import get_logger
from rich.console import Console
from rich.panel import Panel

from modelscope import AutoTokenizer

logger = get_logger()

console = Console(
    width=200,  # for getting Markdown tables rendered nicely
)


class ImgPlaceholderSerializerProvider(ChunkingSerializerProvider):

    def get_serializer(self, doc):
        return ChunkingDocSerializer(
            doc=doc,
            params=MarkdownParams(image_placeholder='<!-- image -->', ),
        )


# TODO: Add Table Serializer


class HybridDocumentChunker:

    EMBED_MODEL_ID = 'sentence-transformers/all-MiniLM-L6-v2'
    MAX_TOKENS = 1024

    def __init__(self,
                 embed_model_id: str = EMBED_MODEL_ID,
                 max_tokens: int = MAX_TOKENS):
        """
        Hybrid chunker that splits interleaved picture, table, and text into chunks.

        """

        self.tokenizer: BaseTokenizer = HuggingFaceTokenizer(
            tokenizer=AutoTokenizer.from_pretrained(embed_model_id),
            max_tokens=max_tokens,
        )

        # TODO: for test1
        # self.chunker = HybridChunker(tokenizer=self.tokenizer)

        self.chunker = HybridChunker(
            tokenizer=self.tokenizer,
            serializer_provider=ImgPlaceholderSerializerProvider(),
        )

        logger.info(
            f'Hybrid chunker initialized with tokenizer {embed_model_id}, max_tokens={self.tokenizer.get_max_tokens()}'
        )

    @staticmethod
    def find_n_th_chunk_with_label(
            chunks: List[BaseChunk], n: int,
            label: DocItemLabel) -> tuple[int, BaseChunk]:
        """
        Find the n-th chunk with the specified label in an iterable of chunks.

        Args:
            chunks (List[BaseChunk]): An iterable of BaseChunk objects.
            n (int): The index of the chunk to find (0-based).
            label (DocItemLabel): The label to search for in the chunks.
        """
        num_found = -1
        for i, chunk in enumerate(chunks):
            doc_chunk = DocChunk.model_validate(chunk)
            for it in doc_chunk.meta.doc_items:
                if it.label == label:
                    num_found += 1
                    if num_found == n:
                        return i, chunk
        return None, None

    @staticmethod
    def find_all_chunks_with_label(chunks: List[BaseChunk],
                                   label: DocItemLabel) -> List[BaseChunk]:
        """
        Find all chunks with the specified label in an iterable of chunks.

        Args:
            chunks (List[BaseChunk]): An iterable of BaseChunk objects.
            label (DocItemLabel): The label to search for in the chunks.

        Returns:
            List[BaseChunk]: A list of BaseChunk objects that match the label.
        """
        return [
            chunk for chunk in chunks
            if any(it.label == label
                   for it in DocChunk.model_validate(chunk).meta.doc_items)
        ]

    def print_chunk(self, chunks: List[BaseChunk], chunk_pos: int) -> None:
        """
        Print the chunk at the specified position in a rich panel format.

        Args:
            chunks (List[BaseChunk]): An iterable of BaseChunk objects.
            chunk_pos (int): The position of the chunk to print.
        """
        chunk = chunks[chunk_pos]
        ctx_text = self.chunker.contextualize(chunk=chunk)
        num_tokens = self.tokenizer.count_tokens(text=ctx_text)
        doc_items_refs = [it.self_ref for it in chunk.meta.doc_items]
        title = f'{chunk_pos=} {num_tokens=} {doc_items_refs=}'
        console.print(Panel(ctx_text, title=title))

    def chunk(self, docs: Iterable[DoclingDocument]) -> Iterator[BaseChunk]:
        """
        Chunk the document using the `Hybrid Chunker`.

        Args:
            docs (Iterable[DoclingDocument]): An iterable of DoclingDocument objects to be chunked.

        Returns:
            Iterator[BaseChunk]: An iterator over the chunks of the document.
        """
        for doc in docs:
            yield from self.chunker.chunk(dl_doc=doc)


if __name__ == '__main__':
    from ms_agent.tools.docling.doc_loader import DocLoader
    urls = [
        'https://arxiv.org/pdf/2408.09869',
        'https://arxiv.org/pdf/2502.15214',
        'https://github.com/modelscope/evalscope',
        'https://www.news.cn/talking/20250530/691e47a5d1a24c82bfa2371d1af40630/c.html',
        'aaa',
    ]

    doc_loader = DocLoader()
    docs: List[DoclingDocument] = doc_loader.load(urls_or_files=urls)

    doc_chunker = HybridDocumentChunker()
    chunks = doc_chunker.chunk(docs=docs)
    chunks = list(chunks)

    logger.info(f'Chunked {len(chunks)} chunks from {len(urls)} documents.')
