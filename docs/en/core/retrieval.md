# Retrieval

Local retrieval lets the model find evidence in configured files when needed. It differs from web search and from the [RAG](rag.md) path that enriches a query with indexed material.

## Enable on-demand local search

```yaml
tools:
  localsearch:
    mcp: false
    paths: [./src, ./docs]
    mode: FAST
```

Or use the CLI:

```bash
ms-agent run --query 'Explain configuration loading' --knowledge_search_paths './src,./docs'
```

Paths must exist. Calls can narrow to files/subdirectories within configured roots; this is not authorization to read arbitrary server files. Search reuses the agent model unless `llm_api_key`, `llm_base_url`, and `llm_model_name` are configured separately.

## Queries and evidence

The model invokes `localsearch` when relevant, rather than automatically searching every turn. Cite returned paths/snippets and read originals when necessary. Legacy `knowledge_search` configuration remains compatible; prefer the tool block for new configurations.

Indexes, caches, and original files are different assets. Check refresh behavior after changes rather than treating stale matches as current facts. Large results may be shortened or written to artifact files.

## Related retrieval mechanisms

| Mechanism | Searches |
| --- | --- |
| localsearch | Local code and documents |
| web_search | External search engines |
| Skill retrieval | Available skills |
| Memory recall | Durable cross-task knowledge |
| RAG | Indexed material for answer augmentation |

Keyword, vector, and reranking backends have different costs/dependencies. Basic reading does not require installing every heavy dependency. Installation/import checks are not retrieval-quality validation.

Next: [RAG](rag.md), [Tools](tools.md). Implementation: `tools/search/localsearch_tool.py`, `sirchmunk_search.py`, `retriever/`.
