"""Pydantic request/response schemas for the API.

Request validation happens at the schema boundary (FastAPI returns 422 with
a structured ``detail``). Existence checks that need the database (e.g. an
unknown ``project_id``) are handled in the routers with a ``400`` error
whose body matches the shared suite convention: ``{"errors": {...}}``.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Status = Literal["todo", "in_progress", "done"]


def _not_blank(value: str, field_name: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{field_name} must not be empty")
    return value


class ProjectCreate(BaseModel):
    name: str = Field(..., max_length=120, min_length=1)
    description: str = Field("", max_length=2000)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        return _not_blank(value, "name")


class ProjectUpdate(BaseModel):
    name: str | None = Field(None, max_length=120, min_length=1)
    description: str | None = Field(None, max_length=2000)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _not_blank(value, "name")


class TaskCreate(BaseModel):
    project_id: int | None = Field(None, ge=1)
    title: str = Field(..., max_length=200, min_length=1)
    description: str = Field("", max_length=4000)
    status: Status = "todo"

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str) -> str:
        return _not_blank(value, "title")


class TaskUpdate(BaseModel):
    project_id: int | None = Field(None, ge=1)
    title: str | None = Field(None, max_length=200, min_length=1)
    description: str | None = Field(None, max_length=4000)
    status: Status | None = None

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _not_blank(value, "title")


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    created_at: datetime
    task_count: int = 0


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int | None
    project_name: str | None = None
    title: str
    description: str
    status: str
    created_at: datetime
    updated_at: datetime
