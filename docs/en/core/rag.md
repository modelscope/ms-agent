# RAG

RAG connects document indexing, retrieval, and answer augmentation. The repository retains a LlamaIndex-based implementation. It is a different integration from on-demand `localsearch`; enabling one does not enable the other.

## Interface and flow

The `RAG` abstraction defines asynchronous `add_documents()`, `query()`, and `retrieve()`. Implementations own chunking, embedding, index persistence, and querying.

```{mermaid}
flowchart TD
 A[Documents] --> B[Load and split]
 B --> C[Embed and index]
 D[Question] --> E[Retrieve relevant passages]
 C --> E
 E --> F[Return passages or generate augmented answer]
```

## Configure LlamaIndex

```{warning}
Current `LLMAgent.prepare_rag()` calls the `rag_mapping` dictionary as a function, raising `TypeError: 'dict' object is not callable` when RAG is configured. The fragment below documents the schema, not a verified working Agent path. Fix and validate that integration before using it, or instantiate the RAG implementation explicitly in your application. Use `localsearch` for ordinary on-demand retrieval. This documentation change does not alter SDK code.
```

Direct implementation use still requires valid LLM and LlamaIndex/embedding dependencies. First use may download a model:

```yaml
rag:
  name: LlamaIndexRAG
  embedding: Qwen/Qwen3-Embedding-0.6B
  chunk_size: 512
  chunk_overlap: 50
  retrieve_only: false
```

Without `storage_dir`, the implementation uses `.ms_agent/search_index/rag` in the workspace. The old `./llama_index` default in historical prose should not be assumed.

Configuration selects an implementation; it does not create source material. Add/load documents and build an index before querying. `retrieve_only` selects retrieval without generation; do not also depend on a generated query answer.

## Costs and limits

Chunk size, overlap, and embedding choice affect indexing cost and recall. A different embedding model generally requires a compatible index. Preserve original data/configuration before rebuilding instead of reusing incompatible vectors.

Traditional Agent RAG enriches the initial user input; on-demand search is a separate tool. Generated summaries do not replace source citations or prove complete coverage. Manage third-party global settings and resources carefully when running different configurations concurrently.

Next: [Retrieval](retrieval.md), [Context](context.md). Implementation: `rag/base.py`, `rag/llama_index_rag.py`, `LLMAgent.do_rag()`.
