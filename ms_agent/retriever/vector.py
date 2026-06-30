# Copyright (c) ModelScope Contributors. All rights reserved.
"""Dense vector retriever using FAISS + sentence-transformers.

All heavy imports (``faiss``, ``sentence_transformers``, ``numpy``) are
**lazy-loaded** so that the module can be imported without pulling in
large dependencies when only BM25 is needed.
"""
from typing import List, Optional

from .base import BaseRetriever, SearchResult


class VectorRetriever(BaseRetriever):
    """Dense retriever backed by a FAISS flat inner-product index.

    The embedding model is loaded on first ``index()`` or ``search()`` call
    and cached for the lifetime of the instance.
    """

    DEFAULT_MODEL = (
        'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')

    def __init__(self, embed_model: Optional[str] = None):
        self._embed_model_id = embed_model or self.DEFAULT_MODEL
        self._model = None       # SentenceTransformer (lazy)
        self._index = None       # faiss.IndexFlatIP  (lazy)
        self._documents: List[str] = []
        self._doc_ids: List[str] = []

    # ------------------------------------------------------------------ #
    #  Lazy initialisation helpers
    # ------------------------------------------------------------------ #

    def _ensure_model(self):
        if self._model is not None:
            return
        try:
            from modelscope import snapshot_download
            local_path = snapshot_download(
                model_id=self._embed_model_id,
                ignore_patterns=[
                    'openvino/*', 'onnx/*', 'pytorch_model.bin',
                    'rust_model.ot', 'tf_model.h5',
                ])
        except Exception:
            local_path = self._embed_model_id

        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(local_path)

    def _encode(self, texts: List[str]):
        import numpy as np
        self._ensure_model()
        embeddings = self._model.encode(texts, convert_to_numpy=True)
        return embeddings.astype(np.float32)

    # ------------------------------------------------------------------ #
    #  BaseRetriever interface
    # ------------------------------------------------------------------ #

    def index(self, documents: List[str],
              doc_ids: Optional[List[str]] = None) -> None:
        import faiss
        self.reset()
        self._documents = list(documents)
        self._doc_ids = (
            list(doc_ids) if doc_ids else
            [str(i) for i in range(len(documents))])

        embeddings = self._encode(self._documents)
        faiss.normalize_L2(embeddings)
        self._index = faiss.IndexFlatIP(embeddings.shape[1])
        self._index.add(embeddings)

    def search(self, query: str, top_k: int = 10) -> List[SearchResult]:
        import faiss
        import numpy as np
        if self._index is None or not self._documents:
            return []

        q_vec = self._encode([query])
        faiss.normalize_L2(q_vec)
        k = min(top_k, len(self._documents))
        dists, indices = self._index.search(q_vec, k)

        results: List[SearchResult] = []
        for dist, idx in zip(dists[0], indices[0]):
            if idx == -1:
                continue
            results.append(SearchResult(
                doc_id=self._doc_ids[idx],
                text=self._documents[idx],
                score=float(dist),
            ))
        return results

    def reset(self) -> None:
        self._index = None
        self._documents.clear()
        self._doc_ids.clear()
