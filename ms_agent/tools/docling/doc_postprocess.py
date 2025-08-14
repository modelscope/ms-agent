from typing import Union

from docling_core.types import DoclingDocument


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
        # kept_pictures: List[PictureItem] = []
        for pic_item in doc.pictures:
            if hasattr(pic_item, 'image') and pic_item.image is not None:
                if pic_item.image.size.height * pic_item.image.size.width < PostProcess.MIN_PICTURE_SIZE:
                    pic_item.image = None  # Remove image if too small

            if hasattr(pic_item, 'annotations') and pic_item.annotations:
                pic_classes = getattr(pic_item.annotations[0],
                                      'predicted_classes', None)
                pic_class = pic_classes[
                    0].class_name if pic_classes else None  # Get the first predicted class if available
                if pic_class is not None and pic_class.lower() in [
                        'qr_code', 'logo', 'icon'
                ]:
                    pic_item.image = None

        return doc
