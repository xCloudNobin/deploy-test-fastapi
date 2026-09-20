"""Liveness, readiness and dependency-failure behavior."""


def test_health_liveness(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["app"] == "deploy-test-fastapi"


def test_readiness_ok(client):
    r = client.get("/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    assert body["database"] == "ok"


def test_readiness_fails_when_db_unavailable(broken_db_app):
    assert broken_db_app.get("/health").status_code == 200
    r = broken_db_app.get("/ready")
    assert r.status_code == 503
    assert r.json()["status"] == "unavailable"


def test_pages_degrade_when_db_unavailable(broken_db_app):
    r = broken_db_app.get("/")
    assert r.status_code == 503
    assert "Database is unavailable" in r.text


def test_api_degrades_with_json_when_db_unavailable(broken_db_app):
    r = broken_db_app.get("/api/tasks")
    assert r.status_code == 503
    assert r.json()["status"] == "unavailable"
