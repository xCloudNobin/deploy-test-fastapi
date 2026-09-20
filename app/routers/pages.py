"""HTML server-rendered task-board routes.

Templates are rendered with Jinja2 (autoescaping on by default) from
``app.state.templates``. All state-changing POST handlers are protected by
``require_csrf``; validation failures re-render the form with a 400 status
and a field-level ``errors`` dict. Output is escaped everywhere; the only
place raw HTML could appear (descriptions/titles) goes through Jinja's
autoescape so it is escaped too.
"""

import re
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..deps import ensure_csrf_token, flash, get_db, pop_flashes, require_csrf
from ..models import STATUSES, Project, Task
from ..schemas import _not_blank

router = APIRouter(tags=["pages"])

_TASK_TITLE_MAX = 200
_TASK_DESC_MAX = 4000
_PROJECT_NAME_MAX = 120
_PROJECT_DESC_MAX = 2000
_ID_RE = re.compile(r"^\d+$")


def _render(
    request: Request, name: str, context: dict[str, Any], status_code: int = 200
):
    templates = request.app.state.templates
    base = {
        "build_marker": request.app.state.build_marker,
        "statuses": STATUSES,
        "csrf_token": ensure_csrf_token(request),
        "flashes": pop_flashes(request),
    }
    base.update(context)
    return templates.TemplateResponse(request, name, base, status_code=status_code)


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)


def _filters(request: Request) -> tuple[str, str, str]:
    status_ = (request.query_params.get("status") or "").strip()
    if status_ not in STATUSES:
        status_ = ""
    q = (request.query_params.get("q") or "").strip()[:100]
    pattern = f"%{q.lower()}%"
    return status_, q, pattern


def _filtered_tasks(
    db: Session, project_id: int | None = None, status_: str = "", pattern: str = ""
) -> list[Task]:
    stmt = select(Task).order_by(Task.created_at.desc(), Task.id.desc())
    if project_id is not None:
        stmt = stmt.where(Task.project_id == project_id)
    if status_:
        stmt = stmt.where(Task.status == status_)
    if pattern:
        stmt = stmt.where(
            or_(Task.title.ilike(pattern), Task.description.ilike(pattern))
        )
    return list(db.execute(stmt).scalars())


def _group_tasks(tasks: list[Task]) -> tuple[dict[int, list[Task]], list[Task]]:
    by_project: dict[int, list[Task]] = {}
    unassigned: list[Task] = []
    for task in tasks:
        if task.project_id is None:
            unassigned.append(task)
        else:
            by_project.setdefault(task.project_id, []).append(task)
    return by_project, unassigned


def _project_counts(db: Session) -> dict[int, int]:
    rows = db.execute(
        select(Task.project_id, func.count(Task.id)).group_by(Task.project_id)
    ).all()
    return {pid: count for pid, count in rows}


def _validate_project(name: str, description: str) -> dict[str, str]:
    errors: dict[str, str] = {}
    if not name or not name.strip():
        errors["name"] = "Project name is required."
    return errors


def _validate_task(
    db: Session, title: str, description: str, status_: str, project_id: int | None
) -> dict[str, str]:
    errors: dict[str, str] = {}
    if not title or not title.strip():
        errors["title"] = "Task title is required."
    if status_ not in STATUSES:
        errors["status"] = f"Invalid status. Allowed: {', '.join(STATUSES)}."
    if project_id is not None and db.get(Project, project_id) is None:
        errors["project_id"] = "Selected project does not exist."
    return errors


def _parse_project_id(raw: str | None) -> int | None:
    if raw is None or raw == "":
        return None
    if not _ID_RE.match(raw):
        raise HTTPException(status_code=400, detail="Invalid project selection.")
    return int(raw)


def _load_projects(db: Session) -> list[Project]:
    return list(db.execute(select(Project).order_by(Project.name)).scalars())


