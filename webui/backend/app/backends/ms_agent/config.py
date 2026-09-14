"""Assemble the per-session run config and construct the LLMAgent (Route A).

Uses the SDK ConfigResolver.resolve() for the layered config
(framework -> WebUI defaults -> settings.json -> project -> session),
then route-A shaping (interactive lifecycle, streaming, session-log dir), then
the managed MCP/skills bridge, then LLMAgent with the UI seams injected.
"""
from __future__ import annotations

import logging
import os
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from app.backends.ms_agent.common import home
from app.backends.ms_agent.defaults import DEFAULT_TOOLS, RETIRED_TOOLS

logger = logging.getLogger("app.ms_agent.config")
_model_snapshot = ContextVar("webui_model_snapshot", default=None)

# mem0 2.x opens a SECOND, process-global qdrant store at
# ~/.mem0/migrations_qdrant for every Memory instance whose vector provider is
# qdrant (mem0/memory/main.py, `if MEM0_TELEMETRY:`). Embedded qdrant takes an
# exclusive OS file lock per path, so that global store caps the whole machine
# at one live vector project — the second one dies with "Storage folder ... is
# already accessed by another instance". Turning telemetry off skips the branch
# entirely (and stops mem0 phoning home to PostHog).
#
# mem0's telemetry module reads this at ITS import time, so it has to be set
# before the first `import mem0`. Module scope is early enough: every mem0
# import in this repo is lazy (`_vector_memory_available` below, `memory.py`,
# and the SDK's mem0_adapter.start()), and memory.py imports this module first.
os.environ.setdefault("MEM0_TELEMETRY", "false")


def _apply_webui_defaults(config):
    """Make a newly-created WebUI session useful without requiring a hand-written
    agent.yaml. Project/global config can still override these keys."""
    from omegaconf import OmegaConf

    if OmegaConf.select(config, "skills", default=None) is None:
        OmegaConf.update(config, "skills", {}, merge=True)
    for key, value in {
        "skills.prompt_injection": "all",
        "skills.auto_discover": True,
        "skills.enable_manage": False,
        "skills.disabled": [],
        # Skill changes are announced as in-conversation <system-reminder>
        # notices (chat._maybe_skill_notice); the SDK then keeps the system
        # prompt byte-stable per session (head_refresh_enabled=False) so the
        # provider prefix cache never breaks on a skill change.
        "skills.update_notice": True,
    }.items():
        if OmegaConf.select(config, key, default=None) is None:
            OmegaConf.update(config, key, value, merge=True)
    # Retired WebUI tools must not reappear after an import performed at runtime.
    for name in RETIRED_TOOLS:
        config.tools.pop(name, None)
    return config


def _vector_memory_available() -> bool:
    """The 'vector' project backend maps to the SDK's mem0 adapter (`mem0ai`
    is a backend dependency; the guard keeps a broken install non-fatal)."""
    try:
        import mem0  # noqa: F401

        return True
    except Exception:
        return False


