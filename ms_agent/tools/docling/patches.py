# flake8: noqa
import time
from functools import partial
from pathlib import Path
from typing import Dict, Iterator

from bs4 import Tag
from docling.datamodel.document import (ConversionResult,
                                        _DocumentConversionInput)
from docling.datamodel.settings import settings
from docling.utils.utils import chunkify
from docling_core.types import DoclingDocument
from docling_core.types.doc import DocItemLabel, ImageRef
from ms_agent.utils.logger import get_logger
from ms_agent.utils.utils import extract_image

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

    # extract image from url or data URI
    img_pil: 'Image.Image' = extract_image(
        img_url=img_url,
        backend=self,
        base_url=self.current_url if hasattr(self, 'current_url') else None)

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

    # extract image from url or data URI
    img_pil: 'Image.Image' = extract_image(
        img_url=img_url,
        backend=self,
        base_url=self.current_url if hasattr(self, 'current_url') else None)

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

    model_id: str = 'ms-agent/docling-models'
    logger.info(f'Downloading or reloading {model_id} from ModelScope Hub ...')
    download_path: str = snapshot_download(model_id=model_id)
    return Path(download_path)


def download_models_pic_classifier_ms(
    local_dir=None,
    force: bool = False,
    progress: bool = False,
) -> Path:
    from modelscope import snapshot_download

    model_id: str = 'ms-agent/DocumentFigureClassifier'
    logger.info(f'Downloading or reloading {model_id} from ModelScope Hub ...')
    download_path: str = snapshot_download(model_id=model_id)
    return Path(download_path)


def patch_easyocr_models():
    """
    Patch EasyOCR models URLs to use ModelScope Hub.
    """
    from easyocr.config import detection_models, recognition_models

    logger.info('Patching EasyOCR models URLs for ModelScope...')

    # Patch detection models
    detection_models['craft'][
        'url'] = 'https://modelscope.cn/models/ms-agent/craft_mlt_25k/resolve/master/craft_mlt_25k.zip'
    detection_models['dbnet18'][
        'url'] = 'https://modelscope.cn/models/ms-agent/pretrained_ic15_res18/resolve/master/pretrained_ic15_res18.zip'
    detection_models['dbnet50'][
        'url'] = 'https://modelscope.cn/models/ms-agent/pretrained_ic15_res50/resolve/master/pretrained_ic15_res50.zip'

    # Patch recognition models
    recognition_models['gen2']['english_g2'][
        'url'] = 'https://modelscope.cn/models/ms-agent/english_g2/resolve/master/english_g2.zip'
    recognition_models['gen2']['latin_g2'][
        'url'] = 'https://modelscope.cn/models/ms-agent/latin_g2/resolve/master/latin_g2.zip'
    recognition_models['gen2']['zh_sim_g2'][
        'url'] = 'https://modelscope.cn/models/ms-agent/zh_sim_g2/resolve/master/zh_sim_g2.zip'
    recognition_models['gen2']['japanese_g2'][
        'url'] = 'https://modelscope.cn/models/ms-agent/japanese_g2/resolve/master/japanese_g2.zip'
    recognition_models['gen2']['korean_g2'][
        'url'] = 'https://modelscope.cn/models/ms-agent/korean_g2/resolve/master/korean_g2.zip'
    recognition_models['gen2']['telugu_g2'][
        'url'] = 'https://modelscope.cn/models/ms-agent/telugu_g2/resolve/master/telugu_g2.zip'
    recognition_models['gen2']['kannada_g2'][
        'url'] = 'https://modelscope.cn/models/ms-agent/kannada_g2/resolve/master/kannada_g2.zip'
    recognition_models['gen2']['cyrillic_g2'][
        'url'] = 'https://modelscope.cn/models/ms-agent/cyrillic_g2/resolve/master/cyrillic_g2.zip'


def convert_ms(self, conv_input: _DocumentConversionInput,
               raises_on_error: bool) -> Iterator[ConversionResult]:
    """
    Patch the `docling.document_converter.DocumentConverter._convert` method for image parsing.
    """
    start_time = time.monotonic()

    def _add_custom_attributes(doc: DoclingDocument, target: str,
                               attributes_dict: Dict) -> DoclingDocument:
        """
        Add custom attributes to the target object.
        """
        for key, value in attributes_dict.items():
            target_obj = getattr(doc, target) if target is not None else doc
            if not hasattr(target_obj, key):
                setattr(target_obj, key, value)
            else:
                raise ValueError(
                    f"Attribute '{key}' already exists in the document.")
        return doc

    for input_batch in chunkify(
            conv_input.docs(self.format_to_options),
            settings.perf.doc_batch_size,  # pass format_options
    ):
        # parallel processing only within input_batch
        # with ThreadPoolExecutor(
        #    max_workers=settings.perf.doc_batch_concurrency
        # ) as pool:
        #   yield from pool.map(self.process_document, input_batch)
        # Note: PDF backends are not thread-safe, thread pool usage was disabled.

        for item in map(
                partial(
                    self._process_document, raises_on_error=raises_on_error),
                map(
                    lambda doc: _add_custom_attributes(
                        doc, '_backend', {'current_url': self.current_url}),
                    input_batch)):
            elapsed = time.monotonic() - start_time
            start_time = time.monotonic()
            logger.info(
                f'Finished converting document {item.input.file.name} in {elapsed:.2f} sec.'
            )
            yield item
