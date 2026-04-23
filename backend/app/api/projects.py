"""Project management endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.db.models import Project
from app.db.session import registry_session
from app.schemas.all import ProjectCreateIn, ProjectOut
from app.services.event_logger import log_event
from app.db.session import project_session
from app.utils.time import utcnow

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("/create", response_model=ProjectOut)
def create_project(body: ProjectCreateIn) -> ProjectOut:
    with registry_session() as s:
        existing = s.query(Project).filter(Project.id == body.id).first()
        if existing is not None:
            raise HTTPException(409, f"project '{body.id}' already exists")
        row = Project(
            id=body.id,
            name=body.name,
            description=body.description,
            created_at=utcnow(),
            config_json={},
        )
        s.add(row)

    # Initialize the per-project DB by opening a session once (creates tables
    # and the data/{id}/ directory structure).
    with project_session(body.id) as ps:
        log_event(ps, body.id, "PROJECT_CREATED", {"name": body.name})

    return ProjectOut(
        id=body.id,
        name=body.name,
        description=body.description,
        created_at=row.created_at,
    )


@router.get("/list", response_model=list[ProjectOut])
def list_projects() -> list[ProjectOut]:
    with registry_session() as s:
        rows = s.query(Project).order_by(Project.created_at.desc()).all()
        return [
            ProjectOut(
                id=r.id, name=r.name, description=r.description, created_at=r.created_at
            )
            for r in rows
        ]


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: str) -> ProjectOut:
    with registry_session() as s:
        r = s.query(Project).filter(Project.id == project_id).first()
        if r is None:
            raise HTTPException(404, "project not found")
        return ProjectOut(
            id=r.id, name=r.name, description=r.description, created_at=r.created_at
        )
