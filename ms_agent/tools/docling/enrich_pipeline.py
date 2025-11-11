# yapf: disable
from pathlib import Path
from typing import Iterable, List, Optional, Union

import numpy as np
from docling.datamodel.accelerator_options import AcceleratorOptions
from docling.datamodel.pipeline_options import PipelineOptions
from docling.datamodel.settings import settings
from docling.models.code_formula_model import (CodeFormulaModel,
                                               CodeFormulaModelOptions)
from docling.models.document_picture_classifier import (
    DocumentPictureClassifier, DocumentPictureClassifierOptions)
from docling.pipeline.simple_pipeline import SimplePipeline
from docling_core.types.doc import (DoclingDocument, NodeItem,
                                    PictureClassificationClass,
                                    PictureClassificationData, PictureItem)
from PIL import Image


class DocPipelineOptions(PipelineOptions):
    """Options for processing Word and PPT documents in the pipeline."""

    artifacts_path: Optional[Union[Path, str]] = None
    do_picture_classification: bool = False  # True: classify pictures in documents
    do_code_enrichment: bool = False  # True: perform code OCR
    do_formula_enrichment: bool = False  # True: perform formula OCR, return Latex code


class EnrichDocumentPictureClassifier(DocumentPictureClassifier):
    """
    Specializes DocumentPictureClassifier for robust pipeline processing.

    This classifier is designed to handle document formats like Word and PPT where
    images might be missing or invalid. It overrides the default behavior to
    skip elements with unreadable images instead of raising an error, thus
    preventing the entire processing pipeline from halting.
    """

    def __init__(self, enabled: bool, artifacts_path: Optional[Path],
                 options: DocumentPictureClassifierOptions,
                 accelerator_options: AcceleratorOptions):
        super().__init__(enabled, artifacts_path, options, accelerator_options)

    def __call__(
        self,
        doc: DoclingDocument,
        element_batch: Iterable[NodeItem],
    ) -> Iterable[NodeItem]:
        """
        This method iterates through a batch of elements, extracts their images,
        and applies the picture classification model. Unlike the base class
        implementation, it gracefully handles cases where an image cannot be
        retrieved (i.e., `get_image()` returns None) by skipping that element.
        This ensures that a single faulty item does not stop the entire batch
        processing.
        """
        if not self.enabled:
            for element in element_batch:
                yield element
            return

        images: List[Union[Image.Image, np.ndarray]] = []
        elements_with_images: List[PictureItem] = []
        element_batch_list: List[PictureItem] = list(element_batch)
        for el in element_batch_list:
            assert isinstance(
                el, PictureItem), f'Element {el} is not a PictureItem'
            img = el.get_image(doc)
            if img is not None:
                images.append(img)
                elements_with_images.append(el)

        if images:
            outputs = self.document_picture_classifier.predict(images)
            for element, output in zip(elements_with_images, outputs):
                element.annotations.append(
                    PictureClassificationData(
                        provenance='DocumentPictureClassifier',
                        predicted_classes=[
                            PictureClassificationClass(
                                class_name=pred[0],
                                confidence=pred[1],
                            ) for pred in output
                        ],
                    ))

        for element in element_batch_list:
            yield element


class EnrichDocPipeline(SimplePipeline):
    """Pipeline for enriching Word and PPT documents with additional processing steps."""

    def __init__(self, pipeline_options: DocPipelineOptions):
        super().__init__(pipeline_options)

        artifacts_path: Optional[Path] = None
        if pipeline_options.artifacts_path is not None:
            artifacts_path = Path(pipeline_options.artifacts_path).expanduser()
        elif settings.artifacts_path is not None:
            artifacts_path = Path(settings.artifacts_path).expanduser()

        if artifacts_path is not None and not artifacts_path.is_dir():
            raise RuntimeError(
                f'The value of {artifacts_path=} is not valid. '
                'When defined, it must point to a folder containing all models required by the pipeline.'
            )

        self.enrichment_pipe = [
            # Code Formula Enrichment Model
            CodeFormulaModel(
                enabled=pipeline_options.do_code_enrichment
                or pipeline_options.do_formula_enrichment,
                artifacts_path=artifacts_path,
                options=CodeFormulaModelOptions(
                    do_code_enrichment=pipeline_options.do_code_enrichment,
                    do_formula_enrichment=pipeline_options.do_formula_enrichment,
                ),
                accelerator_options=pipeline_options.accelerator_options,
            ),
            # Document Picture Classifier
            EnrichDocumentPictureClassifier(
                enabled=pipeline_options.do_picture_classification,
                artifacts_path=artifacts_path,
                options=DocumentPictureClassifierOptions(),
                accelerator_options=pipeline_options.accelerator_options,
            )
        ]

    @classmethod
    def get_default_options(cls) -> DocPipelineOptions:
        return DocPipelineOptions()