class MemoryConfigError(RuntimeError):
    """Vector memory cannot be built as configured.

    ``code`` is machine-readable for the UI:
    - ``embed_unavailable``: no usable embeddings endpoint (provider serves
      none / credentials missing) and no local fallback;
    - ``local_missing``: local mode chosen but fastembed is not installed;
    - ``local_model_unavailable``: fastembed is installed but the model itself
      cannot be loaded — on first use it is downloaded (~220 MB), so this is
      normally a network/proxy problem rather than a configuration one;
    - ``embedder_mismatch``: the store was built with a different embedding
      model — searching across a model swap silently degrades recall, so we
      refuse and offer a rebuild instead.
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


# Embedding models known to work per provider, verified against the exact call
# shape mem0 sends (``dimensions`` + ``encoding_format=float``). A provider
# absent here serves no /embeddings at all (verified: DeepSeek and Moonshot
# 403 it, MiniMax returns no data, a custom Aliyun MaaS endpoint 400s
# "Model not exist") — which is why "just use the chat provider" needs a
# fallback: about half of the chat providers cannot embed.
_KNOWN_EMBED_MODELS: dict[str, str] = {
    "dashscope": "text-embedding-v4",
    "openai": "text-embedding-3-small",
    "modelscope": "Qwen/Qwen3-Embedding-4B",
    "zhipu": "embedding-3",
    "openrouter": "openai/text-embedding-3-small",
}

# The bundled offline default: the lightest multilingual model fastembed
# ships (384 dims, ~220 MB one-time download, ONNX — no network at runtime).
_LOCAL_EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

_EMBEDDER_IDENTITY_FILE = "embedder.json"


def _read_settings() -> dict:
    snapshot = _model_snapshot.get()
    if snapshot is not None:
        return snapshot.settings
    from pathlib import Path
    from ms_agent.utils.json_store import read_json
    return read_json(Path(home()) / "settings.json")


def _read_metadata(section: str, key: str, default=None):
    snapshot = _model_snapshot.get()
    if snapshot is not None:
        return snapshot.metadata.get(section, {}).get(key, default)
    from app.backends.ms_agent import sidecar
    return sidecar.get(section, key) if default is None else sidecar.get(section, key, default)


def _local_embed_available() -> bool:
    """fastembed ships as the optional `local-embed` extra (it drags in
    onnxruntime); absence is a normal state the UI must explain, not a bug."""
    try:
        import fastembed  # noqa: F401

        return True
    except Exception:
        return False


def _project_memory_models(project) -> dict:
    """The PROJECT's memory-model choices, materialized into its sidecar at
    creation. The global settings block only seeds new projects (modal
    prefill) — it is deliberately never read here, so changing a global
    default cannot ripple through existing stores (which are pinned to their
    embedder by identity anyway). Absent (legacy project) = follow defaults.

    One value is filled in rather than read: a project saved WITHOUT an
    embedding provider ("follow the conversation provider", the option the UI
    no longer offers) adopts the provider its store was actually built with.
    Otherwise the embedder would track a global setting — switching models
    while chatting in another project would silently invalidate this one's
    store and ask the user to re-embed for no reason.
    """
    from app.backends.ms_agent import sidecar

    meta = _read_metadata("projects", getattr(project, "id", None) or "", {}) or {}
    cfg = dict(meta.get("memory_models") or {})
    if (getattr(project, "path", None)
            and cfg.get("embed_mode", "provider") != "local"
            and not cfg.get("embed_provider_id")):
        stored = _load_embedder_identity(project) or {}
        pinned = stored.get("provider")
        if pinned and pinned != "local":
            cfg["embed_provider_id"] = pinned
            cfg.setdefault("embed_model", stored.get("model"))
        elif pinned == "local":
            cfg["embed_mode"] = "local"
            cfg.setdefault("embed_model", stored.get("model"))
    return cfg


def _resolve_embedder(settings: dict, mem_cfg: dict) -> dict:
    """Decide where embeddings come from. Never guesses silently:

    1. explicit local mode -> the local model (error if not installed);
    2. explicit provider -> exactly that provider (error if it cannot embed —
       the user pinned it, switching behind their back is the old bug);
    3. no provider pinned -> the CONVERSATION provider if it is known to embed,
       else the local model, else a clear error. ``fallback_reason`` records a
       taken fallback so the UI can say why.

    Case 3 only ever decides the FIRST build: the choice is recorded in the
    store's identity file, and ``_project_memory_models`` pins the project to it
    from then on. The UI no longer offers "follow the conversation provider" —
    the conversation provider is a global setting, so following it meant that
    switching models while chatting in one project invalidated another
    project's store.
    """
    providers = settings.get("providers") or {}
    mode = mem_cfg.get("embed_mode") or "provider"

    def _local(reason: str | None = None) -> dict:
        if not _local_embed_available():
            raise MemoryConfigError(
                "local_missing",
                "local embedding model is not installed — run "
                "`uv sync --extra local-embed` in backend/ and restart",
            )
        return {
            "mode": "local",
            "provider": None,
            "model": mem_cfg.get("embed_model") or _LOCAL_EMBED_MODEL,
            "fallback_reason": reason,
        }

    if mode == "local":
        return _local()

    explicit_pid = mem_cfg.get("embed_provider_id")
    pid = explicit_pid or (settings.get("llm") or {}).get("provider") or ""
    entry = providers.get(pid) or {}
    model = mem_cfg.get("embed_model") or _KNOWN_EMBED_MODELS.get(pid)
    if entry.get("api_key") and entry.get("base_url") and model:
        return {
            "mode": "provider",
            "provider": pid,
            "model": model,
            "api_key": entry["api_key"],
            "base_url": entry["base_url"],
            "fallback_reason": None,
        }

    if explicit_pid:
        raise MemoryConfigError(
            "embed_unavailable",
            f"provider {pid!r} cannot serve embeddings as configured "
            "(missing credentials or no known embedding model — set one "
            "explicitly in settings → personalization)",
        )
    # Following the conversation provider and it cannot embed: fall back to
    # the local model rather than silently billing some other vendor.
    reason = (
        f"provider {pid!r} serves no embeddings; using the local model"
        if pid else "no conversation provider configured; using the local model"
    )
    return _local(reason)


def _embedder_identity_path(project):
    from ms_agent.project.paths import memory_dir

    return memory_dir(project.path) / _EMBEDDER_IDENTITY_FILE


def _load_embedder_identity(project) -> dict | None:
    import json

    try:
        with open(_embedder_identity_path(project), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) and data.get("model") else None
    except (OSError, ValueError):
        return None


def _stage_embedder_identity(project, identity: dict):
    """Write the identity to a temp file NEXT TO its target and return the path.

    Split from the commit so a rebuild can prove it is able to record the new
    identity *before* it moves any store: promoting the temp file afterwards is
    a rename within one directory, which is atomic and cannot half-succeed.
    Raises :class:`OSError` — the caller must not swallow it, because a store
    that speaks model B under an identity file that still says model A reads as
    a mismatch forever and disables the project's memory.
    """
    import json
    import os
    import tempfile

    path = _embedder_identity_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".embedder.",
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(identity, ensure_ascii=False, indent=2) + "\n")
    except BaseException:
        os.unlink(tmp)
        raise
    return Path(tmp)


def _commit_embedder_identity(project, staged) -> None:
    """Promote a staged identity into place (atomic rename)."""
    import os

    os.replace(str(staged), str(_embedder_identity_path(project)))


def _store_embedder_identity(project, identity: dict) -> None:
    """Record the identity now, best-effort (first build of a store).

    Best-effort is fine here and only here: there is no store yet to be
    mislabelled, and the next build simply records it again.
    """
    try:
        _commit_embedder_identity(project,
                                  _stage_embedder_identity(project, identity))
    except OSError as e:  # bookkeeping must never break memory itself
        logger.warning("embedder identity write failed for %s: %s",
                       _embedder_identity_path(project), e)


def _probe_embed_dimension(desc: dict) -> tuple[int, bool]:
    """``(dimension, provider_accepts_dimensions_param)`` for the resolved
    embedder — measured, not assumed (mempalace's RFC 001 approach): the
    width is baked into the qdrant collection at creation, and a hardcoded
    table goes stale the moment a vendor changes a default.

    Providers are probed twice: once bare (native width), once passing
    ``dimensions=<native>`` — mem0 sends that argument whenever
    ``embedding_dims`` is configured, and non-matryoshka backends reject it,
    so we only configure it when the probe proved it is accepted.
    """
    if desc["mode"] == "local":
        from fastembed import TextEmbedding

        for m in TextEmbedding.list_supported_models():
            if m.get("model") == desc["model"] and m.get("dim"):
                return int(m["dim"]), False
        # Unknown to the table — load the model once and measure. Loading may
        # download; give the ModelScope path its chance first (no-op when the
        # cache is already warm or the source is switched off).
        from app.backends.ms_agent import embed_warmup
        from app.core.settings import settings as app_settings

        embed_warmup.warm_local_memory_models(desc["model"],
                                          app_settings.ms_agent_embed_model_source)
        return int(TextEmbedding(model_name=desc["model"]).embedding_size), False

    from openai import OpenAI

    client = OpenAI(
        api_key=desc["api_key"], base_url=desc["base_url"],
        timeout=30, max_retries=0)
    native = len(
        client.embeddings.create(
            model=desc["model"], input="dimension probe").data[0].embedding)
    try:
        echoed = len(
            client.embeddings.create(
                model=desc["model"], input="dimension probe",
                dimensions=native).data[0].embedding)
        return native, echoed == native
    except Exception:
        return native, False


def _openai_compat_base_url(provider: str) -> str | None:
    """The vendor's canonical OpenAI-compatible endpoint, per the SDK registry.

    settings.json may hold a different-protocol url for the same vendor —
    DeepSeek ships both ``/v1`` and ``/anthropic`` — while mem0's per-vendor
    clients are OpenAI clients underneath. So take the registry's value rather
    than doing string surgery on whatever the user configured. Returns None for
    vendors that are not OpenAI-compatible at all (real Anthropic), where the
    configured url is the right one. Same lookup as ``model_link``."""
    try:
        from ms_agent.llm.spec import TRANSPORT_OPENAI_COMPAT, get_registry
    except Exception:  # pragma: no cover - import guard
        return None
    spec = get_registry().get(provider)
    if spec is None or spec.transport != TRANSPORT_OPENAI_COMPAT:
        return None
    return spec.default_base_url or None


def _mem0_base_url_key(provider: str) -> str | None:
    """mem0's base-url field name for a native provider (``deepseek_base_url``,
    ``anthropic_base_url``, …), or None if it takes no such argument.

    Introspected rather than hardcoded: the set of native providers moves
    between mem0 versions, and an unrecognised kwarg is a TypeError at config
    construction, not a warning."""
    import inspect

    try:
        from mem0.utils.factory import LlmFactory

        config_cls = LlmFactory.provider_to_class[provider][1]
        params = inspect.signature(config_cls.__init__).parameters
    except Exception:  # pragma: no cover - unknown provider / mem0 layout change
        return None
    key = f"{provider}_base_url"
    return key if key in params else None


def _mem0_llm(settings: dict, mem_cfg: dict | None = None) -> dict | None:
    """The mem0 ``llm`` block used for per-round fact extraction.

    Defaults to the CONVERSATION model; an explicit choice in settings →
    personalization (``memory_llm_provider_id``/``memory_llm_model``) pins
    extraction to a model of the user's own, decoupled from what chat uses.

    The chosen model may be reached over the Anthropic protocol (DeepSeek's
    ``/anthropic`` endpoint, for one). Declaring that as mem0's ``openai``
    provider — which this used to do unconditionally — makes mem0 POST
    ``/anthropic/chat/completions`` and take a 404, silently: extraction
    writes nothing and the memory panel stays empty forever. Resolve the
    protocol instead of assuming it:

    1. the provider already speaks OpenAI → mem0's ``openai`` provider;
    2. else mem0 has a native provider of the same name → use it, with the
       vendor's OpenAI-compatible url from the SDK registry;
    3. else None — mem0 falls back to its own default, and we warn, because
       picking a different vendor would mean guessing a model name it serves.
    """
    mem_cfg = mem_cfg or {}
    override_pid = mem_cfg.get("llm_provider_id")
    override_model = mem_cfg.get("llm_model")
    if override_pid and override_model:
        entry = (settings.get("providers") or {}).get(override_pid) or {}
        # Synthesize the same shape the follow-conversation path reads, so
        # both flow through one protocol-resolution body below.
        llm = {
            "provider": override_pid,
            "model": override_model,
            "api_key": entry.get("api_key"),
            "base_url": entry.get("base_url"),
        }
    else:
        llm = settings.get("llm") or {}
    model = llm.get("model")
    if not model:
        return None
    pid = llm.get("provider") or ""
    entry = (settings.get("providers") or {}).get(pid) or {}
    api_key = llm.get("api_key") or entry.get("api_key")
    if not api_key:
        logger.warning("no api key for memory fact extraction (provider %r)", pid)
        return None

    if entry.get("protocol") == "openai":
        base_url = llm.get("base_url") or entry.get("base_url")
        if base_url:
            return {
                "provider": "openai",
                "config": {
                    "model": model,
                    "api_key": api_key,
                    "openai_base_url": base_url,
                },
            }

    base_url_key = _mem0_base_url_key(pid)
    if base_url_key is not None:
        config = {"model": model, "api_key": api_key}
        base_url = _openai_compat_base_url(pid) or entry.get("base_url")
        if base_url:
            config[base_url_key] = base_url
        return {"provider": pid, "config": config}

    logger.warning(
        "provider %r speaks %r and mem0 has no native adapter for it; leaving "
        "the fact-extraction LLM to mem0's default — vector memory will likely "
        "not be written",
        pid,
        entry.get("protocol") or "unknown",
    )
    return None


def ensure_embedder_usable(desc: dict) -> None:
    """Materialize the embedder so an unusable one fails HERE.

    Only the local mode needs it: fastembed downloads its ONNX model on first
    use (~220 MB), and until that finishes nothing can be embedded. The
    dimension probe alone does not catch this — it answers from fastembed's
    static model table without touching the model — so a rebuild used to sail
    past this point, retire the project's runtimes, and only then die inside
    the re-embedding step with a bare ``[Errno 60] Operation timed out``.

    BLOCKING (loads/downloads a model): call it from a thread.
    """
    if desc.get("mode") != "local":
        return
    from fastembed import TextEmbedding

    from app.backends.ms_agent import embed_warmup
    from app.core.settings import settings as app_settings

    # Fetch the model from ModelScope first (the default): fastembed's own
    # download source is HuggingFace-only, which is unreachable on many of the
    # networks this runs on. A warm cache short-circuits fastembed's downloader
    # entirely; a failed warm-up falls through to it unchanged.
    embed_warmup.warm_local_memory_models(desc["model"],
                                      app_settings.ms_agent_embed_model_source)
    try:
        TextEmbedding(model_name=desc["model"])
    except Exception as exc:
        raise MemoryConfigError(
            "local_model_unavailable",
            f"the local embedding model ({desc['model']}) could not be "
            f"loaded: {exc}. It is downloaded on first use (~120–220 MB) — "
            f"check the network to modelscope.cn (or huggingface.co, the "
            f"fallback source) and try again",
        )


def _new_embedder_identity(desc: dict) -> dict:
    """A fresh identity for ``desc``, dimension measured. Touches no disk: the
    caller decides when it becomes the store's recorded identity — a rebuild
    may only record it once the new vectors are actually in place."""
    import time as _time

    dims, pass_dims = _probe_embed_dimension(desc)
    return {
        "provider": desc.get("provider") or "local",
        "model": desc["model"],
        "dimension": dims,
        "pass_dimensions": pass_dims,
        "created_at": _time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }


def _resolve_embedder_identity(project, desc: dict) -> dict:
    """The store's embedder identity: recorded once, then enforced.

    The identity file (``<project>/.ms_agent/memory/embedder.json``) pins
    which model produced the store's vectors. Checked at build time — before
    any query — so a model swap fails fast with a rebuild path instead of
    silently mixing vector spaces (mixed spaces don't error, they just make
    recall garbage). A store predating the identity file adopts the current
    embedder with a warning: its vectors cannot be attributed after the fact.
    """
    from ms_agent.project.paths import memory_dir

    current = {"provider": desc.get("provider") or "local", "model": desc["model"]}
    stored = _load_embedder_identity(project)
    if stored is not None:
        if (stored.get("provider"), stored.get("model")) != (
                current["provider"], current["model"]):
            raise MemoryConfigError(
                "embedder_mismatch",
                f"this project's memory was built with "
                f"{stored.get('provider')}/{stored.get('model')} but the "
                f"current embedder is {current['provider']}/{current['model']}"
                " — searching across a model swap silently degrades recall. "
                "Rebuild the memory store to switch.",
            )
        return stored

    identity = _new_embedder_identity(desc)
    if (memory_dir(project.path) / "qdrant").exists():
        identity["adopted_existing_store"] = True
        logger.warning(
            "project %s has a vector store predating embedder identity "
            "tracking; adopting %s/%s for it",
            project.id, current["provider"], current["model"])
    _store_embedder_identity(project, identity)
    return identity


def _mem0_options(project) -> dict:
    """mem0 backend options for a 'vector' project.

    - embedder: resolved by ``_resolve_embedder`` (explicit choice →
      conversation provider → local model), identity-checked against the
      store it is about to write into;
    - llm (fact extraction): see ``_mem0_llm``;
    - vector_store: local on-disk qdrant under the project memory dir
      (embedded mode — no server; see the MEM0_TELEMETRY note at module top).

    Raises :class:`MemoryConfigError` when vector memory cannot be built as
    configured — callers decide whether that surfaces (API) or degrades
    (agent build)."""
    settings = _read_settings()
    mem_cfg = _project_memory_models(project)
    desc = _resolve_embedder(settings, mem_cfg)
    identity = _resolve_embedder_identity(project, desc)
    return _mem0_options_for(project, settings, mem_cfg, desc, identity)


def _mem0_options_for(project, settings: dict, mem_cfg: dict, desc: dict,
                      identity: dict, *,
                      qdrant_path: str | None = None) -> dict:
    """Assemble mem0 options for an already-resolved embedder + identity.

    Split out for the rebuild path, which must NOT go through
    ``_resolve_embedder_identity`` (its whole job is to refuse a changed
    embedder) and which writes into a temporary store before swapping it in —
    hence ``qdrant_path``.
    """
    from ms_agent.project.paths import memory_dir

    dims = int(identity["dimension"])

    if desc["mode"] == "local":
        # mem0 constructs its own TextEmbedding later, out of our hands — make
        # sure the model is already in the shared cache by then. No-op when
        # warm; covers a legacy local-mode project whose store was configured
        # before this machine ever ran ensure_embedder_usable.
        from app.backends.ms_agent import embed_warmup
        from app.core.settings import settings as app_settings

        embed_warmup.warm_local_memory_models(desc["model"],
                                          app_settings.ms_agent_embed_model_source)
        embedder = {
            "provider": "fastembed",
            "config": {"model": desc["model"], "embedding_dims": dims},
        }
    else:
        config = {
            "api_key": desc["api_key"],
            "openai_base_url": desc["base_url"],
            "model": desc["model"],
        }
        # mem0 forwards `dimensions` to the API whenever embedding_dims is
        # set; only set it where the probe proved the backend accepts it.
        if identity.get("pass_dimensions"):
            config["embedding_dims"] = dims
        embedder = {"provider": "openai", "config": config}

    options: dict = {
        "embedder": embedder,
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "path": qdrant_path or str(memory_dir(project.path) / "qdrant"),
                "on_disk": True,
                "collection_name": "webui_memory",
                "embedding_model_dims": dims,
            },
        },
        # mem0 defaults this to ~/.mem0/history.db — one global SQLite holding
        # every project's RAW conversation messages (it feeds them back as
        # extraction context) plus its memory event log. For a per-project
        # product that is the wrong scope: it outlives the project it came from
        # and sits outside the directory that is supposed to hold its data.
        "history_db_path": str(memory_dir(project.path) / "history.db"),
    }
    llm = _mem0_llm(settings, mem_cfg)
    if llm is not None:
        options["llm"] = llm
    return options


def _apply_webui_memory(config, project):
    """Wire the project's memory toggle to the SDK's unified memory.

    Enabled -> `memory.unified_memory`, namespaced per project and rooted
    under `<project.path>/.ms_agent/memory/` (via output_dir):
    - memory_backend "file"   -> FileBasedBackend (MEMORY.md, default);
      writes happen through the model's `memory` tool.
    - memory_backend "vector" -> Mem0Backend (mem0 + local qdrant); writes
      happen through mem0's per-round fact extraction, so the node also
      activates the agent's `add_after_step` ingestion hook.
    A vector project whose memory cannot be built (no embedder, identity
    mismatch, mem0 missing) runs WITHOUT memory for the session — never as a
    silent file fallback, which would write a MEMORY.md the vector UI never
    shows. The reason reaches the user through GET /memory/status.
    Disabled -> drop any lower-layer memory block so the WebUI toggle is
    authoritative (no memory tools, no injection)."""
    from omegaconf import OmegaConf

    if getattr(project, "memory_enabled", False):
        pid = project.id or "default"
        backend = getattr(project, "memory_backend", None) or "file"
        node: dict = {
            "storage": {"backend": "file"},
            "namespace": {"user_id": pid},
            # Legacy-shaped fields some agent paths read directly:
            # SharedMemoryManager keying + add_memory()'s per-step ingestion
            # (get_memory_meta_safe requires an explicit add_after_step block).
            "user_id": pid,
            "add_after_step": {"user_id": pid},
        }
        if backend == "vector":
            recall = (_project_memory_models(project) or {}).get("recall_top_k")
            if isinstance(recall, int) and recall > 0:
                node["recall_top_k"] = recall
            node_ok = False
            if _vector_memory_available():
                try:
                    options = _mem0_options(project)
                    node["storage"]["backend"] = "mem0"
                    node["mem0"] = options
                    node_ok = True
                except MemoryConfigError as e:
                    logger.warning(
                        "vector memory disabled for project %s this session "
                        "(%s): %s", pid, e.code, e)
                except Exception:
                    logger.warning(
                        "vector memory disabled for project %s this session",
                        pid, exc_info=True)
            else:
                logger.warning(
                    "vector memory disabled for project %s: mem0ai missing", pid)
            if not node_ok:
                if OmegaConf.select(config, "memory", default=None) is not None:
                    del config["memory"]
                return config
        elif backend != "file":
            logger.warning("unknown memory_backend %r; using file", backend)
        OmegaConf.update(config, "memory.unified_memory", node, merge=True)
        # The WebUI drives unified_memory only. Legacy memory types leaking in
        # from project/global config (notably `default_memory`, whose mem0 v1
        # calls break against the mem0 2.x we ship) are dropped, not merged.
        mem_node = OmegaConf.select(config, "memory", default=None)
        for key in [k for k in (mem_node or {}) if k != "unified_memory"]:
            logger.warning("dropping legacy memory type %r (webui uses unified_memory)", key)
            del mem_node[key]
    elif OmegaConf.select(config, "memory", default=None) is not None:
        del config["memory"]
    return config


# Read-only / plan-machinery tools that restricted mode lets through without a
# confirmation card. Writes (write_file/edit_file), shell (code_executor) and
# MCP tools are NOT whitelisted, so each surfaces an authorization card.
_PERMISSION_WHITELIST = [
    "file_system---read_file",
    "file_system---grep",
    "file_system---glob",
    "todo_list---*",
    "unified_memory---*",
    "skills---*",
]


def _apply_webui_permission(config, project_mode: str | None = None):
    """Default this phase to the SDK's restricted (ask) mode.

    Non-whitelisted tools suspend on the session's WebPermissionHandler, which
    surfaces an authorization card over SSE and times out to deny. Explicit
    `permission.*` from settings.json / project config still wins — we only
    fill blanks. ``project_mode`` is the UI's per-project override (the
    composer's restricted/full-access selector, stored in the project sidecar):
    an explicit user choice, so it beats the fill-blanks default."""
    from omegaconf import OmegaConf

    if project_mode in ("restricted", "auto"):
        OmegaConf.update(config, "permission.mode", project_mode, merge=True)
    elif OmegaConf.select(config, "permission.mode", default=None) is None:
        OmegaConf.update(config, "permission.mode", "restricted", merge=True)
    if OmegaConf.select(config, "permission.whitelist", default=None) is None:
        OmegaConf.update(
            config, "permission.whitelist", list(_PERMISSION_WHITELIST), merge=True
        )
    return config


def provider_base_url(provider: str) -> str:
    """The endpoint we will actually call for ``provider`` (user override first,
    then the built-in spec's default). The thinking dialect is decided by the
    host, so this — not the provider id — is what the SDK needs."""
    provider = (provider or "").lower()
    entry = (_read_settings().get("providers") or {}).get(provider) or {}
    return entry.get("base_url") or _openai_compat_base_url(provider) or ""


def thinking_plan(
    protocol: str,
    provider: str,
    effort: Any = "auto",
    existing: dict | None = None,
) -> dict:
    """What the SDK will send for ``effort`` on this provider's endpoint.

    A thin pass-through to ``ms_agent.llm.thinking.plan`` so the settings UI and
    the runtime can never drift: the same function decides both. ``existing`` is
    the rest of the user's generation params, which the plan yields to — without
    it the dialog would advertise a ``reasoning_effort`` that the request path
    then drops (DashScope rejects it alongside a hand-written
    ``thinking_budget``). The WebUI holds NO policy of its own about thinking —
    it used to, as a per-provider boolean, and that boolean is exactly what
    silenced thinking on ModelScope and Zhipu by writing an explicit ``false``
    where it meant "no opinion"."""
    from ms_agent.llm.thinking import plan

    return plan(effort,
                base_url=provider_base_url(provider),
                protocol=(protocol or "").lower(),
                existing=existing)


def _apply_model_compatibility(config):
    """Normalize provider/model quirks that break the WebUI's shared defaults."""
    import json

    from omegaconf import OmegaConf

    service = str(OmegaConf.select(config, "llm.service", default="") or "")
    model_id = str(OmegaConf.select(config, "llm.model", default="") or "")
    # Case-folded copies for the vendor quirk matching further down ONLY. The
    # sidecar lookup below has to use both ids verbatim: its keys are the provider
    # id as created and the model id as the provider spells it, so folding them
    # made `webui_params` come back empty for anything carrying capitals — a very
    # ordinary model id like `Qwen/Qwen3-32B`. That empty dict then reads as "the
    # user configured no temperature / no thinking", and the two blocks below
    # delete the values `_apply_webui_generation_params` had just merged in from
    # exactly those settings.
    provider = service.lower()
    model = model_id.lower()
    temperature_enabled = False
    webui_params = _webui_generation_params(service, model_id)
    temperature_enabled = bool((_read_settings().get("llm") or {}).get("temperature_enabled"))

    # The SDK's base agent.yaml sets temperature=0.3 as a generic default. Many
    # OpenAI-compatible models (including deepseek-v4-pro and kimi-k2.5 here)
    # reject that value. In the WebUI, temperature should only be sent when the
    # user explicitly enables/configures it.
    temperature_explicit = temperature_enabled or "temperature" in webui_params
    if not temperature_explicit:
        generation_config = OmegaConf.select(config, "generation_config", default=None)
        if generation_config is not None and "temperature" in generation_config:
            del generation_config["temperature"]

    # Some current OpenAI-compatible reasoning/code models reject arbitrary
    # temperature values and require temperature=1 when the field is present.
    if temperature_explicit and (
        model.startswith("deepseek-v4")
        or (provider == "deepseek" and "deepseek-v4" in model)
        or model.startswith("kimi-k2")
        or (provider == "kimi" and "kimi-k2" in model)
    ):
        OmegaConf.update(config, "generation_config.temperature", 1.0, merge=True)

    # Thinking: the WebUI decides nothing. The SDK resolves the canonical
    # `reasoning_effort` knob against the endpoint at request time
    # (ms_agent/llm/thinking.py), which is the only place that knows the
    # base_url and therefore the dialect.
    #
    # All we have to do is get out of its way: the SDK's base agent.yaml seeds
    # generation_config.extra_body.enable_thinking = false, and a hand-written
    # wire value deliberately outranks the knob, so leaving that seed in place
    # would pin thinking OFF everywhere. Dropping it is an active step, not an
    # omission. A value the USER configured (provider default_generation_params
    # / model advanced_params, merged in by _apply_webui_generation_params) is
    # left exactly as it is — that is the escape hatch working as intended.
    extra_body = webui_params.get("extra_body")
    thinking_user_set = isinstance(extra_body, dict) and any(
        key in extra_body
        for key in ("enable_thinking", "thinking_budget", "thinking")
    )
    if not thinking_user_set:
        extra = OmegaConf.select(
            config, "generation_config.extra_body", default=None)
        if extra is not None and "enable_thinking" in extra:
            del extra["enable_thinking"]
    return config


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge ``override`` into ``base`` (nested dicts merged, not
    replaced), returning a new dict. Non-dict values (and dict-vs-scalar
    mismatches) are overwritten by ``override``."""
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _webui_generation_params(provider: str, model: str) -> dict:
    """Provider defaults + model overrides stored in WebUI sidecar metadata.

    Merged deeply so a model-level nested dict (e.g. ``extra_body``) refines the
    provider-level one rather than replacing it — otherwise a model that sets a
    single ``extra_body`` key would drop the provider's other ``extra_body``
    entries (e.g. ``enable_thinking``)."""
    if not provider or not model:
        return {}
    from app.backends.ms_agent import sidecar
    from app.backends.ms_agent.mapping import encode_model_id

    provider_params = (
        _read_metadata("providers", provider) or {}
    ).get("default_generation_params") or {}
    model_params = (
        _read_metadata("models", encode_model_id(provider, model)) or {}
    ).get("advanced_params") or {}
    params: dict = {}
    if isinstance(provider_params, dict):
        params = _deep_merge(params, provider_params)
    if isinstance(model_params, dict):
        params = _deep_merge(params, model_params)
    return params


def _webui_supports_vision(provider: str, model: str) -> bool | None:
    """The model's "image understanding" switch, or None when never set.

    Tri-state is load-bearing: None means the SDK decides (provider capability,
    then learning from a refusal), which is why this cannot collapse to a bool.
    """
    if not provider or not model:
        return None
    from app.backends.ms_agent import sidecar
    from app.backends.ms_agent.mapping import encode_model_id

    meta = _read_metadata("models", encode_model_id(provider, model)) or {}
    value = meta.get("supports_vision")
    return None if value is None else bool(value)


def _apply_webui_generation_params(config):
    """Apply generation params configured from the WebUI model settings page."""
    from omegaconf import OmegaConf

    provider = str(OmegaConf.select(config, "llm.service", default="") or "")
    model = str(OmegaConf.select(config, "llm.model", default="") or "")
    for key, value in _webui_generation_params(provider, model).items():
        OmegaConf.update(config, f"generation_config.{key}", value, merge=True)
    # Not a generation param — it decides whether image attachments are put on
    # the wire at all, so it lands on `llm` where the SDK's resolver reads it.
    # Only written when the user has actually set it, so "unset" stays unset.
    supports_vision = _webui_supports_vision(provider, model)
    if supports_vision is not None:
        OmegaConf.update(
            config, "llm.supports_vision", supports_vision, merge=True)
    return config


def session_dir(project, session) -> str:
    from ms_agent.project.paths import global_projects_root

    return str(global_projects_root() / project.id / "sessions" / session.id)


def session_has_history(project, session) -> bool:
    from ms_agent.project import SessionManager

    try:
        log = SessionManager(project).get_session_log(session)
        return bool(log.get_all_messages())
    except Exception:
        return False


# UI/meta fields on a managed MCP entry that must not reach the runtime server
# config (mirrors ms_agent.tui.managed_config._MCP_META).
_MCP_META = frozenset({
    "source", "meta", "_scope", "mcp", "implementation", "trust_remote_code", "_removed",
})


def _mcp_reachable(server: dict, timeout: float = 2.0) -> bool:
    """Cheap pre-flight so an unreachable MCP can't break the chat turn.

    Remote servers: TCP-connect to host:port. stdio servers: the command must
    resolve on PATH (or be an existing file). Reachable-but-broken servers still
    pass (rare); the common 'wrong/dead URL or missing command' case is dropped.
    """
    import shutil
    import socket
    from urllib.parse import urlparse

    url = server.get("url")
    if url:
        try:
            u = urlparse(url)
            if not u.hostname:
                return False
            port = u.port or (443 if u.scheme in ("https", "wss") else 80)
            with socket.create_connection((u.hostname, port), timeout=timeout):
                return True
        except Exception:
            return False
    command = server.get("command")
    if command:
        return bool(shutil.which(command)) or os.path.isfile(command)
    return True  # unknown shape — don't drop


def _healthy_mcp_config(mcp_config: dict | None) -> dict:
    servers = (mcp_config or {}).get("mcpServers") or {}
    healthy = {name: s for name, s in servers.items() if _mcp_reachable(s)}
    dropped = set(servers) - set(healthy)
    if dropped:
        logger.warning("skipping unreachable MCP server(s): %s", ", ".join(sorted(dropped)))
    return {"mcpServers": healthy} if healthy else {}


def build_agent(project, session, *, event_sink, input_source, mcp_config=None,
                permission_handler=None, model_snapshot=None):
    token = _model_snapshot.set(model_snapshot)
    try:
        return _build_agent(project, session, event_sink=event_sink, input_source=input_source,
                            mcp_config=mcp_config, permission_handler=permission_handler)
    finally:
        _model_snapshot.reset(token)


def _build_agent(project, session, *, event_sink, input_source, mcp_config=None,
                 permission_handler=None):
    from ms_agent.agent.llm_agent import LLMAgent
    from ms_agent.config import ConfigResolver
    from ms_agent.permission.handler import AutoPermissionHandler
    from ms_agent.tui.managed_config import (
        merge_skills_into_config,
        resolve_mcp_config,
    )
    from omegaconf import OmegaConf

    from app.backends.ms_agent.tool_settings import ensure_tool_settings

    h = home()
    ensure_tool_settings(h)
    resolver = ConfigResolver(
        global_dir=h, project_root=project.path, defaults={"tools": DEFAULT_TOOLS})
    sdir = session_dir(project, session)
    session_overrides = {
        # ① align the runtime SessionLog with the SessionManager session dir
        "session_log": {
            "dir": sdir,
            "session_key": session.session_key,
        },
        # ② project-level personalization instruction
        "personalization": {"project_instruction": project.instruction or ""},
        # ③ per-session todo plan: the todo_list tool joins these onto
        # output_dir, and an absolute path wins the join — so each session's
        # plan lives beside its session log instead of a project-shared
        # <workspace>/plan.json (which made concurrent sessions clobber each
        # other's plans). read_plan() resolves the same path.
        "tools": {
            "todo_list": {
                # This is the built-in session plan, even when an existing
                # settings block omits its MCP discriminator.
                "mcp": False,
                "plan_filename": os.path.join(sdir, "plan.json"),
                "plan_md_filename": os.path.join(sdir, "plan.md"),
            },
        },
    }
    cfg = resolver.resolve(
        agent_config=None,
        project_path=project.path,
        session_overrides=session_overrides,
        global_settings=_read_settings(),
    )
    snapshot = _model_snapshot.get()
    if snapshot is not None:
        llm = snapshot.settings["llm"]
        provider = llm["provider"]
        selected = {"service": provider, "model": llm["model"]}
        for key in ("api_key", "base_url"):
            if key in llm:
                selected[f"{provider}_{key}"] = llm[key]
        if llm.get("protocol"):
            selected["protocol"] = llm["protocol"]
        OmegaConf.update(cfg, "llm", selected, merge=False)
    cfg = _apply_webui_defaults(cfg)
    cfg = _apply_webui_memory(cfg, project)
    # Restricted-by-default permission; the project sidecar's explicit
    # restricted/full-access choice (composer selector) overrides.
    from app.backends.ms_agent import sidecar

    meta = _read_metadata("projects", project.id, {}) or {}
    cfg = _apply_webui_permission(cfg, meta.get("permission_mode"))

    # Route-A shaping (see tui/app.py::_prepare_config).
    shaping = {
        "interactive": True,  # non-TTY backend: enable interactive lifecycle
        # Route chat through the data-driven provider layer (ms_agent/llm/
        # router.py) rather than the legacy hard-coded LLM classes. The new
        # layer supports mid-stream interrupt() — abandoning a turn closes the
        # upstream streaming response so the server stops generating instead of
        # running to completion into a dropped connection. The legacy path is
        # being deprecated.
        "llm.use_provider_router": True,
        "generation_config.stream": True,
        "generation_config.stream_output": True,
        "generation_config.show_reasoning": True,
        # No enable_thinking here on purpose: _apply_model_compatibility below
        # is the single place that decides it (on / off / say nothing), and a
        # hardcoded True here would be an unconditional default it then has to
        # undo.
        "session_log.enabled": True,
        "output_dir": project.path,
        "max_chat_round": 1000,
    }
    for key, value in shaping.items():
        OmegaConf.update(cfg, key, value, merge=True)
    # Propagate the active provider's wire protocol (openai | anthropic) so the
    # provider layer picks the matching transport. A provider may point at
    # another vendor's compatible endpoint (e.g. DeepSeek's /anthropic gateway),
    # where the endpoint's protocol differs from the service's default transport.
    _service = str(OmegaConf.select(cfg, "llm.service", default="") or "")
    _protocol = (
        (_read_settings().get("providers") or {}).get(_service) or {}
    ).get("protocol")
    if _protocol:
        OmegaConf.update(cfg, "llm.protocol", _protocol)
    cfg = _apply_webui_generation_params(cfg)
    cfg = _apply_model_compatibility(cfg)
    # Drop any listed InputCallback so restarts never double-register it.
    cbs = [c for c in list(getattr(cfg, "callbacks", []) or []) if c != "input_callback"]
    OmegaConf.update(cfg, "callbacks", cbs, merge=False)

    # Bridge managed skill sources into the runtime (reused SDK/TUI helper).
    cfg = merge_skills_into_config(cfg, h, project.path)
    skill_sync_token = None
    try:
        from app.backends.ms_agent.skill_index import skill_index

        skill_sync_token = skill_index.runtime_snapshot(
            project.id,
            project.path,
            getattr(cfg, "skills", None),
        ).token
    except Exception:
        logger.debug("skill change tracker baseline failed", exc_info=True)

    # MCP: use the SDK's standard mcp_config path (enabled servers only) — far
    # more robust to invalid servers than injecting an MCPRuntime (whose remote
    # client teardown throws cross-task anyio errors). The registry pre-probes
    # servers (connect+initialize) and passes only healthy ones as `mcp_config`;
    # fall back to a cheap TCP check for direct callers (tests). Live
    # enable/disable is sacrificed — a toggle applies on the next session build.
    if mcp_config is None:
        mcp_config = _healthy_mcp_config(resolve_mcp_config(h, project.path, None))

    resume = session_has_history(project, session)
    agent = LLMAgent(
        cfg,
        event_sink=event_sink,
        input_source=input_source,
        mcp_config=mcp_config or {},
        load_cache=resume,
    )
    if skill_sync_token is not None:
        # The watcher baseline predates the SDK's full catalog load.  Any
        # subsequent resource event changes the token before the first turn.
        agent._webui_skill_sync_token = skill_sync_token
    # The runtime passes a WebPermissionHandler (ask -> SSE authorization card
    # -> POST /api/chat/permission resolve, deny on timeout). Direct callers
    # (tests/scripts) get auto-allow so restricted mode can't hang them on a
    # CLI prompt.
    agent.set_permission_handler(permission_handler or AutoPermissionHandler())
    return agent
