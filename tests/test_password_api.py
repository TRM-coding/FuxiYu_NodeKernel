from __future__ import annotations

import inspect
import json
import time

import docker
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from FuxiYu_NodeKernel import create_app, extensions
from FuxiYu_NodeKernel.network import api as api_module
from FuxiYu_NodeKernel.schemas import ResetContainerPasswordConfig, ResetContainerPasswordMessage
from FuxiYu_NodeKernel.services.container_service import ContainerNotRunning, CreateContainerReturn

from .conftest import FakeDockerClient, docker_not_found

PW = "Role#Password9"
ROOT_PW = "Root#Password9"
VALID_CFG = {
    "gpu_list": [],
    "cpu_number": 2,
    "memory": 4,
    "shared_memory": 0,
    "name": "c1",
    "port": 2233,
    "image": "ubuntu:22.04",
}


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(extensions, "docker_client", FakeDockerClient())
    return TestClient(create_app())


def _patch_service(monkeypatch, name, fn):
    monkeypatch.setattr(api_module, name, fn)


def _reset_payload(user_name="u1", password=PW):
    return {"config": {"container_name": "c1", "user_name": user_name, "password": password}}


def test_reset_endpoint_cases(client, monkeypatch, capsys):
    seen = []
    _patch_service(monkeypatch, "reset_container_password", lambda *a: seen.append(a) or True)
    resp = client.post("/api/reset_container_password", json=_reset_payload())
    assert resp.status_code == 200
    assert resp.json() == {"success": 1}
    assert resp.headers["Cache-Control"] == "no-store"
    assert seen[-1][0:2] == ("c1", "u1")

    resp = client.post("/api/reset_container_password", json=_reset_payload("root"))
    assert resp.status_code == 200
    assert resp.json() == {"success": 1}
    assert seen[-1][0:2] == ("c1", "root")

    def _not_found(*_a):
        raise docker_not_found()

    _patch_service(monkeypatch, "reset_container_password", _not_found)
    resp = client.post("/api/reset_container_password", json=_reset_payload())
    assert resp.status_code == 404
    assert resp.json()["error_reason"] == "not_found"
    assert PW not in resp.text

    def _not_running(*_a):
        raise ContainerNotRunning("not running")

    _patch_service(monkeypatch, "reset_container_password", _not_running)
    resp = client.post("/api/reset_container_password", json=_reset_payload())
    assert resp.status_code == 409
    assert resp.json()["error_reason"] == "container_not_running"

    _patch_service(monkeypatch, "reset_container_password", lambda *a: (_ for _ in ()).throw(RuntimeError("chpasswd failed")))
    resp = client.post("/api/reset_container_password", json=_reset_payload())
    assert resp.status_code == 500
    assert resp.json()["error_reason"] == "reset_failed"
    assert PW not in resp.text

    resp = client.post("/api/reset_container_password", json=_reset_payload(password="short"))
    assert resp.status_code == 422
    assert PW not in resp.text
    assert "input" not in resp.text and "ctx" not in resp.text

    resp = client.post("/api/reset_container_password", json=_reset_payload("bad;name"))
    assert resp.status_code == 422
    assert "bad;name" not in resp.text
    assert PW not in resp.text
    assert PW not in capsys.readouterr().out


def test_password_routes_no_store(client, monkeypatch):
    resp = client.post("/api/create_container", json={"owner_name": "admin", "config": VALID_CFG})
    assert resp.status_code == 422
    assert resp.headers["Cache-Control"] == "no-store"

    _patch_service(monkeypatch, "add_collaborator", lambda *a, **k: True)
    resp = client.post(
        "/api/add_collaborator",
        json={"config": {"container_name": "c1", "user_name": "u1", "role": "admin", "password": PW}},
    )
    assert resp.status_code == 200 and resp.headers["Cache-Control"] == "no-store"

    _patch_service(monkeypatch, "update_role", lambda *a, **k: True)
    resp = client.post(
        "/api/update_role",
        json={"config": {"container_name": "c1", "user_name": "u1", "updated_role": "root", "root_password": ROOT_PW}},
    )
    assert resp.status_code == 200 and resp.headers["Cache-Control"] == "no-store"

    _patch_service(monkeypatch, "reset_container_password", lambda *a: True)
    resp = client.post("/api/reset_container_password", json=_reset_payload())
    assert resp.status_code == 200 and resp.headers["Cache-Control"] == "no-store"


