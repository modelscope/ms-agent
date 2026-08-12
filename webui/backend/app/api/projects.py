from fastapi import APIRouter, HTTPException

from app.core.envelope import EnvelopeRoute
from app.schemas.project import Project, ProjectCreate, ProjectUpdate

router = APIRouter(prefix="/api/projects", tags=["projects"],
                   route_class=EnvelopeRoute)


@router.get("")
def list_projects() -> list[Project]:
    from app.backends.ms_agent import projects

    return projects.list_projects()


@router.post("", status_code=201)
def create_project(body: ProjectCreate) -> Project:
    from app.backends.ms_agent import projects

    return projects.create_project(body)


@router.get("/{project_id}")
def get_project(project_id: str) -> Project:
    from app.backends.ms_agent import projects

    return projects.get_project(project_id)


@router.patch("/{project_id}")
def update_project(project_id: str, body: ProjectUpdate) -> Project:
    from app.backends.ms_agent import projects

    return projects.update_project(project_id, body)


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: str) -> None:
    from app.backends.ms_agent import projects

    return projects.delete_project(project_id)
