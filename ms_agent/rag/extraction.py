# flake8: noqa
# yapf: disable
from abc import ABC, abstractmethod
from typing import Dict, List

from docling_core.transforms.chunker import BaseChunk
from docling_core.types import DoclingDocument
from docling_core.types.doc import DocItem, DocItemLabel
from ms_agent.rag.schema import KeyInformation
from ms_agent.tools.docling.chunker import HybridDocumentChunker
from ms_agent.tools.docling.doc_loader import DocLoader


class KeyInformationExtraction(ABC):
    """
    Abstract base class for key information extraction.
    """

    def __init__(self):
        ...

    @abstractmethod
    def extract(self):
        """
        Extract key information from the input.
        """
        raise NotImplementedError('Subclasses must implement this method.')


class HierarchicalKeyInformationExtraction(KeyInformationExtraction):

    def __init__(self, urls_or_files: list[str]):
        super().__init__()

        doc_loader = DocLoader()
        self.docs: List[DoclingDocument] = doc_loader.load(
            urls_or_files=urls_or_files)
        self.all_ref_items: Dict[str, DocItem] = doc_loader.map_item_by_ref(
            self.docs)

        self.chunker = HybridDocumentChunker()
        self.chunks: List[BaseChunk] = list(self.chunker.chunk(docs=self.docs))

    @staticmethod
    def _replace_resource_placeholders(text: str, resources: List[Dict[str, str]], placeholder: str = '<!-- image -->') -> str:
        """
        Replace placeholders in the text with actual resource ids in sequence.

        Args:
            text (str): The text containing placeholders like `<!-- image -->`.
                e.g. text = "<!-- image -->\n<!-- image -->\n<!-- image -->\nHello world."
            resources (List[Dict[str, str]]): A list of resources with 'id' keys to replace the placeholders.
                e.g. resources = [{'id': 'doc_file_name@binary_hash@self_ref1'}, {'id': 'doc_file_name@binary_hash@self_ref2'}, {'id': 'doc_file_name@binary_hash@self_ref3'}]

        Returns:
            str: The text with placeholders replaced by actual resource ids.
        """

        # Get the list of resource ids to replace
        replace_values = [res['id'] for res in resources]

        # Replace each placeholder in the text with the corresponding resource id
        for value in replace_values:
            text = text.replace(placeholder, f'<resource_info>{value}</resource_info>', 1)

        return text

    def process_pictures_tables(self):
        """
        Get the nearest context for each picture and table in the document.
        """
        target_chunks = []

        # Deal with all pictures
        target_chunks.extend(
            HybridDocumentChunker.find_all_chunks_with_label(
                chunks=self.chunks, label=DocItemLabel.PICTURE))

        # Deal with all tables
        target_chunks.extend(
            HybridDocumentChunker.find_all_chunks_with_label(
                chunks=self.chunks, label=DocItemLabel.TABLE))

        return target_chunks

    def process_headings(self):
        """
        Process headings in the document to create a hierarchical structure.
        """
        # TODO: to be finished
        target_chunks = []

        target_chunks.extend(
            HybridDocumentChunker.find_all_chunks_with_label(
                chunks=self.chunks, label=DocItemLabel.SECTION_HEADER))

        # TODO: add filter to determine which headings to keep (rule-based and llm-based)

        return target_chunks

    def extract(self) -> List[KeyInformation]:

        final_res: List[KeyInformation] = []

        key_chunks: List[BaseChunk] = self.process_pictures_tables()
        print(f'Found {len(key_chunks)} key chunks with pictures and tables.')

        # TODO: TBD ...
        heading_chunks: List[BaseChunk] = self.process_headings()

        for key_chunk in key_chunks:

            # Replace image placeholders with actual resource id (doc_file_name@binary_hash@self_ref)
            resources = []
            for item in key_chunk.meta.doc_items:
                if item.label == DocItemLabel.PICTURE or item.label == DocItemLabel.TABLE:
                    item_ref_key = f'{key_chunk.meta.origin.filename}@{key_chunk.meta.origin.binary_hash}@{item.self_ref}'
                    if item_ref_key in self.all_ref_items:
                        resources.append({
                            'id': item_ref_key,
                            'content': self.all_ref_items[item_ref_key]
                        })

            if len(resources) == 0:
                continue

            text: str = key_chunk.text
            replaced_text: str = self._replace_resource_placeholders(
                text=text,
                resources=resources,
                placeholder='<!-- image -->'    # TODO: Add table placeholder
            )

            # Append the KeyInformation object to the final result
            final_res.append(
                KeyInformation(text=replaced_text, resources=resources)
            )

        return final_res


if __name__ == '__main__':
    urls_or_files = [
        # 'https://arxiv.org/pdf/2408.09869',
        # 'https://arxiv.org/pdf/2502.15214',
        'https://github.com/modelscope/evalscope',
        # 'https://www.news.cn/world/20250613/fa77beee47134689901e4e32ea108886/c.html',
        # 'aaa',
        # '/path/to/file.pdf',
    ]

    extractor = HierarchicalKeyInformationExtraction(
        urls_or_files=urls_or_files)
    key_chunk_res = extractor.extract()

    if len(key_chunk_res) > 0:
        print(key_chunk_res[0])