def test_password_route_422_redaction(client):
    # Sibling field missing while a valid secret is present: no input/ctx echo.
    payload = {"owner_name": "admin", "root_password": ROOT_PW, "config": {"gpu_list": []}}
    resp = client.post("/api/create_container", json=payload)
    assert resp.status_code == 422
    assert ROOT_PW not in resp.text
    assert "input" not in resp.text and "ctx" not in resp.text

    resp = client.post("/api/reset_container_password", json=_reset_payload(password="short"))
    assert resp.status_code == 422
    assert "short" not in resp.text
    assert "input" not in resp.text and "ctx" not in resp.text

    resp = client.post("/api/reset_container_password", json=_reset_payload(password=123))
    assert resp.status_code == 422
    assert "123" not in resp.text
    assert "input" not in resp.text and "ctx" not in resp.text


def test_non_password_route_default_422(client):
    resp = client.post("/api/container_status", json={"config": "bad"})
    assert resp.status_code == 422
    assert "success" not in resp.json()
    assert resp.headers.get("Cache-Control") != "no-store"
    assert "detail" in resp.json()


def test_add_collab_response_redacts(client, monkeypatch):
    _patch_service(monkeypatch, "add_collaborator", lambda *a, **k: True)
    payload = {"config": {"container_name": "c1", "user_name": "u1", "role": "admin", "password": PW}}
    resp = client.post("/api/add_collaborator", json=payload)
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert resp.json()["decrypted_message"] == {"container_name": "c1", "user_name": "u1", "role": "admin"}
    assert PW not in resp.text

    def _boom(*_a, **_k):
        raise RuntimeError(f"password={PW}")

    _patch_service(monkeypatch, "add_collaborator", _boom)
    resp = client.post("/api/add_collaborator", json=payload)
    assert resp.status_code == 500
    assert PW not in resp.text
    assert resp.json()["error_reason"] == "add_failed"


def test_update_role_response_redacts(client, monkeypatch):
    _patch_service(monkeypatch, "update_role", lambda *a, **k: True)
    payload = {
        "config": {
            "container_name": "c1",
            "user_name": "u1",
            "updated_role": "root",
            "root_password": ROOT_PW,
        }
    }
    resp = client.post("/api/update_role", json=payload)
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert resp.json()["decrypted_message"] == {
        "container_name": "c1",
        "user_name": "u1",
        "updated_role": "root",
    }
    assert ROOT_PW not in resp.text

    admin_payload = {
        "config": {
            "container_name": "c1",
            "user_name": "old_root",
            "updated_role": "admin",
            "password": PW,
        }
    }
    resp = client.post("/api/update_role", json=admin_payload)
    assert resp.status_code == 200
    assert PW not in resp.text


def test_responses_no_credentials(client, monkeypatch):
    _patch_service(monkeypatch, "container_exists", lambda name: False)
    _patch_service(
        monkeypatch,
        "create_container",
        lambda owner_name, cfg, *, root_password, public_key=None, restore_mount_path=None: CreateContainerReturn("cid", cfg.name),
    )
    resp = client.post(
        "/api/create_container",
        json={"owner_name": "admin", "config": VALID_CFG, "root_password": ROOT_PW},
    )
    assert resp.status_code == 200
    assert "credentials" not in resp.text and ROOT_PW not in resp.text

    _patch_service(monkeypatch, "add_collaborator", lambda *a, **k: True)
    resp = client.post(
        "/api/add_collaborator",
        json={"config": {"container_name": "c1", "user_name": "u1", "role": "admin", "password": PW}},
    )
    assert "credentials" not in resp.text and PW not in resp.text

    _patch_service(monkeypatch, "update_role", lambda *a, **k: True)
    resp = client.post(
        "/api/update_role",
        json={"config": {"container_name": "c1", "user_name": "u1", "updated_role": "root", "root_password": ROOT_PW}},
    )
    assert "credentials" not in resp.text and ROOT_PW not in resp.text

    _patch_service(monkeypatch, "reset_container_password", lambda *a: True)
    resp = client.post("/api/reset_container_password", json=_reset_payload())
    assert resp.json() == {"success": 1}
    assert PW not in resp.text


