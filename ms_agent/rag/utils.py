# Copyright (c) ModelScope Contributors. All rights reserved.
from .llama_index_rag import LlamaIndexRAG

rag_mapping = {
    'LlamaIndexRAG': LlamaIndexRAG,
}

# Note: SirchmunkSearch is registered in knowledge_search module
# and integrated directly in LLMAgent, not through rag_mapping
