import os

from magic_pdf.config.enums import SupportedPdfParseMethod
from magic_pdf.data.data_reader_writer import (FileBasedDataReader,
                                               FileBasedDataWriter)
from magic_pdf.data.dataset import PymuDocDataset
from magic_pdf.model.doc_analyze_by_custom_model import doc_analyze


class PdfParser:

    def __init__(self, parser_workdir: str):

        # e.g. "your_workdir/resources/mineru"
        self._workdir = parser_workdir
        os.makedirs(self._workdir, exist_ok=True)

        self.relative_image_dir = 'images'
        self.markdown_dir = self._workdir

        self.img_writer = FileBasedDataWriter(
            os.path.join(self._workdir, self.relative_image_dir))
        self.md_writer = FileBasedDataWriter(self.markdown_dir)

        self.data_reader = FileBasedDataReader('')

    def parse(self, f_path: str, reuse: bool = True) -> str:
        """
        Parse a PDF file and generate various outputs including layout, markdown, content_list, etc.

        Args:
            f_path (str): The path to the PDF file to be parsed.
            reuse (bool): If True, skips processing if the target files already exist.

        Returns:
            str: The path to the generated markdown file.
        """

        # TODO:
        # 1. support file_list is a list of pdf urls
        # 2. parallel parsing

        print(f'Processing file: {f_path}')

        file_name_no_suffix = os.path.splitext(os.path.basename(f_path))[0]
        entry_md_file = os.path.join(self.markdown_dir,
                                     f'{file_name_no_suffix}.md')

        if reuse and os.path.exists(entry_md_file):
            print(f'File {entry_md_file} already exists. Skipping processing.')
            return entry_md_file

        pdf_bytes = self.data_reader.read(f_path)

        ds = PymuDocDataset(pdf_bytes)

        # inference
        if ds.classify() == SupportedPdfParseMethod.OCR:
            infer_result = ds.apply(doc_analyze, ocr=True)

            # pipeline
            pipe_result = infer_result.pipe_ocr_mode(self.img_writer)

        else:
            infer_result = ds.apply(doc_analyze, ocr=False)

            # pipeline
            pipe_result = infer_result.pipe_txt_mode(self.img_writer)

        # draw model result on each page
        infer_result.draw_model(
            os.path.join(self.markdown_dir,
                         f'{file_name_no_suffix}_model.pdf'))

        # draw layout result on each page
        pipe_result.draw_layout(
            os.path.join(self.markdown_dir,
                         f'{file_name_no_suffix}_layout.pdf'))

        # draw spans result on each page
        pipe_result.draw_span(
            os.path.join(self.markdown_dir,
                         f'{file_name_no_suffix}_spans.pdf'))

        # dump markdown
        pipe_result.dump_md(self.md_writer, f'{file_name_no_suffix}.md',
                            self.relative_image_dir)

        # dump content list
        pipe_result.dump_content_list(
            self.md_writer, f'{file_name_no_suffix}_content_list.json',
            self.relative_image_dir)

        # dump middle json
        pipe_result.dump_middle_json(self.md_writer,
                                     f'{file_name_no_suffix}_middle.json')

        print(f'Finished processing file: {f_path}')

        return entry_md_file
