from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    agent_settings,
    chat,
    instructions,
    mcps,
    memory,
    models,
    presence,
    profile,
    projects,
    providers,
    sessions,
    skills,
    workspace,
)
from app.core.envelope import register_exception_handlers
from app.core.settings import settings


def create_app() -> FastAPI:
    app = FastAPI(title="ms-agent-webui backend", version="0.2.0")

    # Uniform envelope-shaped errors for every route (HTTP / validation / crash).
    register_exception_handlers(app)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Ensure ~/.ms_agent + default project + settings.json llm are ready.
    from app.backends.ms_agent.bootstrap import bootstrap

    bootstrap()

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        from app.backends.ms_agent.runtime import registry

        await registry.close_all()

    app.include_router(chat.router)
    app.include_router(presence.router)
    app.include_router(projects.router)
    app.include_router(sessions.router)
    app.include_router(mcps.router)
    app.include_router(skills.router)
    app.include_router(memory.router)
    app.include_router(instructions.router)
    app.include_router(providers.router)
    app.include_router(models.router)
    app.include_router(agent_settings.router)
    app.include_router(profile.router)
    app.include_router(workspace.router)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()


def _run(reload: bool) -> None:
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=reload,
        reload_dirs=["app"] if reload else None,
        reload_includes=["*.py", "*.env"] if reload else None,
    )


def dev() -> None:
    """Run with hot reload."""
    _run(reload=True)


def serve() -> None:
    """Run without reload (production)."""
    _run(reload=False)


if __name__ == "__main__":
    dev()
