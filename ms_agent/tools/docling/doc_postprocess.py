from typing import List, Union

from docling_core.types import DoclingDocument
from docling_core.types.doc import PictureItem


class PostProcess:

    MIN_PICTURE_SIZE = 200.0 * 200.0  # Minimum size for pictures in pixels

    def __init__(self):
        ...

    @staticmethod
    def filter(doc: DoclingDocument) -> Union[DoclingDocument, None]:
        """
        Filter documents based on specific criteria.
        """
        # Filter out pictures that are too small
        kept_pictures: List[PictureItem] = []
        for pic_item in doc.pictures:
            if (hasattr(pic_item, 'image') and pic_item.image is not None
                    and pic_item.image.size.height * pic_item.image.size.width
                    >= PostProcess.MIN_PICTURE_SIZE):
                kept_pictures.append(pic_item)

        doc.pictures = kept_pictures

        return doc
