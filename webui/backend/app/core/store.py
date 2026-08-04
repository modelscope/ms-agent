"""In-memory mock store for the prototype.

Entities live in module-level dicts keyed by id. A `seed()` call at app boot
populates demo data so the UI has something to render before any user action.
There is no persistence — restart the process and the store resets.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

DEFAULT_PROJECT_ID = "default"


def now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid4().hex[:12]}"


# Per-entity stores --------------------------------------------------------

projects: dict[str, dict] = {}
sessions: dict[str, dict] = {}
artifacts: dict[str, list[dict]] = {}  # session_id -> artifacts
mcps: dict[str, dict] = {}
skills: dict[str, dict] = {}
# project_id -> list of MemoryFile dicts. Global memory is NOT supported —
# the spec gates memory at project level.
memory_files: dict[str, list[dict]] = {}
# scope ('global' | 'project:<id>') -> single Instruction blob.
instructions: dict[str, dict] = {}
providers: dict[str, dict] = {}
models: dict[str, dict] = {}
agent_settings: dict = {}  # singleton
profile: dict = {}  # singleton (user profile / user.md)
# project_id -> list of WorkspaceFile dicts.
workspace_files: dict[str, list[dict]] = {}


# Scope helpers -----------------------------------------------------------


def scope_key(scope: str) -> str:
    """Normalize scope. Accepts 'global' or 'project:<id>'."""
    if scope == "global":
        return "global"
    if scope.startswith("project:"):
        pid = scope.split(":", 1)[1]
        if pid not in projects:
            raise ValueError(f"unknown project: {pid}")
        return f"project:{pid}"
    raise ValueError(f"invalid scope: {scope!r}")


# Seed --------------------------------------------------------------------


def seed() -> None:
    if projects:
        return
    t = now()

    agent_settings.update({
        "default_provider_id": "modelscope",
        "default_model_id": "qwen3-max",
        "default_memory_enabled": True,
        "default_memory_backend": "file",
        "global_mcp_auto_attach": True,
        "global_skill_auto_attach": True,
    })

    profile.update({
        "agent_calls_user": "User",
        "description": "",
        "updated_at": t,
    })

    # Projects — default project has memory forced off per spec.
    projects[DEFAULT_PROJECT_ID] = {
        "id": DEFAULT_PROJECT_ID,
        "name": "默认项目",
        "description":
        "Default workspace — its settings are the global settings.",
        "local_path": "",
        "is_default": True,
        "memory_enabled": False,
        "memory_backend": "file",
        "mcp_auto_attach": True,
        "skill_auto_attach": True,
        "created_at": t - timedelta(days=30),
    }
    for pid, name, desc, path in [
        ("webui", "ms-agent-webui", "This repo",
         "/Users/demo/Projects/ms-agent-webui"),
        ("agent-idp", "AgentIDP", "Agent IDP project",
         "/Users/demo/Projects/agent-idp"),
        ("studio-preinstall", "StudioPreInstall", "Studio preinstall stack",
         ""),
            # Chinese-named project — id stays an opaque slug, name carries Chinese.
        ("p-zh01", "智能客服助手", "中文命名示例项目", "/Users/demo/Projects/zh-support-bot"
         ),
    ]:
        projects[pid] = {
            "id": pid,
            "name": name,
            "description": desc,
            "local_path": path,
            "is_default": False,
            "memory_enabled": True,
            "memory_backend": "file",
            "mcp_auto_attach": True,
            "skill_auto_attach": True,
            "created_at": t - timedelta(days=7),
        }

    # Sessions — a few in default + each named project
    for sid, title, project_id, mins_ago, preview in [
        ("s-001", "Bootstrap webui prototype", "webui", 5,
         "Use the README and wire up the entry page"),
        ("s-002", "Sort out plan-component interactions", "webui", 120,
         "ask/confirm → tool-side rendering"),
        ("s-003", "Implement sidebar navigation", "webui", 60 * 4,
         "Collapsible sidebar with project list"),
        ("s-004", "Design token integration", "webui", 60 * 6,
         "Map Figma tokens to Tailwind CSS variables"),
        ("s-005", "Empty state component", "webui", 60 * 8,
         "Unified EmptyState with illustration and action"),
        ("s-006", "Composer SSR hydration fix", "webui", 60 * 12,
         "Fix textarea flash on initial load"),
        ("s-007", "MCP panel card layout", "webui", 60 * 18,
         "Grid cards with enable toggle and status"),
        ("s-008", "Memory module refactor", "webui", 60 * 24,
         "Inline editing with content-only model"),
        ("s-009", "Dark mode theme switching", "webui", 60 * 36,
         "Class-based dark mode with useTheme hook"),
        ("s-010", "File upload interaction", "webui", 60 * 48,
         "Drag-drop and click-to-upload with preview"),
        ("s-011", "SVG icon componentization", "webui", 60 * 72,
         "vite-plugin-svgr + currentColor migration"),
        ("s-100", "Quick brainstorm", DEFAULT_PROJECT_ID, 20,
         "Out-of-project chat — name ideas"),
        ("s-101", "Session log research", DEFAULT_PROJECT_ID, 60 * 24,
         "activity monitor + intermediate trace"),
        ("s-102", "Read the antd-x docs", DEFAULT_PROJECT_ID, 60 * 6,
         "Skim useXChat / x-chat-provider"),
        ("s-200", "IDP feature gaps", "agent-idp", 60 * 3,
         "Compare with internal IDP stack"),
        ("s-300", "客服话术优化", "p-zh01", 45, "整理高频问题与标准回复"),
        ("s-301", "意图识别调研", "p-zh01", 60 * 8, "对比规则匹配与小模型分类"),
    ]:
        sessions[sid] = {
            "id": sid,
            "title": title,
            "project_id": project_id,
            "updated_at": t - timedelta(minutes=mins_ago),
            "preview": preview,
        }

    artifacts["s-001"] = [
        {
            "id":
            "a-001",
            "session_id":
            "s-001",
            "path":
            "workspace/notes.md",
            "kind":
            "markdown",
            "size":
            512,
            "updated_at":
            t - timedelta(minutes=4),
            "preview":
            "# Entry page TODO\n- Left sidebar\n- Centre chat\n- Right artifact panel",
        },
        {
            "id": "a-002",
            "session_id": "s-001",
            "path": "workspace/plan.json",
            "kind": "json",
            "size": 128,
            "updated_at": t - timedelta(minutes=3),
            "preview": '{"steps": ["scaffold", "ui", "wire"]}',
        },
    ]

    # MCPs — a couple global + project-scoped
    for name, transport, endpoint, scope, desc in [
        ("@amap/amap-maps", "stdio", "npx -y @amap/amap-maps-mcp-server",
         "global",
         "Use this skill whenever the user wants to do anything with map / location queries."
         ),
        ("@modelcontextprotocol/fetch", "stdio",
         "npx -y @modelcontextprotocol/server-fetch", "global",
         "Use this skill any time a URL is involved in any way — fetch / scrape / parse pages."
         ),
        ("@anthropic/claude-code", "stdio",
         "npx -y @anthropic/claude-code-mcp", "global",
         "Interact with Claude for code generation and review."),
        ("@vercel/mcp-server", "streamable_http", "https://mcp.vercel.com",
         "global", "Deploy and manage Vercel projects."),
        ("@github/mcp-server", "stdio", "npx -y @github/mcp-server", "global",
         "GitHub repository operations — issues, PRs, code search."),
        ("@supabase/mcp-server", "stdio", "npx -y @supabase/mcp-server",
         "global", "Supabase database and auth management."),
        ("@stripe/agent-toolkit", "stdio", "npx -y @stripe/agent-toolkit-mcp",
         "global", "Payment processing and subscription management."),
        ("@notion/mcp-server", "stdio", "npx -y @notion/mcp-server", "global",
         "Read and write Notion pages and databases."),
        ("@linear/mcp-server", "stdio", "npx -y @linear/mcp-server", "global",
         "Linear issue tracking and project management."),
        ("@slack/mcp-server", "stdio", "npx -y @slack/mcp-server", "global",
         "Send messages and manage Slack channels."),
        ("@figma/mcp-server", "stdio", "npx -y @figma/mcp-server", "global",
         "Access Figma designs, components, and design tokens."),
        ("@sentry/mcp-server-global", "stdio", "npx -y @sentry/mcp-server",
         "global", "Error monitoring and performance tracing for production."),
        ("@datadog/mcp-server", "stdio", "npx -y @datadog/mcp-server",
         "global", "Application monitoring, tracing, and log analytics."),
        ("@twilio/mcp-server", "stdio", "npx -y @twilio/mcp-server", "global",
         "SMS, voice, and messaging communication APIs."),
        ("@cloudflare/mcp-server", "stdio", "npx -y @cloudflare/mcp-server",
         "global", "Edge computing, DNS, and CDN management."),
        ("@jira/mcp-server", "stdio", "npx -y @jira/mcp-server", "global",
         "Jira issue tracking and agile project boards."),
        ("@confluence/mcp-server", "stdio", "npx -y @confluence/mcp-server",
         "global", "Confluence wiki page creation and search."),
        ("@tavily-ai/tavily-mcp", "stdio", "npx -y @tavily-ai/tavily-mcp",
         f"project:{DEFAULT_PROJECT_ID}",
         "Web search and real-time information retrieval."),
        ("antvis/mcp-server-chart", "stdio", "uvx mcp-server-chart",
         f"project:{DEFAULT_PROJECT_ID}",
         "Use this skill any time a spreadsheet file is the primary input or output."
         ),
        ("@prisma/mcp-server", "stdio", "npx -y @prisma/mcp-server",
         f"project:{DEFAULT_PROJECT_ID}",
         "Prisma ORM schema and migration management."),
        ("@docker/mcp-server", "stdio", "npx -y @docker/mcp-server",
         f"project:{DEFAULT_PROJECT_ID}",
         "Docker container lifecycle management."),
        ("@aws/mcp-server", "stdio", "npx -y @aws/mcp-server",
         f"project:{DEFAULT_PROJECT_ID}",
         "AWS cloud resource provisioning and monitoring."),
        ("@firebase/mcp-server", "stdio", "npx -y @firebase/mcp-server",
         f"project:{DEFAULT_PROJECT_ID}",
         "Firebase auth, Firestore, and hosting operations."),
        ("@openai/mcp-server", "stdio", "npx -y @openai/mcp-server",
         f"project:{DEFAULT_PROJECT_ID}",
         "OpenAI API access for embeddings and completions."),
        ("@redis/mcp-server", "stdio", "npx -y @redis/mcp-server",
         f"project:{DEFAULT_PROJECT_ID}",
         "Redis cache and pub/sub operations."),
        ("@elasticsearch/mcp-server", "stdio",
         "npx -y @elasticsearch/mcp-server", f"project:{DEFAULT_PROJECT_ID}",
         "Elasticsearch full-text search and analytics."),
        ("@sentry/mcp-server", "stdio", "npx -y @sentry/mcp-server",
         f"project:{DEFAULT_PROJECT_ID}",
         "Sentry error tracking and performance monitoring."),
        ("@mongodb/mcp-server", "stdio", "npx -y @mongodb/mcp-server",
         f"project:{DEFAULT_PROJECT_ID}",
         "MongoDB document CRUD and aggregation pipelines."),
        ("@grafana/mcp-server", "stdio", "npx -y @grafana/mcp-server",
         f"project:{DEFAULT_PROJECT_ID}",
         "Grafana dashboard queries and alert management."),
    ]:
        mid = new_id("m-")
        mcps[mid] = {
            "id": mid,
            "name": name,
            "description": desc,
            "transport": transport,
            "endpoint": endpoint,
            "enabled": True,
            "scope": scope,
            "created_at": t,
        }

    # Skills — global + project-scoped
    for name, kind, scope in [
        ("docx", "file-type", "global"),
        ("pdf", "file-type", "global"),
        ("xlsx", "file-type", "global"),
        ("skill-creator", "meta", "global"),
        ("code-review", "meta", "global"),
        ("unit-test-gen", "meta", "global"),
        ("api-doc-gen", "meta", "global"),
        ("commit-message", "meta", "global"),
        ("refactor-assist", "domain", "global"),
        ("i18n-extract", "domain", "global"),
        ("sql-optimizer", "domain", "global"),
        ("regex-builder", "domain", "global"),
        ("env-checker", "domain", "global"),
        ("changelog-writer", "meta", "global"),
        ("type-gen", "meta", "global"),
        ("mock-data-gen", "meta", "global"),
        ("git-flow-helper", "domain", "global"),
        ("orbra-writing-plans", "domain", f"project:{DEFAULT_PROJECT_ID}"),
        ("anthropics-front-design", "domain", f"project:{DEFAULT_PROJECT_ID}"),
        ("component-scaffold", "meta", f"project:{DEFAULT_PROJECT_ID}"),
        ("storybook-gen", "meta", f"project:{DEFAULT_PROJECT_ID}"),
        ("e2e-test-writer", "meta", f"project:{DEFAULT_PROJECT_ID}"),
        ("changelog-gen", "meta", f"project:{DEFAULT_PROJECT_ID}"),
        ("migration-assist", "domain", f"project:{DEFAULT_PROJECT_ID}"),
        ("perf-profiler", "domain", f"project:{DEFAULT_PROJECT_ID}"),
        ("accessibility-audit", "domain", f"project:{DEFAULT_PROJECT_ID}"),
        ("dep-updater", "domain", f"project:{DEFAULT_PROJECT_ID}"),
        ("lint-fixer", "domain", f"project:{DEFAULT_PROJECT_ID}"),
        ("docker-compose-gen", "domain", f"project:{DEFAULT_PROJECT_ID}"),
    ]:
        sk_id = new_id("sk-")
        skills[sk_id] = {
            "id": sk_id,
            "name": name,
            "kind": kind,
            "content": f"# {name}\n\nPlaceholder skill description.",
            "enabled": True,
            "scope": scope,
            "created_at": t,
        }

    # Memory items — project-scoped only (Default project gets none).
    memory_files["webui"] = [
        {
            "id": "mem_001",
            "project_id": "webui",
            "content":
            "User prefers concise replies. Default model: Qwen3-Max.",
            "updated_at": t,
        },
        {
            "id": "mem_002",
            "project_id": "webui",
            "content":
            "Use Tailwind utility classes. Avoid inline styles. Prefer design tokens over raw color values.",
            "updated_at": t - timedelta(hours=1),
        },
        {
            "id": "mem_003",
            "project_id": "webui",
            "content":
            "All buttons must use MsaButton component. IconButton for icon-only actions. No raw <button> elements.",
            "updated_at": t - timedelta(hours=2),
        },
        {
            "id": "mem_004",
            "project_id": "webui",
            "content":
            "Project-scoped routes: /projects/:id/sessions/:sid. New chat: /projects/:id/new.",
            "updated_at": t - timedelta(hours=3),
        },
        {
            "id": "mem_005",
            "project_id": "webui",
            "content":
            "All user-facing text must go through useT() hook. Keys are nested by feature module.",
            "updated_at": t - timedelta(hours=5),
        },
        {
            "id": "mem_006",
            "project_id": "webui",
            "content":
            "Sidebar width: 260px expanded, 72px collapsed. Transition 200ms ease. Detail page uses flex-5 / flex-3 split.",
            "updated_at": t - timedelta(hours=8),
        },
        {
            "id": "mem_007",
            "project_id": "webui",
            "content":
            "Class-based dark mode via useTheme(). All colors reference CSS variables with --msa- prefix.",
            "updated_at": t - timedelta(hours=12),
        },
        {
            "id": "mem_008",
            "project_id": "webui",
            "content":
            "Unit tests for utils only. Component testing deferred. Use vitest for runner.",
            "updated_at": t - timedelta(days=1),
        },
        {
            "id": "mem_009",
            "project_id": "webui",
            "content":
            "All API calls go through ~/lib/api.ts. Return typed responses. Handle errors with message.error().",
            "updated_at": t - timedelta(days=2),
        },
        {
            "id": "mem_010",
            "project_id": "webui",
            "content":
            "Use vite-plugin-svgr with ?react suffix. All icons must use currentColor for fill/stroke.",
            "updated_at": t - timedelta(days=3),
        },
    ]

    instructions["global"] = {
        "scope": "global",
        "content": "Be precise. Reference workspace files when relevant.",
        "updated_at": t,
    }

    # Workspace files — mock data for workspace panel.
    webui_workspace = [
        ("speech_paraformer-large-vad-zh", "folder", 8_800_000_000),
        ("speech_paraformer-large-vad-zh/configuration.json", "file", 2_300),
        ("speech_paraformer-large-vad-zh/model.bin", "file", 8_200_000_000),
        ("speech_paraformer-large-vad-zh/vocab.txt", "file", 120_000),
        ("speech_paraformer-large-vad-model.bin", "file", 8_200_000_000),
        ("speech_paraformer-large-vad-config.yaml", "file", 8_200_000_000),
        ("speech_paraformer-large-vad-tokenizer.json", "file", 8_200_000_000),
        ("result_output.json", "file", 1_200_000),
        ("evaluation_report.md", "file", 45_000),
        ("logs", "folder", 5_600_000),
        ("logs/train.log", "file", 3_200_000),
        ("logs/eval.log", "file", 1_800_000),
        ("logs/debug", "folder", 600_000),
        ("logs/debug/step_100.log", "file", 300_000),
        ("logs/debug/step_200.log", "file", 300_000),
    ]
    workspace_files["webui"] = [{
        "project_id": "webui",
        "path": path,
        "kind": kind,
        "size": size,
        "updated_at": t - timedelta(days=240),
        "preview": None,
    } for path, kind, size in webui_workspace]

    # Providers + models
    providers["modelscope"] = {
        "id": "modelscope",
        "kind": "builtin",
        "name": "ModelScope API-Inference",
        "base_url": "https://api-inference.modelscope.cn/v1",
        "api_key_masked": "ms-****abcd",
        "api_key": "",
        "protocol": "openai",
        "enabled": True,
        "default_generation_params": {
            "extra_body": {
                "enable_thinking": False
            },
            "max_tokens": 2048,
        },
        "created_at": t,
    }
    providers["dashscope"] = {
        "id": "dashscope",
        "kind": "custom",
        "name": "DashScope",
        "base_url": "https://dashscope.aliyuncs.com/api/v1",
        "api_key_masked": "",
        "api_key": "",
        "protocol": "openai",
        "enabled": False,
        "created_at": t,
    }
    providers["zhipuai"] = {
        "id": "zhipuai",
        "kind": "custom",
        "name": "ZhipuAI",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "api_key_masked": "",
        "api_key": "",
        "protocol": "openai",
        "enabled": False,
        "created_at": t,
    }
    providers["openai-compat"] = {
        "id": "openai-compat",
        "kind": "custom",
        "name": "OpenAI-compatible",
        "base_url": "",
        "api_key_masked": "",
        "api_key": "",
        "protocol": "openai",
        "enabled": False,
        "created_at": t,
    }
    providers["anthropic-compat"] = {
        "id": "anthropic-compat",
        "kind": "custom",
        "name": "Anthropic-compatible",
        "base_url": "https://api.anthropic.com",
        "api_key_masked": "",
        "api_key": "",
        "protocol": "anthropic",
        "enabled": False,
        "created_at": t,
    }

    for mid, provider_id, name, display in [
        ("qwen3-max", "modelscope", "Qwen/Qwen3-Max", "Qwen3 Max"),
        ("qwen3-235b", "modelscope", "Qwen/Qwen3-235B-A22B-Thinking",
         "Qwen3 235B A22B Thinking"),
        ("deepseek-v3.2", "modelscope", "deepseek-ai/DeepSeek-V3.2",
         "DeepSeek-V3.2"),
    ]:
        models[mid] = {
            "id": mid,
            "provider_id": provider_id,
            "name": name,
            "display_name": display,
            "is_builtin": False,
            "advanced_params": {},
            "created_at": t,
        }
