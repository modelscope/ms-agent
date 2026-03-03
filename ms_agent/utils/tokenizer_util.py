# Copyright (c) ModelScope Contributors. All rights reserved.
from typing import List, Optional, Union


class TokenizerUtil:
    """Fast tokenizer utility using modelscope AutoTokenizer."""

    def __init__(self, model_id: Optional[str] = None):
        """
        Tokenizer encoding and counting utility.
        Args:
            model_id: Model ID for loading the tokenizer. Defaults to "Qwen/Qwen3-8B".
        """
        from modelscope import AutoTokenizer

        model_id: str = model_id or 'Qwen/Qwen3-8B'
        self.tokenizer = AutoTokenizer.from_pretrained(model_id)

    def encode(self, content: str) -> List[int]:
        """Encode text into token IDs.

        Args:
            content: Input text string.

        Returns:
            List of token IDs.
        """
        if not content.strip():
            return []
        return self.tokenizer.encode(content.strip())

    def decode(self, token_ids: List[int]) -> str:
        """Decode a list of token IDs back into a natural text string.

        Args:
            token_ids: List of token IDs to decode.

        Returns:
            Decoded text string.
        """
        if not token_ids:
            return ''
        return self.tokenizer.decode(token_ids, skip_special_tokens=True)

    def segment(self, content: str) -> List[str]:
        """Tokenize text into a list of token strings suitable for BM25-like algorithms indexing/retrieval.

        This method returns the actual sub-word tokens as strings (e.g., ["▁Hello", "▁world"]),
        preserving token boundaries. These tokens can be directly used as terms in BM25.

        Args:
            content: Input text string.

        Returns:
            List of token strings (not IDs), ready for BM25-style processing.
        """
        if not content.strip():
            return []

        token_ids = self.encode(content)
        # Decode each token ID individually to get its string representation
        token_strings = [
            self.tokenizer.decode([tid], skip_special_tokens=True)
            for tid in token_ids
        ]
        return token_strings

    def count_tokens(self,
                     contents: Union[str, List[str]]) -> Union[int, List[int]]:
        """
        Batch count tokens for multiple texts.

        Args:
            contents: List of input text strings.

        Returns:
            List of token counts corresponding to each input text, or an integer if a single string is provided.
        """
        if isinstance(contents, str):
            contents = [contents]

        counts = []
        for content in contents:
            if not content.strip():
                counts.append(0)
            else:
                counts.append(len(self.tokenizer.encode(content.strip())))

        if len(contents) == 1:
            return counts[0]
        return counts
