# flake8: noqa
import os
from pathlib import Path
from typing import Dict, Iterator, List, Union

from bs4 import Tag
from docling.backend.html_backend import HTMLDocumentBackend
from docling.datamodel.accelerator_options import AcceleratorOptions
from docling.datamodel.base_models import InputFormat
from docling.datamodel.document import ConversionResult
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.models.document_picture_classifier import \
    DocumentPictureClassifier
from docling.models.layout_model import LayoutModel
from docling.models.table_structure_model import TableStructureModel
from docling_core.types import DoclingDocument
from docling_core.types.doc import DocItem, DocItemLabel, ImageRef
from ms_agent.tools.docling.doc_postprocess import PostProcess
from ms_agent.utils.logger import get_logger
from ms_agent.utils.patcher import patch
from ms_agent.utils.utils import (load_image_from_uri_to_pil,
                                  load_image_from_url_to_pil, validate_url)

logger = get_logger()


def html_handle_figure(self, element: Tag, doc: DoclingDocument) -> None:
    """
    Patch the `docling.backend.html_backend.HTMLDocumentBackend.handle_figure` method.
    """
    logger.debug(
        f'Patching HTMLDocumentBackend.handle_figure for {doc.origin.filename}'
    )

    img_element: Tag = element.find('img')
    if isinstance(img_element, Tag):
        img_url = img_element.attrs.get('src', None)
    else:
        img_url = None

    if img_url:
        if img_url.startswith('data:'):
            img_pil, ext = load_image_from_uri_to_pil(img_url)
        else:
            if not img_url.startswith('http'):
                img_url = validate_url(img_url=img_url, backend=self)
            img_pil = load_image_from_url_to_pil(
                img_url) if img_url.startswith('http') else None
    else:
        img_pil = None

    dpi: int = int(img_pil.info.get('dpi', (96, 96))[0]) if img_pil else 96
    img_ref: ImageRef = None
    if img_pil:
        img_ref = ImageRef.from_pil(
            image=img_pil,
            dpi=dpi,
        )

    contains_captions = element.find(['figcaption'])
    if isinstance(contains_captions, Tag):
        texts = []
        for item in contains_captions:
            texts.append(item.text)

        fig_caption = doc.add_text(
            label=DocItemLabel.CAPTION,
            text=(''.join(texts)).strip(),
            content_layer=self.content_layer,
        )
        doc.add_picture(
            annotations=[],
            image=img_ref,
            parent=self.parents[self.level],
            caption=fig_caption,
            content_layer=self.content_layer,
        )
    else:
        doc.add_picture(
            annotations=[],
            image=img_ref,
            parent=self.parents[self.level],
            caption=None,
            content_layer=self.content_layer,
        )


def html_handle_image(self, element: Tag, doc: DoclingDocument) -> None:
    """
    Patch the `docling.backend.html_backend.HTMLDocumentBackend.handle_image` method to use the custom.
    """
    logger.debug(
        f'Patching HTMLDocumentBackend.handle_image for {doc.origin.filename}')

    # Get the image from element
    img_url: str = element.attrs.get('src', None)

    if img_url:
        if img_url.startswith('data:'):
            img_pil, ext = load_image_from_uri_to_pil(img_url)
        else:
            if not img_url.startswith('http'):
                img_url = validate_url(img_url=img_url, backend=self)
            img_pil = load_image_from_url_to_pil(img_url)
    else:
        img_pil = None

    dpi: int = int(img_pil.info.get('dpi', (96, 96))[0]) if img_pil else 96

    img_ref: ImageRef = None
    if img_pil:
        img_ref = ImageRef.from_pil(
            image=img_pil,
            dpi=dpi,
        )

    doc.add_picture(
        annotations=[],
        image=img_ref,
        parent=self.parents[self.level],
        caption=None,
        prov=None,
        content_layer=self.content_layer,
    )


def download_models_ms(
    local_dir=None,
    force: bool = False,
    progress: bool = False,
) -> Path:
    from modelscope import snapshot_download

    download_path: str = snapshot_download(model_id='ds4sd/docling-models', )
    return Path(download_path)