def test_password_not_in_status_or_wss(client, monkeypatch):
    message = api_module.CreateContainerMessage(
        owner_name="admin", config=VALID_CFG, root_password=SecretStr(ROOT_PW)
    )
    dumped = json.dumps(message.model_dump(), default=str)
    assert ROOT_PW not in dumped
    assert "credentials" not in dumped

    class _NoopCache:
        node_epoch = "epoch"
        def submit_action(self, *a, **k):
            return {"node_epoch": "epoch", "generation": 0, "seq": 1}
        def set_port_info(self, *a, **k):
            pass
        def refresh_from_docker(self, *a, **k):
            pass

    monkeypatch.setattr(extensions, "status_cache", _NoopCache())
    _patch_service(monkeypatch, "container_exists", lambda name: False)
    _patch_service(
        monkeypatch,
        "create_container",
        lambda owner_name, cfg, *, root_password, public_key=None, restore_mount_path=None: CreateContainerReturn("cid", cfg.name),
    )
    resp = client.post(
        "/api/create_container",
        json={"owner_name": "admin", "config": VALID_CFG, "root_password": ROOT_PW},
    )
    assert resp.status_code == 200
    assert ROOT_PW not in resp.text


def test_no_password_lookup_endpoint(client):
    paths = client.get("/openapi.json").json()["paths"]
    for path, methods in paths.items():
        if "password" in path:
            assert set(methods).issubset({"post"}), path


def test_no_duplicate_password_audit(client, monkeypatch, caplog, capsys):
    _patch_service(monkeypatch, "add_collaborator", lambda *a, **k: True)
    client.post(
        "/api/add_collaborator",
        json={"config": {"container_name": "c1", "user_name": "u1", "role": "admin", "password": PW}},
    )
    _patch_service(monkeypatch, "reset_container_password", lambda *a: True)
    client.post("/api/reset_container_password", json=_reset_payload())
    text = capsys.readouterr().out + caplog.text
    assert PW not in text
    assert "password=" not in text


def test_create_restore_password_failure(client, monkeypatch):
    cfg = dict(VALID_CFG)
    cfg["name"] = "restore_fail_c"
    _patch_service(monkeypatch, "container_exists", lambda name: False)
    _patch_service(
        monkeypatch,
        "create_container",
        lambda owner_name, container_cfg, *, root_password, public_key=None, restore_mount_path=None: CreateContainerReturn(
            "cid", container_cfg.name
        ),
    )
    _patch_service(monkeypatch, "add_collaborator", lambda *a, **k: False)
    resp = client.post(
        "/api/create_container",
        json={
            "owner_name": "admin",
            "config": cfg,
            "root_password": ROOT_PW,
            "restore_accounts": [{"user_name": "alice", "role": "collaborator", "password": PW}],
        },
    )
    assert resp.status_code == 200
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        last = extensions.status_cache.get_state(cfg["name"]).get("last_action") or {}
        if last.get("phase") == "failed":
            break
        time.sleep(0.02)
    last = extensions.status_cache.get_state(cfg["name"]).get("last_action") or {}
    assert last.get("phase") == "failed"
    assert last.get("error_reason") == "create_failed"
    assert ROOT_PW not in resp.text and PW not in resp.text


def test_failure_response_no_secret(client, monkeypatch):
    _patch_service(monkeypatch, "reset_container_password", lambda *a: (_ for _ in ()).throw(RuntimeError(f"secret={PW}")))
    resp = client.post("/api/reset_container_password", json=_reset_payload())
    assert resp.status_code == 500
    assert PW not in resp.text

    _patch_service(monkeypatch, "update_role", lambda *a, **k: (_ for _ in ()).throw(RuntimeError(f"secret={ROOT_PW}")))
    resp = client.post(
        "/api/update_role",
        json={"config": {"container_name": "c1", "user_name": "u1", "updated_role": "root", "root_password": ROOT_PW}},
    )
    assert resp.status_code == 500
    assert ROOT_PW not in resp.text


def test_sync_disconnect_continues(monkeypatch):
    called = []
    monkeypatch.setattr(api_module, "reset_container_password", lambda *a: called.append(a) or True)
    assert inspect.iscoroutinefunction(api_module.reset_container_password_api) is False
    msg = ResetContainerPasswordMessage(
        config=ResetContainerPasswordConfig(container_name="c1", user_name="root", password=SecretStr(PW))
    )
    result = api_module.reset_container_password_api(msg)
    assert result == {"success": 1}
    assert called and called[0][1] == "root"
