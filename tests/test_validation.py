"""Negative and validation tests: meaningful errors for bad input."""

import re


def _csrf(client):
    r = client.get("/tasks/new")
    return re.search(r'name="csrf_token" value="([^"]+)"', r.text).group(1)


def test_create_task_missing_title(client):
    r = client.post(
        "/api/tasks", json={"title": ""}, headers={"X-CSRF-Token": _csrf(client)}
    )
    assert r.status_code == 422
    assert any(e["loc"][-1] == "title" for e in r.json()["detail"])


def test_create_task_invalid_status(client):
    r = client.post(
        "/api/tasks",
        json={"title": "x", "status": "warp"},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert r.status_code == 422


def test_create_task_unknown_project(client):
    r = client.post(
        "/api/tasks",
        json={"title": "x", "project_id": 999999},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert r.status_code == 400
    body = r.json()
    assert body["errors"]["project_id"] == "Selected project does not exist."


def test_malformed_json_body(client):
    r = client.post(
        "/api/tasks",
        content=b"{oops",
        headers={"Content-Type": "application/json", "X-CSRF-Token": _csrf(client)},
    )
    assert r.status_code == 422


def test_missing_csrf_rejected(client):
    no_csrf = client.post("/api/tasks", json={"title": "x", "status": "todo"})
    assert no_csrf.status_code == 403


def test_wrong_csrf_rejected(client):
    r = client.post(
        "/api/tasks",
        json={"title": "x", "csrf_token": "nope"},
        headers={"X-CSRF-Token": "nope"},
    )
    assert r.status_code == 403


def test_invalid_status_filter(client):
    r = client.get("/api/tasks", params={"status": "nope"})
    assert r.status_code == 400
    assert "errors" in r.json()


def test_unknown_task_404(client):
    r = client.get("/api/tasks/9999999")
    assert r.status_code == 404


def test_unknown_project_page_404(client):
    r = client.get("/projects/9999999")
    assert r.status_code == 404
    assert "404" in r.text


def test_invalid_project_id_path_422(client):
    r = client.get("/projects/not-a-number")
    assert r.status_code == 422


def test_project_empty_name_html(client):
    tok = _csrf(client)
    r = client.post(
        "/projects/new",
        data={"name": "", "description": "d", "csrf_token": tok},
    )
    assert r.status_code == 400
    assert "Project name is required" in r.text


def test_task_empty_title_html(client):
    tok = _csrf(client)
    r = client.post(
        "/tasks/new",
        data={"title": "", "status": "todo", "csrf_token": tok},
    )
    assert r.status_code == 400
    assert "Task title is required" in r.text


def test_task_invalid_status_html(client):
    tok = _csrf(client)
    r = client.post(
        "/tasks/new",
        data={"title": "x", "status": "bogus", "csrf_token": tok},
    )
    assert r.status_code == 400
    assert "Invalid status" in r.text


def test_html_missing_csrf(client):
    r = client.post("/tasks/new", data={"title": "x", "status": "todo"})
    assert r.status_code == 403


def test_delete_unknown_task_404(client):
    r = client.delete("/api/tasks/9999999", headers={"X-CSRF-Token": _csrf(client)})
    assert r.status_code == 404