def download_models_pic_classifier_ms(
    local_dir=None,
    force: bool = False,
    progress: bool = False,
) -> Path:
    from modelscope import snapshot_download

    download_path: str = snapshot_download(
        model_id='ds4sd/DocumentFigureClassifier', )
    return Path(download_path)


class DocLoader:

    MAX_NUM_PAGES = 1000
    MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB

    # Number of threads for document conversion
    DOC_CONVERT_NUM_THREADS = os.environ.get('DOC_CONVERT_NUM_THREADS', 16)

    def __init__(self):

        accelerator_options = AcceleratorOptions()
        accelerator_options.num_threads = self.DOC_CONVERT_NUM_THREADS
        accelerator_options.device = 'auto'
        accelerator_options.cuda_use_flash_attention2 = False  # TODO

        pdf_pipeline_options = PdfPipelineOptions()
        pdf_pipeline_options.generate_page_images = True
        pdf_pipeline_options.generate_picture_images = True
        pdf_pipeline_options.generate_table_images = True
        pdf_pipeline_options.do_code_enrichment = False
        pdf_pipeline_options.do_formula_enrichment = False
        pdf_pipeline_options.do_picture_classification = True
        pdf_pipeline_options.do_picture_description = False
        pdf_pipeline_options.images_scale = 2.0
        pdf_pipeline_options.accelerator_options = accelerator_options  # type: ignore

        self._converter = DocumentConverter(
            format_options={
                InputFormat.PDF:
                PdfFormatOption(pipeline_options=pdf_pipeline_options)
            })

    @staticmethod
    def _group_by_input_format(
            urls_or_files: list[str]) -> dict[InputFormat, list[str]]:
        """
        Group the provided URLs or files by their input format.
        This is a placeholder implementation and should be replaced with actual logic.

        TODO: to be implemented in the future, currently only supports PDF and HTML formats.
        """
        grouped = {InputFormat.PDF: [], InputFormat.HTML: []}
        for url_or_file in urls_or_files:
            if url_or_file.endswith('.pdf') or url_or_file.startswith(
                    'https://arxiv.org/pdf/'):
                grouped[InputFormat.PDF].append(url_or_file)
            elif url_or_file.startswith('http') or url_or_file.endswith(
                    '.html'):
                grouped[InputFormat.HTML].append(url_or_file)
            else:
                logger.error(
                    f'**Error: Unsupported file type for {url_or_file}')
        return grouped

    @staticmethod
    def _transform_dict(original_dict):
        """
        Transfer {'key': [val1, val2, ...]} to the format of {val1: 'key', val2: 'key', ...}

        Args:
            original_dict (dict): original dictionary to be transformed.

        Returns:
            dict: transformed dictionary with values as keys and original keys as values.
        """
        transformed_dict = {}
        for key, values_list in original_dict.items():
            for value in values_list:
                transformed_dict[value] = key
        return transformed_dict

    @staticmethod
    def get_item_ref_key(doc: DoclingDocument, item: DocItem) -> str:
        """
        Get the reference key for a DocItem in the format of 'doc_file_name@binary_hash@self_ref'.
        """
        return f'{doc.origin.filename}@{doc.origin.binary_hash}@{item.self_ref}'

    @staticmethod
    def map_item_by_ref(docs: List[DoclingDocument]) -> Dict[str, DocItem]:
        """
        Get all pictures and tables in the document and map them by their self_ref,
        in the form of {doc_name@self_ref: item}
        """
        ref_item_d: dict = {}
        # Deal with all pictures and tables
        for doc in docs:
            for pic_item in doc.pictures:
                ref_item_d[
                    f'{DocLoader.get_item_ref_key(doc, pic_item)}'] = pic_item

            for tab_item in doc.tables:
                ref_item_d[
                    f'{DocLoader.get_item_ref_key(doc, tab_item)}'] = tab_item

        return ref_item_d

    @staticmethod
    def _preprocess(url_or_files: List[str]) -> List[str]:
        """
        Pre-process the URLs or files before conversion.

        Args:
            urls_or_files (List[str]): The list of URLs or files to preprocess.

        Returns:
            List[str]: The pre-processed list of URLs or files.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def check_url_valid(url: tuple[int, str]) -> tuple[int, str] | None:
            """
            Check if the URL is valid and accessible.
            """
            import requests
            from urllib.parse import urlparse

            idx, _url = url
            try:
                # Parse URL to check if it's valid
                parsed_url = urlparse(_url)
                if not parsed_url.netloc:
                    logger.warning(f'Invalid URL format: {_url}')
                    return None

                # Try to send a HEAD request to check if the URL is accessible
                response = requests.head(_url, timeout=10)
                if response.status_code >= 400:
                    response = requests.get(_url, stream=True, timeout=10)
                    if response.status_code >= 400:
                        logger.warning(
                            f'URL returned error status {response.status_code}: {_url}'
                        )
                    return None
                return url
            except requests.RequestException as e2:
                logger.warning(f'Failed to access URL {_url}: {e2}')
                return None

        # Step1: Remove urls or files that cannot be processed
        http_urls = [(i, url) for i, url in enumerate(url_or_files)
                     if url and url.startswith('http')]
        file_paths = [(i, file) for i, file in enumerate(url_or_files)
                      if file and not file.startswith('http')]
        preprocessed = []
        with ThreadPoolExecutor() as executor:
            futures = [
                executor.submit(check_url_valid, url) for url in http_urls
            ]
            for future in as_completed(futures):
                result = future.result()
                if result:
                    preprocessed.append(result)

        # Step2: Add file paths that are valid
        preprocessed.extend(file_paths)

        # Restore the original order of URLs or files
        preprocessed = sorted(preprocessed, key=lambda x: x[0])
        logger.info(
            f'Preprocessed {len(preprocessed)} URLs or files for conversion.')

        return [item[1] for item in preprocessed]

    @staticmethod
    def _postprocess(doc: DoclingDocument) -> Union[DoclingDocument, None]:
        """
        Post-process the document after conversion.

        doc (DoclingDocument): The document to post-process.
        Returns:
            DoclingDocument or None: The post-processed document, or None if it should be discarded.
        """
        doc = PostProcess.filter(doc)

        return doc

    @patch(LayoutModel, 'download_models', download_models_ms)
    @patch(TableStructureModel, 'download_models', download_models_ms)
    @patch(DocumentPictureClassifier, 'download_models',
           download_models_pic_classifier_ms)
    @patch(HTMLDocumentBackend, 'handle_image', html_handle_image)
    @patch(HTMLDocumentBackend, 'handle_figure', html_handle_figure)
    def load(self, urls_or_files: list[str]) -> List[DoclingDocument]:

        urls_or_files: List[str] = self._preprocess(urls_or_files)

        # TODO: Support progress bar for document loading (with pather)
        results: Iterator[ConversionResult] = self._converter.convert_all(
            source=urls_or_files, )

        final_results = []
        while True:
            try:
                res: ConversionResult = next(results)
                if res is None or res.document is None:
                    continue

                # Post-process the document
                doc: DoclingDocument = self._postprocess(res.document)
                if doc is not None:
                    final_results.append(doc)

            except StopIteration:
                break

            except Exception as e:
                logger.warning(f'Skipping document due to error: {e}')
                continue

        return final_results


if __name__ == '__main__':

    urls = [
        'https://arxiv.org/pdf/2408.09869',
        # 'https://arxiv.org/pdf/2502.15214',
        # 'https://arxiv.org/pdf/2505.13400',  # todo: cannot convert
        # 'https://github.com/modelscope/evalscope',
        # 'https://www.news.cn/talking/20250530/691e47a5d1a24c82bfa2371d1af40630/c.html',
        # 'https://www.chinaxiantour.com/chengdu-travel-guide/how-to-eat-hot-pot.html',
        # 'https://www.chinahighlights.com/hangzhou/food-restaurant.htm',
        # 'aaa',
    ]

    doc_loader = DocLoader()
    doc_results = doc_loader.load(urls_or_files=urls)
    print(doc_results)
