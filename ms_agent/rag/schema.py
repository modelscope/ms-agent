from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class KeyInformation:
    """
    Represents key information extracted from a document.

    text (str): The text of the key information.
        Note that this text may contain `image placeholder` such as `<!-- image -->`
        "<!-- image0 -->
         <!-- image1 -->
         <!-- table0 -->
         This is the document text."

    resources (List[str, Any]): A list of resources associated with the key information,
        including images, tables, or other relevant data.
        [{'id': 'doc_file_name@binary_hash@self_ref', 'content': PILImage.Image}, ...]
    """
    text: str

    resources: List[Dict[str, Any]]
