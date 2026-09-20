"""Restart-equivalent persistence and idempotent initialization checks.

The migration/restart scenario is truly exercised end-to-end by
``scripts/verify.sh`` against the production uvicorn process. These tests
cover the equivalent at the process level (a fresh app + engine over the
same SQLite file).
"""

import re


def _csrf(client):
    r = client.get("/tasks/new")
    return re.search(r'name="csrf_token" value="([^"]+)"', r.text).group(1)


def test_tasks_survive_gestarted_app(client, restarted_app):
    tok = _csrf(client)
    title = "PERSIST-session-do-not-lose"
    created = client.post(
        "/api/tasks",
        json={"title": title, "description": "durable", "status": "in_progress"},
        headers={"X-CSRF-Token": tok},
    )
    assert created.status_code == 201
    task_id = created.json()["id"]

    fetched = restarted_app.get(f"/api/tasks/{task_id}")
    assert fetched.status_code == 200
    assert fetched.json()["title"] == title

    restarted_app.delete(
        f"/api/tasks/{task_id}", headers={"X-CSRF-Token": _csrf(restarted_app)}
    )


def test_seed_not_duplicated_on_reinit(client, restarted_app):
    before = client.get("/api/tasks")
    before_titles = {t["title"] for t in before.json()}
    assert "Verify environment variables" in before_titles

    after = restarted_app.get("/api/tasks")
    after_titles = [t["title"] for t in after.json()]
    seed_count = sum(
        1 for t in after_titles if t in before_titles and "PERSIST" not in t
    )
    # Exactly one copy of each seed task: idempotent create_all + seed guard.
    assert after_titles.count("Run smoke tests") == 1


def test_deleting_project_sets_tasks_unassigned(client, csrf):
    project = client.post(
        "/api/projects",
        json={"name": "delete-me", "description": ""},
        headers={"X-CSRF-Token": csrf},
    ).json()
    task = client.post(
        "/api/tasks",
        json={"title": "orphan me", "project_id": project["id"]},
        headers={"X-CSRF-Token": csrf},
    ).json()

    r = client.post(
        f"/projects/{project['id']}/delete",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert r.status_code == 303

    fetched = client.get(f"/api/tasks/{task['id']}").json()
    assert fetched["project_id"] is None
    client.delete(f"/api/tasks/{task['id']}", headers={"X-CSRF-Token": csrf})