def _project_or_404(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return project


def _task_or_404(db: Session, task_id: int) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return task


# ---------------------------------------------------------------- board / index


@router.get("/")
def index(request: Request, db: Session = Depends(get_db)):
    status_, q, pattern = _filters(request)
    tasks = _filtered_tasks(db, status_=status_, pattern=pattern)
    by_project, unassigned = _group_tasks(tasks)
    counts = _project_counts(db)
    projects = _load_projects(db)
    return _render(
        request,
        "index.html",
        {
            "projects": projects,
            "by_project": by_project,
            "unassigned": unassigned,
            "counts": counts,
            "status": status_,
            "q": q,
        },
    )


# ---------------------------------------------------------------- projects


@router.get("/projects/new")
def project_new_form(request: Request, db: Session = Depends(get_db)):
    return _render(request, "project_form.html", {"project": None})


@router.post("/projects/new", dependencies=[Depends(require_csrf)])
async def project_new_submit(
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(""),
    description: str = Form(""),
):
    name = name.strip()[:_PROJECT_NAME_MAX]
    description = description.strip()[:_PROJECT_DESC_MAX]
    errors = _validate_project(name, description)
    if errors:
        return _render(
            request,
            "project_form.html",
            {
                "project": None,
                "name": name,
                "description": description,
                "errors": errors,
            },
            status_code=400,
        )
    project = Project(name=name, description=description)
    db.add(project)
    db.commit()
    db.refresh(project)
    flash(request, "Project created.", "success")
    return _redirect(f"/projects/{project.id}")


@router.get("/projects/{project_id}")
def project_detail(project_id: int, request: Request, db: Session = Depends(get_db)):
    project = _project_or_404(db, project_id)
    status_, q, pattern = _filters(request)
    tasks = _filtered_tasks(db, project_id=project_id, status_=status_, pattern=pattern)
    return _render(
        request,
        "project.html",
        {
            "project": project,
            "tasks": tasks,
            "status": status_,
            "q": q,
        },
    )


@router.get("/projects/{project_id}/edit")
def project_edit_form(project_id: int, request: Request, db: Session = Depends(get_db)):
    project = _project_or_404(db, project_id)
    return _render(request, "project_form.html", {"project": project})


@router.post("/projects/{project_id}/edit", dependencies=[Depends(require_csrf)])
async def project_edit_submit(
    project_id: int,
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(""),
    description: str = Form(""),
):
    project = _project_or_404(db, project_id)
    name = name.strip()[:_PROJECT_NAME_MAX]
    description = description.strip()[:_PROJECT_DESC_MAX]
    errors = _validate_project(name, description)
    if errors:
        return _render(
            request,
            "project_form.html",
            {
                "project": project,
                "name": name,
                "description": description,
                "errors": errors,
            },
            status_code=400,
        )
    project.name = name
    project.description = description
    db.commit()
    flash(request, "Project updated.", "success")
    return _redirect(f"/projects/{project.id}")


@router.post("/projects/{project_id}/delete", dependencies=[Depends(require_csrf)])
async def project_delete(
    project_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    project = _project_or_404(db, project_id)
    db.delete(project)
    db.commit()
    flash(request, "Project deleted; its tasks are now unassigned.", "success")
    return _redirect("/")


# ---------------------------------------------------------------- tasks


def _task_form_context(
    task: Task | None,
    projects: list[Project],
    title: str,
    description: str,
    status_: str,
    selected_project_id: int | None,
    errors: dict[str, str] | None,
) -> dict[str, Any]:
    return {
        "task": task,
        "projects": projects,
        "title": title,
        "description": description,
        "status": status_,
        "selected_project_id": selected_project_id,
        "errors": errors or {},
    }


@router.get("/tasks/new")
def task_new_form(request: Request, db: Session = Depends(get_db)):
    selected = request.query_params.get("project_id")
    selected_id = _parse_project_id(selected) if selected else None
    return _render(
        request,
        "task_form.html",
        _task_form_context(None, _load_projects(db), "", "", "todo", selected_id, None),
    )


@router.post("/tasks/new", dependencies=[Depends(require_csrf)])
async def task_new_submit(
    request: Request,
    db: Session = Depends(get_db),
    title: str = Form(""),
    description: str = Form(""),
    project_id: str | None = Form(None),
    status_: str = Form("todo", alias="status"),
):
    title = title.strip()[:_TASK_TITLE_MAX]
    description = description.strip()[:_TASK_DESC_MAX]
    pid = _parse_project_id(project_id)
    errors = _validate_task(db, title, description, status_, pid)
    if errors:
        return _render(
            request,
            "task_form.html",
            _task_form_context(
                None, _load_projects(db), title, description, status_, pid, errors
            ),
            status_code=400,
        )
    task = Task(project_id=pid, title=title, description=description, status=status_)
    db.add(task)
    db.commit()
    flash(request, "Task created.", "success")
    return _redirect("/")


@router.get("/tasks/{task_id}/edit")
def task_edit_form(task_id: int, request: Request, db: Session = Depends(get_db)):
    task = _task_or_404(db, task_id)
    return _render(
        request,
        "task_form.html",
        _task_form_context(
            task,
            _load_projects(db),
            task.title,
            task.description,
            task.status,
            task.project_id,
            None,
        ),
    )


@router.post("/tasks/{task_id}/edit", dependencies=[Depends(require_csrf)])
async def task_edit_submit(
    task_id: int,
    request: Request,
    db: Session = Depends(get_db),
    title: str = Form(""),
    description: str = Form(""),
    project_id: str | None = Form(None),
    status_: str = Form("todo", alias="status"),
):
    task = _task_or_404(db, task_id)
    title = title.strip()[:_TASK_TITLE_MAX]
    description = description.strip()[:_TASK_DESC_MAX]
    pid = _parse_project_id(project_id)
    errors = _validate_task(db, title, description, status_, pid)
    if errors:
        return _render(
            request,
            "task_form.html",
            _task_form_context(
                task, _load_projects(db), title, description, status_, pid, errors
            ),
            status_code=400,
        )
    task.title = title
    task.description = description
    task.status = status_
    task.project_id = pid
    db.commit()
    flash(request, "Task updated.", "success")
    return _redirect("/")


@router.post("/tasks/{task_id}/status", dependencies=[Depends(require_csrf)])
async def task_status_submit(
    task_id: int,
    request: Request,
    db: Session = Depends(get_db),
    status_: str = Form("", alias="status"),
):
    if status_ not in STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Allowed: {', '.join(STATUSES)}.",
        )
    task = _task_or_404(db, task_id)
    task.status = status_
    db.commit()
    flash(request, "Task status updated.", "success")
    return _redirect(request.headers.get("referer") or "/")


@router.post("/tasks/{task_id}/delete", dependencies=[Depends(require_csrf)])
async def task_delete(
    task_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    task = _task_or_404(db, task_id)
    db.delete(task)
    db.commit()
    flash(request, "Task deleted.", "success")
    return _redirect(request.headers.get("referer") or "/")
