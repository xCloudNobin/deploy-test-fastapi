"""CRUD, search/filter and persistence behavior via the JSON API + UI."""

import re


def _csrf(client):
    r = client.get("/tasks/new")
    return re.search(r'name="csrf_token" value="([^"]+)"', r.text).group(1)


def test_api_task_crud(client):
    tok = _csrf(client)
    created = client.post(
        "/api/tasks",
        json={"title": "CRUD create", "description": "via api", "status": "todo"},
        headers={"X-CSRF-Token": tok},
    )
    assert created.status_code == 201
    task = created.json()
    task_id = task["id"]

    fetched = client.get(f"/api/tasks/{task_id}")
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "CRUD create"

    updated = client.patch(
        f"/api/tasks/{task_id}",
        json={"title": "CRUD updated", "status": "in_progress"},
        headers={"X-CSRF-Token": tok},
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["title"] == "CRUD updated"
    assert body["status"] == "in_progress"

    deleted = client.delete(f"/api/tasks/{task_id}", headers={"X-CSRF-Token": tok})
    assert deleted.status_code == 204

    gone = client.get(f"/api/tasks/{task_id}")
    assert gone.status_code == 404


def test_api_unassign_project_via_null(client, csrf):
    project = client.post(
        "/api/projects",
        json={"name": "Unassign proj", "description": ""},
        headers={"X-CSRF-Token": csrf},
    ).json()
    task = client.post(
        "/api/tasks",
        json={"title": "will be unassigned", "project_id": project["id"]},
        headers={"X-CSRF-Token": csrf},
    ).json()
    updated = client.patch(
        f"/api/tasks/{task['id']}",
        json={"project_id": None},
        headers={"X-CSRF-Token": csrf},
    )
    assert updated.status_code == 200
    assert updated.json()["project_id"] is None
    assert updated.json()["project_name"] is None
    client.delete(f"/api/tasks/{task['id']}", headers={"X-CSRF-Token": csrf})


def test_api_search_and_status_filter(client, csrf):
    client.post(
        "/api/tasks",
        json={"title": "Unique-Seabream-12345", "description": "search target"},
        headers={"X-CSRF-Token": csrf},
    )
    r = client.get("/api/tasks", params={"q": "Seabream"})
    assert r.status_code == 200
    assert any(t["title"] == "Unique-Seabream-12345" for t in r.json())

    r = client.get("/api/tasks", params={"q": "seabream", "status": "todo"})
    assert r.status_code == 200
    assert any(t["title"] == "Unique-Seabream-12345" for t in r.json())

    r = client.get("/api/tasks", params={"q": "seabream", "status": "done"})
    assert r.status_code == 200
    assert not any(t["title"] == "Unique-Seabream-12345" for t in r.json())


def test_api_project_crud_and_count(client, csrf):
    created = client.post(
        "/api/projects",
        json={"name": "Count project", "description": "d"},
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 201
    project = created.json()
    assert project["task_count"] == 0

    client.post(
        "/api/tasks",
        json={"title": "task a", "project_id": project["id"]},
        headers={"X-CSRF-Token": csrf},
    )
    client.post(
        "/api/tasks",
        json={"title": "task b", "project_id": project["id"]},
        headers={"X-CSRF-Token": csrf},
    )

    listing = client.get("/api/projects")
    row = next(p for p in listing.json() if p["id"] == project["id"])
    assert row["task_count"] == 2


def test_html_project_and_task_flow(client):
    tok = _csrf(client)
    r = client.post(
        "/projects/new",
        data={"name": "HTML Flow", "description": "created in html", "csrf_token": tok},
        follow_redirects=False,
    )
    assert r.status_code == 303
    project_url = r.headers["location"]

    html = client.get(project_url)
    assert "HTML Flow" in html.text

    r = client.post(
        "/tasks/new",
        data={
            "title": "HTML task",
            "description": "via form",
            "status": "todo",
            "project_id": project_url.rstrip("/").split("/")[-1],
            "csrf_token": tok,
        },
        follow_redirects=False,
    )
    assert r.status_code == 303

    detail = client.get(project_url)
    assert "HTML task" in detail.text

    task_id = re.search(r"/tasks/(\d+)/edit", detail.text)
    assert task_id is not None
    task_id = task_id.group(1)

    r = client.post(
        f"/tasks/{task_id}/edit",
        data={
            "title": "HTML task (updated)",
            "description": "",
            "status": "in_progress",
            "project_id": "",
            "csrf_token": tok,
        },
        follow_redirects=False,
    )
    assert r.status_code == 303

    r = client.post(
        f"/tasks/{task_id}/status",
        data={"status": "done", "csrf_token": tok},
        follow_redirects=False,
    )
    assert r.status_code == 303

    r = client.post(
        f"/tasks/{task_id}/delete",
        data={"csrf_token": tok},
        follow_redirects=False,
    )
    assert r.status_code == 303


def test_html_edit_project(client):
    tok = _csrf(client)
    r = client.post(
        "/projects/new",
        data={"name": "Editable proj", "description": "old", "csrf_token": tok},
        follow_redirects=False,
    )
    project_id = r.headers["location"].rstrip("/").split("/")[-1]

    r = client.post(
        f"/projects/{project_id}/edit",
        data={"name": "Editable proj 2", "description": "new", "csrf_token": tok},
        follow_redirects=False,
    )
    assert r.status_code == 303
    html = client.get(f"/projects/{project_id}")
    assert "Editable proj 2" in html.text


def test_build_marker_rendered(client):
    r = client.get("/")
    assert "test-marker" in r.text


def test_docs_and_static_assets(client):
    assert client.get("/docs").status_code == 200
    assert client.get("/static/app.css").status_code == 200


def test_seed_data_present(client):
    r = client.get("/api/tasks")
    titles = {t["title"] for t in r.json()}
    assert "Verify environment variables" in titles
    assert "Run smoke tests" in titles
    r = client.get("/api/projects")
    names = {p["name"] for p in r.json()}
    assert "Website Redesign" in names
    assert "Launch Checklist" in names


def test_nested_project_route(client):
    r = client.get("/projects/1")
    assert r.status_code == 200
    assert "Website Redesign" in r.text or "Launch Checklist" in r.text
