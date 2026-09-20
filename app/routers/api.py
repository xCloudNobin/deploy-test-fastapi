"""JSON API for projects and tasks (also used by the verify script).

Conventions:

- body validation  -> 422 (FastAPI/Pydantic structured errors)
- semantic errors  -> 400 with ``{"errors": {...}}`` (unknown project, bad filter)
- malformed JSON   -> 422
- missing/wrong CSRF token -> 403
- unknown resource -> 404
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..deps import get_db, require_csrf
from ..models import STATUSES, Project, Task
from ..schemas import (
    ProjectCreate,
    ProjectOut,
    TaskCreate,
    TaskOut,
    TaskUpdate,
)

router = APIRouter(prefix="/api", tags=["api"])


def _status_filter(status: str | None) -> str:
    if status is None or status == "":
        return ""
    if status not in STATUSES:
        raise HTTPException(
            status_code=400,
            detail={
                "errors": {
                    "status": f"Invalid status filter. Allowed: {', '.join(STATUSES)}."
                }
            },
        )
    return status


def _search_pattern(q: str | None) -> tuple[str, str]:
    q = (q or "").strip()[:100]
    return q, f"%{q.lower()}%"


def _task_out(task: Task) -> TaskOut:
    return TaskOut(
        id=task.id,
        project_id=task.project_id,
        project_name=task.project.name if task.project else None,
        title=task.title,
        description=task.description,
        status=task.status,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def _project_out(project: Project, task_count: int) -> ProjectOut:
    return ProjectOut(
        id=project.id,
        name=project.name,
        description=project.description,
        created_at=project.created_at,
        task_count=task_count,
    )


def _check_project_exists(db: Session, project_id: int | None) -> None:
    if project_id is None:
        return
    exists = db.execute(
        select(Project.id).where(Project.id == project_id)
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(
            status_code=400,
            detail={"errors": {"project_id": "Selected project does not exist."}},
        )


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(
    db: Session = Depends(get_db),
    q: str | None = None,
    status: str | None = None,
):
    filter_status = _status_filter(status)
    search, pattern = _search_pattern(q)
    stmt = select(Task).order_by(Task.created_at.desc(), Task.id.desc())
    if filter_status:
        stmt = stmt.where(Task.status == filter_status)
    if search:
        stmt = stmt.where(
            or_(
                Task.title.ilike(pattern),
                Task.description.ilike(pattern),
            )
        )
    tasks = db.execute(stmt).scalars().all()
    return [_task_out(t) for t in tasks]


@router.post("/tasks", response_model=TaskOut, status_code=201)
async def create_task(
    payload: TaskCreate,
    db: Session = Depends(get_db),
    _: None = Depends(require_csrf),
):
    _check_project_exists(db, payload.project_id)
    task = Task(
        project_id=payload.project_id,
        title=payload.title,
        description=payload.description,
        status=payload.status,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return _task_out(task)


@router.get("/tasks/{task_id}", response_model=TaskOut)
def get_task(task_id: int, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return _task_out(task)


@router.patch("/tasks/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: int,
    payload: TaskUpdate,
    db: Session = Depends(get_db),
    _: None = Depends(require_csrf),
):
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")

    provided = payload.model_fields_set
    if "project_id" in provided:
        new_project_id = payload.project_id
        _check_project_exists(db, new_project_id)
        task.project_id = new_project_id
    if "title" in provided:
        task.title = payload.title
    if "description" in provided:
        task.description = payload.description
    if "status" in provided:
        task.status = payload.status

    db.commit()
    db.refresh(task)
    return _task_out(task)


@router.delete("/tasks/{task_id}", status_code=204)
async def delete_task(
    task_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_csrf),
):
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    db.delete(task)
    db.commit()
    return None


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)):
    projects = db.execute(select(Project).order_by(Project.name)).scalars().all()
    counts = dict(
        db.execute(
            select(Task.project_id, func.count(Task.id)).group_by(Task.project_id)
        ).all()
    )
    return [_project_out(p, counts.get(p.id, 0)) for p in projects]


@router.post("/projects", response_model=ProjectOut, status_code=201)
async def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    _: None = Depends(require_csrf),
):
    project = Project(name=payload.name, description=payload.description)
    db.add(project)
    db.commit()
    db.refresh(project)
    return _project_out(project, 0)
