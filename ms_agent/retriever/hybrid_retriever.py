import asyncio
import math
import os
import threading
from typing import List, Tuple

import faiss
import numpy as np
from ms_agent.utils.tokenizer_util import TokenizerUtil

os.environ['OMP_NUM_THREADS'] = '1'
os.environ['MKL_NUM_THREADS'] = '1'
os.environ['TOKENIZERS_PARALLELISM'] = 'false'


class BM25Retriever:
    """
    Sparse retriever based on BM25 algorithm.
    """

    def __init__(self,
                 tokenized_corpus: List[List[str]],
                 k1: float = 1.5,
                 b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.corpus_size = len(tokenized_corpus)
        self.tokenized_corpus = tokenized_corpus

        self.avgdl = 0
        self.idf = {}
        self.doc_len = []
        self.doc_term_freqs = []
        self._initialize(self.tokenized_corpus)

    def _initialize(self, tokenized_corpus: List[List[str]]):
        """Calculate IDF and average document length."""
        total_length = 0
        doc_count = len(tokenized_corpus)

        for doc_tokens in tokenized_corpus:
            length = len(doc_tokens)
            self.doc_len.append(length)
            total_length += length

            unique_tokens = set(doc_tokens)
            for token in unique_tokens:
                self.idf[token] = self.idf.get(token, 0) + 1

        self.avgdl = total_length / doc_count if doc_count > 0 else 0

        for word, freq in self.idf.items():
            self.idf[word] = math.log((self.corpus_size - freq + 0.5)
                                      / (freq + 0.5) + 1)

        for doc_tokens in tokenized_corpus:
            freqs = {}
            for token in doc_tokens:
                freqs[token] = freqs.get(token, 0) + 1
            self.doc_term_freqs.append(freqs)

    def get_scores(self, tokenized_query: List[str]) -> List[float]:
        scores = [0.0] * self.corpus_size

        for token in tokenized_query:
            if token not in self.idf:
                continue
            idf_score = self.idf[token]
            for index, doc_freqs in enumerate(self.doc_term_freqs):
                freq = doc_freqs.get(token, 0)
                if freq == 0: continue  # noqa: E701
                doc_len = self.doc_len[index]
                numerator = freq * (self.k1 + 1)
                denominator = freq + self.k1 * (
                    1 - self.b + self.b * (doc_len / self.avgdl))  # noqa: W504
                scores[index] += idf_score * (numerator / denominator)
        return scores


class HybridRetriever:
    """
    Hybrid retriever combining Dense Retrieval (FAISS) and Sparse Retrieval (BM25).
    """

    def __init__(
            self,
            corpus: List[str] = None,
            embed_model:
        str = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2',  # noqa
            tokenizer_model_id: str = 'Qwen/Qwen3-8B',
            bm25_k1: float = 1.5,
            bm25_b: float = 0.75):
        """
        Initialize Hybrid Retriever with both Dense and Sparse indices.

        Args:
            corpus: List of document strings to index. Optional, can be set later in function `search()`.
            embed_model: Model ID for the embedding model used in Dense Retrieval.
            tokenizer_model_id: Model ID for the tokenizer used in Sparse Retrieval.
            bm25_k1: BM25 k1 parameter.
            bm25_b: BM25 b parameter.

        Attributes:
            self.corpus: The list of documents.
            self.embed_model: SentenceTransformer model for embeddings.
            self.index: FAISS index for dense retrieval.
            self.tokenizer_util: TokenizerUtil instance for tokenization.
            self.bm25: BM25Retriever instance for sparse retrieval.

        Raises:
            ValueError: If the corpus is empty.

        Example:
            my_documents = [
                "Document 1 text...",
                "Document 2 text...",
                "Document 3 text...",
                # ... more documents ...
            ]

            # Case 1: Initialize with corpus
            retriever = HybridRetriever(corpus=my_documents)
            results = retriever.search(
                query="example query",
                top_k=5,
                min_score=0.6,
                alpha=0.7
            )

            # Case 2: Initialize without corpus, set later in search()
            retriever = HybridRetriever()
            results = retriever.search(
                query="example query",
                corpus=my_documents,
                top_k=5,
                min_score=0.6,
                alpha=0.7
            )
        """
        self.corpus = corpus

        # Lock for corpus re-initialization (prevent concurrent modification)
        self._corpus_lock = threading.Lock()

        # Initialize Tokenizer Utility
        print(f'Loading Tokenizer: {tokenizer_model_id}...')
        self.tokenizer_util = TokenizerUtil(model_id=tokenizer_model_id)

        # Initialize Dense Retriever (FAISS)
        embed_model_path: str = self._load_model(
            model_id=embed_model,
            ignore_patterns=[
                'openvino/*', 'onnx/*', 'pytorch_model.bin', 'rust_model.ot',
                'tf_model.h5'
            ])

        from sentence_transformers import SentenceTransformer

        self.embed_model = SentenceTransformer(embed_model_path)
        self.index = None

        self._init_corpus(
            corpus=self.corpus,
            bm25_k1=bm25_k1,
            bm25_b=bm25_b,
        )

    @staticmethod
    def _load_model(model_id: str, ignore_patterns: List[str] = None) -> str:
        print(f'Loading embedding model: {model_id}...')
        from modelscope import snapshot_download

        try:
            return snapshot_download(
                model_id=model_id, ignore_patterns=ignore_patterns)
        except Exception as e:
            raise RuntimeError(f'Failed to load model {model_id}: {e}') from e

    def _init_corpus(self,
                     corpus: List[str],
                     bm25_k1: float = 1.5,
                     bm25_b: float = 0.75):
        """
        Initialize corpus and build both Dense and Sparse indices.

        Args:
            corpus: List of document strings to index.
            bm25_k1: BM25 k1 parameter.
            bm25_b: BM25 b parameter.

        Attributes:
            self.corpus: The list of documents.
            self.index: FAISS index for dense retrieval.
            self.bm25: BM25Retriever instance for sparse retrieval.
            self.tokenized_corpus: Tokenized corpus for BM25.

        Returns:
            None
        """
        if not corpus or len(corpus) <= 0:
            return
        self.corpus = corpus
        self._build_dense_index(texts=self.corpus)

        # Initialize Sparse Retriever (BM25)
        print('Building BM25 index...')
        self.tokenized_corpus = [
            self.tokenizer_util.segment(doc) for doc in self.corpus
        ]
        self.bm25 = BM25Retriever(
            tokenized_corpus=self.tokenized_corpus,
            k1=bm25_k1,
            b=bm25_b,
        )
        print('BM25 index built.')

    def _get_embeddings(self, texts: List[str]) -> np.ndarray:
        embeddings = self.embed_model.encode(texts, convert_to_numpy=True)
        return embeddings.astype('float32')

    def _build_dense_index(self, texts: List[str]):
        embeddings = self._get_embeddings(texts)
        faiss.normalize_L2(embeddings)
        self.index = faiss.IndexFlatIP(embeddings.shape[1])
        self.index.add(embeddings)
        print(
            f'Successfully indexed {len(texts)} documents for Dense Retrieval.'
        )

    @staticmethod
    def _z_score_normalization(scores: List[float]) -> List[float]:
        """Apply Z-score normalization: z = (x - mean) / std."""
        if not scores: return []  # noqa: E701
        arr = np.array(scores)
        std = np.std(arr)
        if std == 0: return [0.0] * len(scores)  # noqa: E701
        mean = np.mean(arr)
        return ((arr - mean) / std).tolist()

    @staticmethod
    def _sigmoid(x: float) -> float:
        """Map Z-score to [0, 1]."""
        return 1 / (1 + math.exp(-x))

    def _validate_corpus(self, corpus: List[str] = None):
        """
        Validate and initialize corpus if needed.

        Args:
            corpus: Optional new corpus to re-initialize the retriever.

        Raises:
            ValueError: If corpus is empty or index not built.
        """
        with self._corpus_lock:
            # Only re-initialize if new corpus is provided
            if corpus is not None and corpus != self.corpus:
                self._init_corpus(corpus=corpus)
            elif self.corpus is None:
                raise ValueError(
                    'Corpus is empty. Please provide a valid corpus for searching.'
                )
            if self.index is None:
                raise ValueError('Index not built.')

    def _compute_dense_scores(self, query: str) -> List[float]:
        """
        Compute dense retrieval scores using FAISS.

        Args:
            query: The search query string.

        Returns:
            List of raw dense scores for all documents in corpus.
        """
        query_vec = self._get_embeddings([query])
        faiss.normalize_L2(query_vec)
        search_k: int = min(len(self.corpus), 500)
        dense_dists, dense_indices = self.index.search(x=query_vec, k=search_k)

        dense_scores_map = {
            idx: float(score)
            for idx, score in zip(dense_indices[0], dense_dists[0])
            if idx != -1
        }
        return [dense_scores_map.get(i, 0.0) for i in range(len(self.corpus))]

    def _compute_sparse_scores(self, query: str) -> List[float]:
        """
        Compute sparse retrieval scores using BM25.

        Args:
            query: The search query string.

        Returns:
            List of raw BM25 scores for all documents in corpus.
        """
        return self.bm25.get_scores(self.tokenizer_util.segment(query))

    def _fuse_and_normalize_scores(
        self,
        raw_dense_scores: List[float],
        raw_bm25_scores: List[float],
        alpha: float,
    ) -> List[dict]:
        """
        Normalize scores using Z-score, fuse with weighted sum, and map to [0, 1].

        Args:
            raw_dense_scores: Raw dense retrieval scores.
            raw_bm25_scores: Raw BM25 scores.
            alpha: Weight for dense component. [0.0, 1.0].

        Returns:
            List of dicts with 'text' and 'score' keys, sorted by score descending.
        """
        # Normalization (Z-score)
        norm_dense = self._z_score_normalization(raw_dense_scores)
        norm_bm25 = self._z_score_normalization(raw_bm25_scores)

        # Weighted Fusion & Range Normalization
        candidates = []
        for i in range(len(self.corpus)):
            # Weighted sum of Z-scores
            z_fused = (alpha * norm_dense[i]) + ((1.0 - alpha) * norm_bm25[i])
            # Normalize to [0, 1] using Sigmoid
            final_score = self._sigmoid(z_fused)
            candidates.append({'text': self.corpus[i], 'score': final_score})

        # Sort descending
        candidates.sort(key=lambda x: x['score'], reverse=True)
        return candidates

    def _filter_and_rank(
        self,
        candidates: List[dict],
        top_k: int,
        min_score: float,
    ) -> List[Tuple[str, float]]:
        """
        Filter candidates by minimum score and return top_k results.

        Args:
            candidates: List of candidate dicts with 'text' and 'score'.
            top_k: Maximum number of results to return.
            min_score: Minimum score threshold for filtering.

        Returns:
            List of (document, score) tuples.
        """
        total_score_sum = sum(c['score'] for c in candidates)
        if total_score_sum == 0:
            return []

        final_results = []
        for item in candidates:
            current_score: float = item['score']
            if current_score < min_score:
                continue
            final_results.append((item['text'], current_score))

        return final_results[:top_k]

    def search(
        self,
        query: str,
        corpus: List[str] = None,
        top_k: int = 3,
        min_score: float = 0.7,
        alpha: float = 0.7,
    ) -> List[Tuple[str, float]]:
        """
        Perform hybrid search (Dense + Sparse) with Z-score normalization and weighted fusion.

        Args:
            query: The search query string.
            top_k: Number of results to return (hard limit).
            alpha: Weight for dense (semantic) component. [0.0, 1.0].
                   - alpha > 0.5 favors semantic meaning.
                   - alpha < 0.5 favors BM25 lexical matching.
            min_score: Minimum score threshold for filtering. [0.0, 1.0].
                If the num of results with prob >= min_prob is less than top_k, returns all those results.
                Otherwise, returns top_k results.
            corpus: Optional new corpus to re-initialize the retriever.

        Returns:
            List of (document, combined_score) tuples, normalized to [0, 1].
        """
        # Validate and initialize corpus
        self._validate_corpus(corpus)

        # Compute dense and sparse scores
        raw_dense_scores = self._compute_dense_scores(query)
        raw_bm25_scores = self._compute_sparse_scores(query)

        # Fuse and normalize scores
        candidates = self._fuse_and_normalize_scores(raw_dense_scores,
                                                     raw_bm25_scores, alpha)

        # Filter and rank results
        return self._filter_and_rank(candidates, top_k, min_score)

    async def async_search(
        self,
        query: str,
        corpus: List[str] = None,
        top_k: int = 3,
        min_score: float = 0.7,
        alpha: float = 0.7,
    ) -> List[Tuple[str, float]]:
        """
        Perform async hybrid search (Dense + Sparse) with Z-score normalization and weighted fusion.

        Args:
            query: The search query string.
            top_k: Number of results to return (hard limit).
            alpha: Weight for dense (semantic) component. [0.0, 1.0].
                   - alpha > 0.5 favors semantic meaning.
                   - alpha < 0.5 favors BM25 lexical matching.
            min_score: Minimum score threshold for filtering. [0.0, 1.0].
                If the num of results with prob >= min_prob is less than top_k, returns all those results.
                Otherwise, returns top_k results.
            corpus: Optional new corpus to re-initialize the retriever.

        Returns:
            List of (document, combined_score) tuples, normalized to [0, 1].
        """
        # Validate and initialize corpus
        self._validate_corpus(corpus)

        # Compute dense and sparse scores concurrently
        dense_task = asyncio.to_thread(self._compute_dense_scores, query)
        sparse_task = asyncio.to_thread(self._compute_sparse_scores, query)

        raw_dense_scores, raw_bm25_scores = await asyncio.gather(
            dense_task, sparse_task)

        # Fuse and normalize scores
        candidates = self._fuse_and_normalize_scores(raw_dense_scores,
                                                     raw_bm25_scores, alpha)

        # Filter and rank results
        return self._filter_and_rank(candidates, top_k, min_score)
