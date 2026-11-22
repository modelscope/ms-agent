# Configuration reference

Read [Configuration](../core/configuration.md) for locations and precedence. This page covers major configuration surfaces, distinguishing code defaults from bundled YAML. Domain applications can define additional fields.

## Execution and lifecycle

| Field | Type | Default/meaning |
| --- | --- | --- |
| type | str | General agents use llmagent; codeagent and workflows have their own loader types |
| code_file | str | Custom Python agent, loaded with explicit trust and preferred over ordinary type selection |
| output_dir | str | SDK defaults to cwd; application YAMLs may select ./output |
| max_chat_round | int | Class default 20; bundled general YAML 9999; TUI can adjust interactive budgets |
| interactive | bool | Interaction mode; entry/input determines behavior when omitted |
| callbacks | list[str] | Lifecycle callbacks; general YAML includes input_callback |
| config_handler | str | Configuration lifecycle handler; external code requires trust |
| tool_call_timeout | number | 120 seconds by default |
| tool_call_timeout_max | number | Default 600-second timeout ceiling |
| save_history | bool | Legacy history-cache option, distinct from SessionLog |
| enable_snapshots | bool | File snapshots where supported by tools/interfaces |
| index_cache_dir | str | Custom index cache, separate from work files |

A field existing does not prove a feature is active. Some components require valid model/path/backend configuration before assembly.

## Models and generation

| Field | Type | Meaning |
| --- | --- | --- |
| llm.service | str | Provider name/alias |
| llm.model | str | A model ID served by the endpoint |
| llm.use_provider_router | bool | Explicit provider/legacy route selection; otherwise service defaults apply |
| llm.protocol | str | Protocol override supported by the selected route |
| llm.api_key / base_url | str | Generic provider fields; legacy routes also use service-specific fields |
| llm.openai_api_key / openai_base_url | str | OpenAI-compatible configuration |
| llm.modelscope_api_key / modelscope_base_url | str | ModelScope legacy configuration |
| llm.anthropic_api_key / anthropic_base_url | str | Anthropic legacy configuration |
| llm.supports_vision | bool or unset | Model vision choice; unset can use provider/runtime capability |
| llm.vision | mapping | Encoding, dimensions, transcoding, auxiliary vision |
| generation_config | mapping | Sampling, streaming, tokens, service extensions; protocol-specific |
| prompt.system | str | Replace the base system layer, not every assembled layer |
| prompt.query | str | Initial task input |

Bundled examples use temperature 0.3, top_k 20, and stream true. This does not guarantee validity for every model. Unknown fields may be filtered, and `extra_body` requires service support. See [Models](../core/models.md) and [Multimodal](../core/multimodal.md).

## Tools, skills, and extensions

| Field | Type | Meaning |
| --- | --- | --- |
| tools | mapping | Built-in tools or MCP servers |
| tools.NAME.mcp | bool | Built-ins need false; omitted values may select MCP |
| tools.NAME.include / exclude | list[str] | Mutually exclusive filters |
| tools.NAME.enabled | bool | Enable where supported by the component/configuration layer |
| tools.plugins | list[str] | Custom Python tool files relative to configuration; distinct from top-level plugin resources |
| tools.code_executor.implementation | str | python_env selects local execution; others need sandbox configuration |
| tools.localsearch.paths | list[str] | Actual local-search roots |
| knowledge_search_paths | str | Compatible comma-separated CLI roots mapped to localsearch |
| skills.sources | list[mapping] | Structured type/path/repo_id and related source fields |
| skills.auto_discover | bool | Default false; not a switch disabling every live tree |
| skills.disabled / whitelist | list[str] | Filter runtime skill IDs |
| skills.enable_manage | bool | Expose management tools separately from loading |
| skills.prompt_injection | str | all / always_only / none |
| skills.update_notice | bool | Default false; stabilizes skill summaries only |
| skills.search | mapping | BM25/vector/hybrid selection and dependencies |
| skills.safety | mapping | Enabling, trust policy, optional LLM checks |
| hooks | mapping | Event→matcher groups→handlers; command executor currently implemented |
| plugins | mapping or entry-specific configuration | Resource assembly and scoped management |
| acp_agents / a2a_agents | mapping | Separate remote-agent connection schemas |

```yaml
tools:
  file_system:
    mcp: false
    include: [read_file, glob, grep]
skills:
  sources:
    - type: local
      path: ./skills
```

## Sessions, context, and memory

| Block | Main fields | Meaning |
| --- | --- | --- |
| session_log | enabled, dir, context_limit, reserved_buffer | Recording and budgets; interfaces can override storage |
| compaction | enabled, context_limit, reserved_buffer, strategies | Built-in pruning/summarization; YAML recognizes built-in names only |
| unified_memory or memory.unified_memory | enabled, storage, base_dir, ingest_interval, recall_top_k | Backend selection; loading path affects default directory |
| Legacy memory compressors | context_compressor, refine_condenser, code_condenser | Still used by some applications |
| personalization | enabled, global_instruction, project_instruction | File-first with legacy fallback; bundled YAML enables, parser defaults false |
| rag | name, embedding, chunk_size, chunk_overlap, retrieve_only, storage_dir | Traditional RAG, separate from on-demand localsearch |

Common context budgets are 128000, reserved space 20000, and recent-tool protection 40000. Match them to the actual model rather than treating budgets as provider capabilities. See [Memory](../core/memory.md) for backend fields and lifecycle examples.

## Permissions

`permission.mode` accepts auto/strict/interactive; restricted is an alias. `whitelist/blacklist/ask_rules` express outer policy. Safety `patterns`, `sensitive_paths`, `sensitive_read_paths`, and `dangerous_removal_paths` **replace default lists**; omit them to retain defaults.

`allowed_directories/read_only_directories` control paths; `allow_temp_dir` defaults true; `path_validation.read_policy` is loose/strict and `max_command_chars` defaults 8192. Coverage depends on execution paths; see [Permissions](../core/permissions.md).

## Environment and secrets

Use dotenv/process variables for credentials. Environment overrides do not create arbitrary nested tool fields without restriction. WebUI loading and CLI `--env` differ; identify the entry point first. Never log complete resolved configurations publicly.

Implementation: `config/config.py`, `resolver.py`, `llm/spec.py`, `permission/config.py`, `memory/unified/config.py`, and individual modules.
