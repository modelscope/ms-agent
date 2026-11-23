# Memory

Memory retains information worth reusing across turns and sessions. It differs from the original records in a [session log](sessions.md) and the input-length management performed by [context strategies](context.md). Extraction, retrieval, and visibility depend on the backend.

## One contract, replaceable backends

```{mermaid}
flowchart TD
  A[Agent lifecycle] --> B[MemoryOrchestrator]
  B --> C[MemoryBackend protocol]
  C --> D[File backend]
  C --> E[Retrieval or external adapters]
  C --> F[Custom backend]
  G[Registry and configuration] --> B
```

`MemoryOrchestrator` delegates injection, ingestion, pre-compaction handling, search, and shutdown. `MemoryBackend` is the public contract; `BaseMemoryBackend` supplies defaults for optional methods. Internal storage/extraction components are not additional required public interfaces.

The repository includes adapters for `file`, `reme`, `mempalace`, `mem0`, `byterover`, and `supermemory`. Dependencies, credentials, and service requirements differ. Adapter code existing does not mean the environment is ready or every external integration has been tested.

## Start with file memory

```yaml
memory:
  unified_memory:
    enabled: true
    storage:
      backend: file
      file:
        memory_path: MEMORY.md
        char_limit: 2200
    ingest_interval: 1
```

When loaded through this configuration path without `base_dir`, memory is rooted at `.ms_agent/memory` under the working directory. The WebUI can configure separate scopes. Bounded file memory does not automatically copy every conversation into MEMORY.md. See [Memory management](../user-guide/memory.md).

## Minimal custom backend

```python
from copy import deepcopy
from ms_agent.memory.unified import BaseMemoryBackend, backend_registry

class DemoBackend(BaseMemoryBackend):
    def __init__(self, config):
        self.config = config

    async def start(self, **kwargs):
        pass

    async def inject(self, messages):
        return deepcopy(messages)

    async def close(self):
        pass

backend_registry.register('demo', DemoBackend)
assert backend_registry.resolve('demo') is DemoBackend
```

Import the registration module before configuration is loaded, then select `storage.backend: demo`. This example demonstrates the contract without persistence. A real backend implements ingestion, search, tools, or compaction callbacks as needed, and closes connections and locks it owns.

## Extraction before compaction

Before compaction, long-term facts can be extracted from original messages using the actual memory model's budget, with room for prompts, existing memory, and output. Oversized input is split into chunks. The file backend's default `char_limit: 2200` bounds the final file in characters, not the model's token window.

Results distinguish `updated`, `unchanged`, `skipped`, and `failed`. All chunks must succeed before replacing the memory file. Ordinary failure preserves old memory and original message sequences for a later retry without blocking a valid summary. User cancellation stops the operation. Memory and logs are written separately, so crash recovery may repeat extraction; this is not a cross-store transaction.

## Writing, sharing, and limits

- Ingestion after a complete reply can run in the background. Messages are snapshotted and the deduplication ledger advances after successful ingestion. “Scheduled” is not “saved.”
- Shutdown and reconfiguration coordinate pending tasks and storage locks. Multiple sessions may share a store; avoid independently opening competing embedded-database instances.
- File content, recall blocks, and prompt snapshots have different refresh behavior. Verify what the next turn or session sees after editing.
- Some projects still use `context_compressor`, `refine_condenser`, or `code_condenser`; do not remove those compatibility paths indiscriminately.
- Keep secrets, complete private files, and unnecessary raw logs out of memory. Remote backends may transmit content to external services.

Implementation: `memory/unified/protocols.py`, `registry.py`, `orchestrator.py`, `backends/`. Next: [Personalization](personalization.md), [Storage](../development/storage.md).
