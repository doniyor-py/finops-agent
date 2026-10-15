"""HTTP-level tests: health check, auth flow and config validation."""

import os
import uuid

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("db") / "finoks-test.db"
    os.environ["FINOKS_DATABASE_URL"] = f"sqlite:///{db_path}"
    from main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def token(client):
    email = f"user-{uuid.uuid4().hex[:8]}@example.com"
    r = client.post("/users/register", json={"email": email, "password": "correct-horse-1"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_health(client):
    assert client.get("/health").json() == {"status": "ok", "service": "finoks"}


def test_register_then_login(client):
    email = f"login-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/users/register", json={"email": email, "password": "correct-horse-1"})
    r = client.post("/users/login", json={"email": email.upper(), "password": "correct-horse-1"})
    assert r.status_code == 200
    assert r.json()["access_token"]


def test_duplicate_registration_is_rejected(client):
    email = f"dupe-{uuid.uuid4().hex[:8]}@example.com"
    body = {"email": email, "password": "correct-horse-1"}
    assert client.post("/users/register", json=body).status_code == 200
    assert client.post("/users/register", json=body).status_code == 409


def test_wrong_password_is_rejected(client, token):
    r = client.post("/users/login", json={"email": "nobody@example.com", "password": "nope"})
    assert r.status_code == 401


def test_agent_routes_require_auth(client):
    assert client.get("/agent/config").status_code == 401


def test_me_returns_current_user(client, token):
    assert client.get("/users/me", headers=auth(token)).status_code == 200


def test_config_rejects_unknown_mode(client, token):
    r = client.post("/agent/config", json={"mode": "yolo"}, headers=auth(token))
    assert r.status_code == 400


def test_config_rejects_negative_threshold(client, token):
    r = client.post("/agent/config", json={"threshold_gbp": -1}, headers=auth(token))
    assert r.status_code == 400


def test_config_update_is_applied(client, token):
    r = client.post("/agent/config", json={"mode": "human_all", "threshold_gbp": 750}, headers=auth(token))
    assert r.status_code == 200
    cfg = r.json()["autonomy_config"]
    assert cfg["mode"] == "human_all"
    assert cfg["threshold_gbp"] == 750.0
