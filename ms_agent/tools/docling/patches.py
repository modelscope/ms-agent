# flake8: noqa
from pathlib import Path

from bs4 import Tag
from docling_core.types import DoclingDocument
from docling_core.types.doc import DocItem, DocItemLabel, ImageRef
from ms_agent.utils.logger import get_logger
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
            img_pil = load_image_from_uri_to_pil(img_url)
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
            img_pil = load_image_from_uri_to_pil(img_url)
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
    # from easyocr.config import (
    #     detection_models as det_models_dict,
    #     recognition_models as rec_models_dict,
    # )
    #
    # logger.info('Patching EasyOCR models URLs for ModelScope...')
    #
    # det_models_dict['craft'][
    #     'url'] = 'https://modelscope.cn/models/ms-agent/craft_mlt_25k/resolve/master/craft_mlt_25k.zip'
    # det_models_dict['dbnet18'][
    #     'url'] = 'https://modelscope.cn/models/ms-agent/pretrained_ic15_res18/resolve/master/pretrained_ic15_res18.zip'
    # det_models_dict['dbnet50'][
    #     'url'] = 'https://modelscope.cn/models/ms-agent/pretrained_ic15_res50/resolve/master/pretrained_ic15_res50.zip'
    #
    # rec_models_dict['gen2']['english_g2'][
    #     'url'] = 'https://modelscope.cn/models/ms-agent/english_g2/resolve/master/english_g2.zip'
    # rec_models_dict['gen2']['latin_g2'][
    #     'url'] = 'https://modelscope.cn/models/ms-agent/latin_g2/resolve/master/latin_g2.zip'
    # rec_models_dict['gen2']['zh_sim_g2'][
    #     'url'] = 'https://modelscope.cn/models/ms-agent/zh_sim_g2/resolve/master/zh_sim_g2.zip'
    # rec_models_dict['gen2']['japanese_g2'][
    #     'url'] = 'https://modelscope.cn/models/ms-agent/japanese_g2/resolve/master/japanese_g2.zip'
    # rec_models_dict['gen2']['korean_g2'][
    #     'url'] = 'https://modelscope.cn/models/ms-agent/korean_g2/resolve/master/korean_g2.zip'
    # rec_models_dict['gen2']['telugu_g2'][
    #     'url'] = 'https://modelscope.cn/models/ms-agent/telugu_g2/resolve/master/telugu_g2.zip'
    # rec_models_dict['gen2']['kannada_g2'][
    #     'url'] = 'https://modelscope.cn/models/ms-agent/kannada_g2/resolve/master/kannada_g2.zip'
    # rec_models_dict['gen2']['cyrillic_g2'][
    #     'url'] = 'https://modelscope.cn/models/ms-agent/cyrillic_g2/resolve/master/cyrillic_g2.zip'

    from easyocr.config import detection_models, recognition_models

    logger.info('Patching EasyOCR models URLs for ModelScope...')

    detection_models['craft'][
        'url'] = 'https://modelscope.cn/models/ms-agent/craft_mlt_25k/resolve/master/craft_mlt_25k.zip'
    detection_models['dbnet18'][
        'url'] = 'https://modelscope.cn/models/ms-agent/pretrained_ic15_res18/resolve/master/pretrained_ic15_res18.zip'
    detection_models['dbnet50'][
        'url'] = 'https://modelscope.cn/models/ms-agent/pretrained_ic15_res50/resolve/master/pretrained_ic15_res50.zip'

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
