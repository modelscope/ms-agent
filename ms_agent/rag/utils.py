# Copyright (c) ModelScope Contributors. All rights reserved.
from .llama_index_rag import LlamaIndexRAG

rag_mapping = {
    'LlamaIndexRAG': LlamaIndexRAG,
}

# Note: Sirchmunk local search is the ``localsearch`` tool
# (ms_agent.tools.search); it is not wired through rag_mapping.
