"""Deterministic, repeatable seed data for a fresh database.

Sample data is inserted only when the tasks table is empty, with fixed
values, so re-initialization never duplicates and databases are
reproducible. The values mirror the shared suite fixture so deployments
across targets look the same.
"""

from .models import STATUSES

SEED_PROJECTS = (
    {
        "name": "Website Redesign",
        "description": "Refresh the public marketing site.",
        "tasks": (
            (
                "Draft new homepage layout",
                "Reorganise the hero section.",
                "in_progress",
            ),
            (
                "Collect stakeholder feedback",
                "Walk the draft past the product team.",
                "todo",
            ),
        ),
    },
    {
        "name": "Launch Checklist",
        "description": "Tasks required before the next release ships.",
        "tasks": (
            (
                "Verify environment variables",
                "Confirm all settings exist in production.",
                "done",
            ),
            ("Run smoke tests", "Exercise CRUD plus restart persistence.", "todo"),
        ),
    },
)


def assert_seed_sane() -> None:
    for project in SEED_PROJECTS:
        for _title, _description, status in project["tasks"]:
            assert status in STATUSES  # noqa: S101
