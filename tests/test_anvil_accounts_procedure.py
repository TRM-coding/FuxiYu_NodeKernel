"""Anvil account / procedure mapping tests.

These tests are deliberately Node-side only: fake Docker records argv/stdin,
and the shell cleanup test runs the emitted cleanup script only with recording
command doubles. No real account, group, container or host directory is changed.
"""

from __future__ import annotations

import asyncio
import builtins
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import docker
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from FuxiYu_NodeKernel import create_app, extensions
from FuxiYu_NodeKernel.constant import ROLE
from FuxiYu_NodeKernel.docker_operates import port_allocator
from FuxiYu_NodeKernel.network import api as api_module
from FuxiYu_NodeKernel.schemas import (
    AddCollaboratorConfig,
    AddCollaboratorMessage,
    AddCollaboratorResponse,
    RemoveCollaboratorConfig,
    RemoveCollaboratorMessage,
    RemoveCollaboratorResponse,
    UpdateRoleConfig,
    UpdateRoleMessage,
    UpdateRoleResponse,
)
from FuxiYu_NodeKernel.services.container_service import (
    ContainerNotRunning,
    CreateContainerReturn,
    add_collaborator,
    create_container,
    reset_container_password,
    update_role,
)
from FuxiYu_NodeKernel.utils.Container import Container

from .conftest import FakeContainer, FakeContainers, FakeDockerClient
from .password_fakes import FakeExecAPI, PasswordFakeContainer, PasswordFakeDockerClient

REPO_ROOT = Path(__file__).resolve().parents[1]
PW = "Role#Password9"
ROOT_PW = "Root#Password9"
COLLAB_PW = "Collab#Password9"
VALID_CFG = {
    "gpu_list": [],
    "cpu_number": 2,
    "memory": 4,
    "shared_memory": 0,
    "name": "pytest_accounts_c",
    "port": 2233,
    "image": "ubuntu:22.04",
}
PROXY_KEYS = (
    "http_proxy",
    "HTTP_PROXY",
    "https_proxy",
    "HTTPS_PROXY",
    "no_proxy",
    "NO_PROXY",
)


def _client(monkeypatch, container: PasswordFakeContainer | None = None):
    containers = FakeContainers([container]) if container is not None else FakeContainers()
    docker_client = PasswordFakeDockerClient(containers)
    monkeypatch.setattr(extensions, "docker_client", docker_client)
    return TestClient(create_app()), docker_client


def _payload_update(**overrides) -> dict[str, Any]:
    config = {
        "container_name": "c1",
        "user_name": "u1",
        "updated_role": "admin",
    }
    config.update(overrides)
    return {"config": config}


def _payload_reset(
    *,
    container_name: str = "c1",
    user_name: str = "u1",
    password: str = PW,
) -> dict[str, Any]:
    return {
        "config": {
            "container_name": container_name,
            "user_name": user_name,
            "password": password,
        }
    }


def _assert_redacted(resp, *secrets: str) -> None:
    assert resp.status_code == 422, resp.text
    assert resp.headers.get("cache-control") == "no-store"
    assert '"input"' not in resp.text
    assert '"ctx"' not in resp.text
    for secret in secrets:
        if secret:
            assert secret not in resp.text


def _wait_action(name: str, phases: tuple[str, ...], timeout: float = 4.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = extensions.status_cache.get_state(name).get("last_action") or {}
        if last.get("phase") in phases:
            return last
        time.sleep(0.01)
    return last


def _commands(container: PasswordFakeContainer) -> list[str]:
    return [call[0][-1] for call in container.exec_calls]


def _install_password_client(monkeypatch, container: PasswordFakeContainer, *, exit_code: int = 0):
    client = PasswordFakeDockerClient(FakeContainers([container]), exit_code=exit_code)
    monkeypatch.setattr(extensions, "docker_client", client)
    return client


# ---------------------------------------------------------------------------
# Add collaborator config / message / response
# ---------------------------------------------------------------------------


def test_add_collaborator_config_required_and_identity_fields():
    base = {
        "container_name": "c1",
        "user_name": "u1",
        "role": "admin",
        "password": SecretStr(PW),
    }
    cfg = AddCollaboratorConfig(**base)
    assert cfg.container_name == "c1"
    assert cfg.user_name == "u1"
    assert cfg.role == "admin"
    assert cfg.password.get_secret_value() == PW

    for missing in ("container_name", "user_name", "role", "password"):
        payload = dict(base)
        del payload[missing]
        with pytest.raises(ValidationError):
            AddCollaboratorConfig(**payload)

    for field, value in (
        ("container_name", ["c1"]),
        ("user_name", {"u": 1}),
        ("role", ["admin"]),
        ("password", {"secret": PW}),
    ):
        payload = dict(base)
        payload[field] = value
        with pytest.raises(ValidationError):
            AddCollaboratorConfig(**payload)


def test_add_collaborator_message_requires_outer_config(monkeypatch):
    with pytest.raises(ValidationError):
        AddCollaboratorMessage()
    with pytest.raises(ValidationError):
        AddCollaboratorMessage(config="not-an-object")

    calls = []

    def _fake_add(container_name, user_name, role, *, password):
        calls.append((container_name, user_name, role, password.get_secret_value()))
        return True

    monkeypatch.setattr(api_module, "add_collaborator", _fake_add)
    client = TestClient(create_app())
    payload = {
        "config": {
            "container_name": "c1",
            "user_name": "u1",
            "role": "admin",
            "password": PW,
        }
    }
    resp = client.post("/api/add_collaborator", json=payload)
    assert resp.status_code == 200
    assert calls == [("c1", "u1", ROLE.ADMIN, PW)]

    resp = client.post("/api/add_collaborator", json={})
    assert resp.status_code == 422
    assert len(calls) == 1


def test_add_collaborator_response_default_and_required_message():
    response = AddCollaboratorResponse(decrypted_message={"container_name": "c1"})
    assert response.success == 1
    with pytest.raises(ValidationError):
        AddCollaboratorResponse()
    with pytest.raises(ValidationError):
        AddCollaboratorResponse(decrypted_message="not-a-mapping")


def test_add_collaborator_missing_or_invalid_password_http_422(monkeypatch, capsys, caplog):
    container = PasswordFakeContainer("c1", user_exists=True)
    client, docker_client = _client(monkeypatch, container)
    base = {
        "config": {
            "container_name": "c1",
            "user_name": "u1",
            "role": "admin",
        }
    }

    resp = client.post("/api/add_collaborator", json=base)
    _assert_redacted(resp)
    assert "u1123" not in resp.text

    for bad in (
        "",
        "short",
        "x" * 129,
        "        ",
        "abc:defgh",
        "abc\rdefgh",
        "abc\ndefgh",
        "abc\x00defgh",
    ):
        payload = json.loads(json.dumps(base))
        payload["config"]["password"] = bad
        resp = client.post("/api/add_collaborator", json=payload)
        _assert_redacted(resp, bad)

    assert container.exec_calls == []
    assert docker_client.api.created == []
    text = capsys.readouterr().out + caplog.text
    assert PW not in text
    assert "u1123" not in text


def test_add_collaborator_failure_path_redacts_and_no_fallback(monkeypatch, capsys, caplog):
    container = PasswordFakeContainer("c1", user_exists=True, exec_exit_code=1)
    client, docker_client = _client(monkeypatch, container)
    payload = {
        "config": {
            "container_name": "c1",
            "user_name": "u1",
            "role": "admin",
            "password": PW,
        }
    }
    resp = client.post("/api/add_collaborator", json=payload)
    assert resp.status_code == 200
    assert resp.json()["success"] is False
    assert PW not in resp.text
    assert "u1123" not in resp.text
    assert "credentials" not in resp.text
    assert docker_client.api.created == []
    assert container.exec_calls
    assert all(PW not in command for command in _commands(container))
    text = capsys.readouterr().out + caplog.text
    assert PW not in text
    assert "u1123" not in text


def test_remove_collaborator_wire_models_and_response_default(monkeypatch):
    cfg = RemoveCollaboratorConfig(container_name="c1", user_name="u1")
    assert cfg.container_name == "c1"
    assert cfg.user_name == "u1"
    for missing in ("container_name", "user_name"):
        payload = {"container_name": "c1", "user_name": "u1"}
        del payload[missing]
        with pytest.raises(ValidationError):
            RemoveCollaboratorConfig(**payload)
    with pytest.raises(ValidationError):
        RemoveCollaboratorConfig(container_name=["c1"], user_name="u1")

    msg = RemoveCollaboratorMessage(config={"container_name": "c1", "user_name": "u1"})
    assert msg.config.user_name == "u1"
    with pytest.raises(ValidationError):
        RemoveCollaboratorMessage()
    with pytest.raises(ValidationError):
        RemoveCollaboratorMessage(config="not-an-object")

    assert RemoveCollaboratorResponse().success == 1

    calls = []
    monkeypatch.setattr(
        api_module,
        "remove_collaborator",
        lambda container_name, user_name: calls.append((container_name, user_name)) or True,
    )
    client = TestClient(create_app())
    resp = client.post(
        "/api/remove_collaborator",
        json={"config": {"container_name": "c1", "user_name": "u1"}},
    )
    assert resp.status_code == 200
    assert resp.json() == {"success": 1}
    assert calls == [("c1", "u1")]


# ---------------------------------------------------------------------------
# Update role config / message / password matrix / responses
# ---------------------------------------------------------------------------


def test_update_role_config_required_fields_and_optional_defaults():
    cfg = UpdateRoleConfig(container_name="c1", user_name="u1", updated_role="admin")
    assert cfg.root_password is None
    assert cfg.password is None

    base = {"container_name": "c1", "user_name": "u1", "updated_role": "admin"}
    for missing in ("container_name", "user_name", "updated_role"):
        payload = dict(base)
        del payload[missing]
        with pytest.raises(ValidationError):
            UpdateRoleConfig(**payload)

    for field, value in (
        ("container_name", ["c1"]),
        ("user_name", {"u": 1}),
        ("updated_role", ["admin"]),
    ):
        payload = dict(base)
        payload[field] = value
        with pytest.raises(ValidationError):
            UpdateRoleConfig(**payload)

    for field, value in (
        ("container_name", "bad;name"),
        ("container_name", "--help"),
        ("user_name", "../root"),
        ("user_name", "u1|id"),
    ):
        payload = dict(base)
        payload[field] = value
        with pytest.raises(ValidationError):
            UpdateRoleConfig(**payload)


def test_update_role_message_requires_outer_config(monkeypatch):
    with pytest.raises(ValidationError):
        UpdateRoleMessage()
    with pytest.raises(ValidationError):
        UpdateRoleMessage(config="not-an-object")

    calls = []

    def _fake_update(container_name, user_name, updated_role, *, root_password=None, password=None):
        calls.append((container_name, user_name, updated_role, root_password, password))
        return True

    monkeypatch.setattr(api_module, "update_role", _fake_update)
    client = TestClient(create_app())
    payload = _payload_update(updated_role="root", root_password=ROOT_PW)
    resp = client.post("/api/update_role", json=payload)
    assert resp.status_code == 200
    assert calls == [("c1", "u1", ROLE.ROOT, SecretStr(ROOT_PW), None)]

    resp = client.post("/api/update_role", json={})
    assert resp.status_code == 422
    assert len(calls) == 1


def test_update_role_password_matrix_rejects_collaborator_root_password_and_admin_invalid(
    monkeypatch, capsys, caplog
):
    container = PasswordFakeContainer("c1", user_exists=True)
    client, docker_client = _client(monkeypatch, container)

    with pytest.raises(ValidationError):
        UpdateRoleConfig(
            container_name="c1",
            user_name="u1",
            updated_role="collaborator",
            root_password=SecretStr(ROOT_PW),
        )
    resp = client.post(
        "/api/update_role",
        json=_payload_update(updated_role="collaborator", root_password=ROOT_PW),
    )
    _assert_redacted(resp, ROOT_PW)

    for bad in (
        "",
        "short",
        "x" * 129,
        "        ",
        "abc:defgh",
        "abc\rdefgh",
        "abc\ndefgh",
        "abc\x00defgh",
    ):
        with pytest.raises(ValidationError):
            UpdateRoleConfig(
                container_name="c1",
                user_name="u1",
                updated_role="admin",
                password=SecretStr(bad),
            )
        resp = client.post(
            "/api/update_role",
            json=_payload_update(updated_role="admin", password=bad),
        )
        _assert_redacted(resp, bad)

    assert container.exec_calls == []
    assert docker_client.api.created == []
    text = capsys.readouterr().out + caplog.text
    assert ROOT_PW not in text
    assert PW not in text


def test_update_role_response_defaults_and_role_shapes(monkeypatch):
    response = UpdateRoleResponse(decrypted_message={"container_name": "c1"})
    assert response.success == 1
    with pytest.raises(ValidationError):
        UpdateRoleResponse()
    with pytest.raises(ValidationError):
        UpdateRoleResponse(decrypted_message="not-a-mapping")

    monkeypatch.setattr(api_module, "update_role", lambda *a, **k: True)
    client = TestClient(create_app())
    cases = [
        (
            _payload_update(updated_role="collaborator"),
            {"container_name": "c1", "user_name": "u1", "updated_role": "collaborator"},
            None,
        ),
        (
            _payload_update(updated_role="admin"),
            {"container_name": "c1", "user_name": "u1", "updated_role": "admin"},
            None,
        ),
        (
            _payload_update(
                user_name="old_root",
                updated_role="admin",
                password=PW,
            ),
            {"container_name": "c1", "user_name": "old_root", "updated_role": "admin"},
            PW,
        ),
        (
            _payload_update(updated_role="root", root_password=ROOT_PW),
            {"container_name": "c1", "user_name": "u1", "updated_role": "root"},
            ROOT_PW,
        ),
    ]
    for payload, expected, secret in cases:
        resp = client.post("/api/update_role", json=payload)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is True
        assert body["decrypted_message"] == expected
        assert "credentials" not in body
        if secret:
            assert secret not in resp.text


def test_role_literal_values_and_runtime_enum_are_distinct():
    for role in ("admin", "collaborator"):
        cfg = AddCollaboratorConfig(
            container_name="c1",
            user_name="u1",
            role=role,
            password=SecretStr(PW),
        )
        assert cfg.role == role
    for role in ("root", "hacker", "ADMIN"):
        with pytest.raises(ValidationError):
            AddCollaboratorConfig(
                container_name="c1",
                user_name="u1",
                role=role,
                password=SecretStr(PW),
            )

    for role in ("admin", "collaborator"):
        cfg = UpdateRoleConfig(container_name="c1", user_name="u1", updated_role=role)
        assert cfg.updated_role == role
    root_cfg = UpdateRoleConfig(
        container_name="c1",
        user_name="u1",
        updated_role="root",
        root_password=SecretStr(ROOT_PW),
    )
    assert root_cfg.updated_role == "root"
    for role in ("hacker", "ADMIN", "ROOT"):
        with pytest.raises(ValidationError):
            UpdateRoleConfig(container_name="c1", user_name="u1", updated_role=role)

    assert ROLE.ADMIN.value == "admin"
    assert ROLE.COLLABORATOR.value == "collaborator"
    assert ROLE.ROOT.value == "root"
    assert ROLE.ADMIN is not ROLE.COLLABORATOR
    assert isinstance("admin", ROLE) is False
    assert isinstance(ROLE.ADMIN, ROLE) is True


# ---------------------------------------------------------------------------
# Restore accounts / home / mount
# ---------------------------------------------------------------------------


def test_restore_accounts_rebuild_each_entry_and_fail_closed(monkeypatch):
    monkeypatch.setattr(extensions, "docker_client", FakeDockerClient())
    name = f"pytest_restore_{uuid.uuid4().hex[:10]}"
    cfg = dict(VALID_CFG)
    cfg["name"] = name
    calls: list[tuple[str, str, object, str]] = []

    def _stub_create(owner_name, container_cfg, *, root_password, public_key=None, restore_mount_path=None):
        return CreateContainerReturn("cid-restore", container_cfg.name)

    def _add(container_name, user_name, role, *, password):
        calls.append((container_name, user_name, role, password.get_secret_value()))
        return True

    monkeypatch.setattr(api_module, "container_exists", lambda name: False)
    monkeypatch.setattr(api_module, "create_container", _stub_create)
    monkeypatch.setattr(api_module, "add_collaborator", _add)
    client = TestClient(create_app())
    extensions.status_cache.clear_pending(name)
    payload = {
        "owner_name": "admin",
        "config": cfg,
        "root_password": ROOT_PW,
        "restore_accounts": [
            {"user_name": "alice", "role": "collaborator", "password": COLLAB_PW},
            {"user_name": "bob", "role": "admin", "password": PW},
        ],
    }
    resp = client.post("/api/create_container", json=payload)
    assert resp.status_code == 200
    last = _wait_action(name, ("confirmed", "failed"))
    assert last.get("phase") == "confirmed", last
    assert calls == [
        (name, "alice", ROLE.COLLABORATOR, COLLAB_PW),
        (name, "bob", ROLE.ADMIN, PW),
    ]

    name2 = f"pytest_restore_fail_{uuid.uuid4().hex[:10]}"
    cfg2 = dict(cfg)
    cfg2["name"] = name2
    calls.clear()
    state = {"count": 0}

    def _add_fail(container_name, user_name, role, *, password):
        state["count"] += 1
        calls.append((container_name, user_name, role, password.get_secret_value()))
        return state["count"] != 2

    monkeypatch.setattr(api_module, "add_collaborator", _add_fail)
    extensions.status_cache.clear_pending(name2)
    payload = {
        "owner_name": "admin",
        "config": cfg2,
        "root_password": ROOT_PW,
        "restore_accounts": [
            {"user_name": "alice", "role": "collaborator", "password": COLLAB_PW},
            {"user_name": "bob", "role": "admin", "password": PW},
            {"user_name": "carol", "role": "collaborator", "password": COLLAB_PW},
        ],
    }
    resp = client.post("/api/create_container", json=payload)
    assert resp.status_code == 200
    last = _wait_action(name2, ("confirmed", "failed"))
    assert last.get("phase") == "failed", last
    assert last.get("error_reason") == "create_failed"
    assert calls == [
        (name2, "alice", ROLE.COLLABORATOR, COLLAB_PW),
        (name2, "bob", ROLE.ADMIN, PW),
    ]


def test_restore_account_home_chown_targets_new_account(monkeypatch):
    container = PasswordFakeContainer("c1", user_exists=True)
    client = _install_password_client(monkeypatch, container)
    assert add_collaborator("c1", "alice", ROLE.COLLABORATOR, password=SecretStr(COLLAB_PW)) is True
    text = "\n".join(_commands(container))
    assert "useradd -M -d /root/.collaborators/alice" in text
    assert "chown -R alice:alice /root/.collaborators/alice" in text
    assert "1000" not in text
    assert "chpasswd" not in text
    assert client.api.created[0]["cmd"] == ["chpasswd"]
    assert client.api.started[0]["socket"].sent == f"alice:{COLLAB_PW}\n".encode()


def test_restore_mount_preserves_files_and_reuses_source(monkeypatch, tmp_path):
    base = tmp_path / "home"
    restore = base / "admin" / "containers" / "old_c"
    restore.mkdir(parents=True)
    sentinel = restore / "keep.txt"
    sentinel.write_text("persist", encoding="utf-8")
    monkeypatch.setenv("NODE_CONTAINERS_BASE", str(base))
    monkeypatch.setattr(port_allocator, "_system_bound_ports", lambda: set())
    for key in PROXY_KEYS:
        monkeypatch.delenv(key, raising=False)

    containers = FakeContainers()
    monkeypatch.setattr(extensions, "docker_client", FakeDockerClient(containers))
    cfg = dict(VALID_CFG)
    cfg["name"] = f"pytest_restore_mount_{uuid.uuid4().hex[:8]}"
    result = create_container(
        "admin",
        Container.Config_info(**cfg),
        root_password=SecretStr(ROOT_PW),
        restore_mount_path=str(restore),
    )
    assert result.bind_mount_path is not None
    assert os.path.samefile(result.bind_mount_path, restore)
    assert os.path.samefile(containers.run_calls[0][1]["mounts"][0]["Source"], restore)
    assert sentinel.exists()
    assert sentinel.read_text(encoding="utf-8") == "persist"


# ---------------------------------------------------------------------------
# Add collaborator role groups / admin demotion / ROOT handover
# ---------------------------------------------------------------------------


def test_add_collaborator_role_group_matrix(monkeypatch, capsys, caplog):
    for role in (ROLE.ADMIN, ROLE.COLLABORATOR):
        container = PasswordFakeContainer("c1", user_exists=True)
        client = _install_password_client(monkeypatch, container)
        caplog.clear()
        assert add_collaborator("c1", "u1", role, password=SecretStr(PW)) is True
        commands = "\n".join(_commands(container))
        assert "useradd -M -d /root/.collaborators/u1" in commands
        assert "chown -R u1:u1 /root/.collaborators/u1" in commands
        assert PW not in commands
        assert client.api.created[0]["cmd"] == ["chpasswd"]
        assert client.api.started[0]["socket"].sent == f"u1:{PW}\n".encode()
        if role is ROLE.ADMIN:
            assert "usermod -aG sudo u1 || usermod -aG wheel u1" in commands
        else:
            assert "usermod -aG" not in commands
        output = capsys.readouterr().out + caplog.text
        assert PW not in output
        assert "u1123" not in output


def test_admin_demotion_joins_admin_group_without_touching_root(monkeypatch):
    for user_exists in (False, True):
        container = PasswordFakeContainer("c1", user_exists=user_exists)
        client = _install_password_client(monkeypatch, container)
        assert update_role("c1", "old_root", ROLE.ADMIN, password=SecretStr(PW)) is True
        commands = "\n".join(_commands(container))
        assert "usermod -aG sudo old_root || usermod -aG wheel old_root" in commands
        if user_exists:
            assert "useradd" not in commands
        else:
            assert "useradd -M -d /root/.collaborators/old_root" in commands
        sent = [entry["socket"].sent for entry in client.api.started]
        assert sent == [f"old_root:{PW}\n".encode()]
        assert [item.split(b":", 1)[0] for item in sent] == [b"old_root"]


def test_root_handover_order_and_binding_isolation(monkeypatch):
    container = PasswordFakeContainer("c1", user_exists=False)
    client = _install_password_client(monkeypatch, container)
    assert update_role("c1", "old_root", ROLE.ADMIN, password=SecretStr(PW)) is True
    first_commands = _commands(container)
    first_count = len(first_commands)
    assert update_role("c1", "target", ROLE.ROOT, root_password=SecretStr(ROOT_PW)) is True
    second_commands = _commands(container)[first_count:]
    first_text = "\n".join(first_commands)
    second_text = "\n".join(second_commands)
    assert "old_root" in first_text
    assert "target" not in first_text
    assert "target" in second_text
    assert "old_root" not in second_text
    sent = [entry["socket"].sent for entry in client.api.started]
    assert sent == [f"old_root:{PW}\n".encode(), f"root:{ROOT_PW}\n".encode()]


def test_root_handover_multiple_old_roots_single_target(monkeypatch):
    container = PasswordFakeContainer("c1", user_exists=False)
    client = _install_password_client(monkeypatch, container)
    old_roots = ["old_a", "old_b", "old_c"]
    for user in old_roots:
        assert update_role("c1", user, ROLE.ADMIN, password=SecretStr(PW)) is True
    assert update_role("c1", "target", ROLE.ROOT, root_password=SecretStr(ROOT_PW)) is True
    commands = _commands(container)
    all_text = "\n".join(commands)
    for user in old_roots:
        assert f"useradd -M -d /root/.collaborators/{user}" in all_text
    assert "target" in all_text
    sent = [entry["socket"].sent for entry in client.api.started]
    assert sent == [
        *(f"{user}:{PW}\n".encode() for user in old_roots),
        f"root:{ROOT_PW}\n".encode(),
    ]
    assert len(client.api.created) == 4


# ---------------------------------------------------------------------------
# ROOT cleanup with recording command doubles
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not Path("/bin/sh").exists(), reason="requires POSIX /bin/sh")
def test_root_cleanup_records_only_with_all_state_command_doubles(monkeypatch, tmp_path):
    container = PasswordFakeContainer("c1", user_exists=True)
    _install_password_client(monkeypatch, container)
    assert update_role("c1", "target", ROLE.ROOT, root_password=SecretStr(ROOT_PW)) is True
    cleanup = next(
        command
        for command in _commands(container)
        if "for g in sudo wheel" in command
    )

    stub_dir = tmp_path / "stub-bin"
    stub_dir.mkdir()
    call_log = tmp_path / "calls.log"
    sentinel = tmp_path / "sentinel"
    sentinel.write_text("unchanged", encoding="utf-8")

    scripts = {
        "id": '#!/bin/sh\nprintf "id %s\\n" "$*" >> "$CALL_LOG"\nprintf "target\\n"\n',
        "deluser": '#!/bin/sh\nprintf "deluser %s\\n" "$*" >> "$CALL_LOG"\nexit 0\n',
        "mv": '#!/bin/sh\nprintf "mv %s\\n" "$*" >> "$CALL_LOG"\nexit 0\n',
        "userdel": '#!/bin/sh\nprintf "userdel %s\\n" "$*" >> "$CALL_LOG"\nexit 0\n',
        "rm": '#!/bin/sh\nprintf "rm %s\\n" "$*" >> "$CALL_LOG"\nexit 0\n',
        "date": '#!/bin/sh\nprintf "20261028T120000\\n"\n',
    }
    for name, body in scripts.items():
        path = stub_dir / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = f"{stub_dir}:/usr/bin:/bin"
    env["CALL_LOG"] = str(call_log)
    completed = subprocess.run(
        ["/bin/sh", "-c", cleanup],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    lines = call_log.read_text(encoding="utf-8").splitlines()
    assert any(line.startswith("id -nG target") for line in lines), lines
    assert any("mv /root/.collaborators/target /root/.collaborators/.legacy_target_20261028T120000" in line for line in lines), lines
    assert any(line == "userdel target" for line in lines), lines
    assert any(line == "rm -f /home/target" for line in lines), lines
    assert not any(line.startswith("deluser ") for line in lines), lines
    assert sentinel.read_text(encoding="utf-8") == "unchanged"


# ---------------------------------------------------------------------------
# Reset password service / API / ASGI disconnect
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("user_name", ["u1", "root"])
def test_reset_password_service_binds_user_and_root_stdin(monkeypatch, user_name):
    container = PasswordFakeContainer("c1", status="running")
    client = _install_password_client(monkeypatch, container)
    assert reset_container_password("c1", user_name, SecretStr(PW)) is True
    assert client.api.created[0]["cmd"] == ["chpasswd"]
    assert client.api.created[0]["kwargs"]["stdin"] is True
    assert client.api.created[0]["kwargs"]["tty"] is False
    assert client.api.created[0]["kwargs"]["user"] == "root"
    assert client.api.started[0]["socket"].sent == f"{user_name}:{PW}\n".encode()
    assert PW not in repr(client.api.created)


def test_reset_password_no_persistence_and_no_retry(monkeypatch):
    real_open = builtins.open

    def _guarded_open(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            raise AssertionError(f"unexpected write: {file!r} mode={mode!r}")
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", _guarded_open)
    container = PasswordFakeContainer("c1", status="running")
    client = _install_password_client(monkeypatch, container)
    assert reset_container_password("c1", "u1", SecretStr(PW)) is True
    assert len(client.api.created) == 1
    assert len(client.api.started) == 1
    assert len(client.api.inspected) == 1

    failing = PasswordFakeContainer("c1", status="running")
    failing_client = _install_password_client(monkeypatch, failing, exit_code=1)
    with pytest.raises(RuntimeError):
        reset_container_password("c1", "u1", SecretStr(PW))
    assert len(failing_client.api.created) == 1
    assert len(failing_client.api.started) == 1
    assert len(failing_client.api.inspected) == 1


def test_reset_password_missing_or_stopped_container_no_exec(monkeypatch):
    missing_client = PasswordFakeDockerClient(FakeContainers([]))
    monkeypatch.setattr(extensions, "docker_client", missing_client)
    with pytest.raises(docker.errors.NotFound):
        reset_container_password("ghost", "u1", SecretStr(PW))
    assert missing_client.api.created == []

    stopped = PasswordFakeContainer("c1", status="exited")
    stopped_client = _install_password_client(monkeypatch, stopped)
    with pytest.raises(ContainerNotRunning):
        reset_container_password("c1", "u1", SecretStr(PW))
    assert stopped_client.api.created == []


def test_reset_password_invalid_inputs_http_422(monkeypatch, capsys, caplog):
    container = PasswordFakeContainer("c1", status="running")
    client, docker_client = _client(monkeypatch, container)
    cases = [
        ("password", ""),
        ("password", "short"),
        ("password", "x" * 129),
        ("password", "        "),
        ("password", "abc:defgh"),
        ("password", "abc\rdefgh"),
        ("password", "abc\ndefgh"),
        ("password", "abc\x00defgh"),
        ("user_name", "bad;name"),
        ("container_name", "bad;name"),
    ]
    for field, value in cases:
        payload = _payload_reset()
        payload["config"][field] = value
        resp = client.post("/api/reset_container_password", json=payload)
        _assert_redacted(resp, value if field == "password" else "")
    assert container.exec_calls == []
    assert docker_client.api.created == []
    text = capsys.readouterr().out + caplog.text
    assert PW not in text


class _BlockingExecAPI(FakeExecAPI):
    def __init__(self):
        super().__init__()
        self.start_entered = threading.Event()
        self.release = threading.Event()

    def exec_start(self, exec_id, **kwargs):
        self.start_entered.set()
        if not self.release.wait(5):
            raise RuntimeError("blocking exec was not released")
        return super().exec_start(exec_id, **kwargs)


def test_reset_password_http_disconnect_does_not_cancel_chpasswd(monkeypatch):
    container = PasswordFakeContainer("c1", status="running")
    docker_client = PasswordFakeDockerClient(FakeContainers([container]))
    api = _BlockingExecAPI()
    docker_client.api = api
    monkeypatch.setattr(extensions, "docker_client", docker_client)

    app = create_app()
    body = json.dumps(_payload_reset()).encode("utf-8")
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/reset_container_password",
        "raw_path": b"/api/reset_container_password",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode("ascii")),
        ],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }
    receive_calls = 0
    disconnect_available = False

    async def receive():
        nonlocal receive_calls, disconnect_available
        receive_calls += 1
        if receive_calls == 1:
            return {"type": "http.request", "body": body, "more_body": False}
        disconnect_available = True
        return {"type": "http.disconnect"}

    messages: list[dict[str, Any]] = []

    async def send(message):
        messages.append(message)

    async def run() -> None:
        task = asyncio.create_task(app(scope, receive, send))
        try:
            entered = await asyncio.to_thread(api.start_entered.wait, 3)
            assert entered, "service did not enter chpasswd"
            # The ASGI server side delivers http.disconnect while the sync
            # chpasswd work is still blocked; this is not task cancellation.
            disconnected = await receive()
            assert disconnected["type"] == "http.disconnect"
            api.release.set()
            await asyncio.wait_for(task, 5)
        finally:
            api.release.set()
            if not task.done():
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task

    asyncio.run(run())
    assert len(docker_client.api.created) == 1
    assert len(docker_client.api.started) == 1
    assert docker_client.api.started[0]["socket"].sent == f"u1:{PW}\n".encode()
    assert len(docker_client.api.inspected) == 1
    assert receive_calls >= 2, receive_calls
    assert disconnect_available is True
    assert any(message.get("type") == "http.response.start" for message in messages)


# ---------------------------------------------------------------------------
# Procedure: commit-msg / pre-commit / PR checker
# ---------------------------------------------------------------------------


def _run_hook(script: Path, cwd: Path, msg_file: Path) -> subprocess.CompletedProcess:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is required for hook tests")
    return subprocess.run(
        [bash, str(script), str(msg_file)],
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=10,
    )


@pytest.mark.parametrize("keyword", ["NEW", "AMEND", "FIX", "SPEC", "TEST"])
def test_commit_msg_hook_entry_grammar(tmp_path, keyword):
    hook = REPO_ROOT / "githooks" / "commit-msg"
    valid = tmp_path / "valid.msg"
    valid.write_text(f"- {keyword} 提交分类说明\n", encoding="utf-8")
    completed = _run_hook(hook, REPO_ROOT, valid)
    assert completed.returncode == 0, completed.stderr
    valid.write_text(
        "- NEW 增加账号映射测试\n"
        "- AMEND 调整密码矩阵\n"
        "# git 注释\n"
        "- FIX 修复脱敏断言\n",
        encoding="utf-8",
    )
    completed = _run_hook(hook, REPO_ROOT, valid)
    assert completed.returncode == 0, completed.stderr

    invalid = tmp_path / "invalid.msg"
    for message in (
        "- DOCS 自造关键字\n",
        "- DEBUG 自造关键字\n",
        "-NEW 缺少空格\n",
        "- spec 关键字必须大写\n",
        "- TEST\n",
    ):
        invalid.write_text(message, encoding="utf-8")
        completed = _run_hook(hook, REPO_ROOT, invalid)
        assert completed.returncode != 0, message
        assert "NEW" in completed.stderr
        assert "连字符" in completed.stderr

    empty = tmp_path / "empty.msg"
    empty.write_text("\n# only a comment\n\n", encoding="utf-8")
    completed = _run_hook(hook, REPO_ROOT, empty)
    assert completed.returncode != 0
    assert "至少需要一条实际变更" in completed.stderr


def test_commit_msg_hook_attribution_and_last_line(tmp_path):
    hook = REPO_ROOT / "githooks" / "commit-msg"
    for text in (
        "- NEW 增加测试\nCo-Authored-By: tool <tool@example.com>\n",
        "- NEW 增加测试\nGenerated with tool\n",
        "- NEW 增加测试\n🤖\n",
    ):
        path = tmp_path / "attribution.msg"
        path.write_text(text, encoding="utf-8")
        completed = _run_hook(hook, REPO_ROOT, path)
        assert completed.returncode != 0
        assert "署名" in completed.stderr or "生成" in completed.stderr

    no_newline = tmp_path / "no-newline.msg"
    no_newline.write_text("- DOCS 末行非法", encoding="utf-8")
    completed = _run_hook(hook, REPO_ROOT, no_newline)
    assert completed.returncode != 0

    crlf = tmp_path / "crlf.msg"
    crlf.write_bytes("- NEW 增加测试\r\n- FIX 修复问题\r\n".encode("utf-8"))
    completed = _run_hook(hook, REPO_ROOT, crlf)
    assert completed.returncode == 0, completed.stderr


def test_commit_msg_hook_merge_exemption_uses_git_state(tmp_path):
    hook = REPO_ROOT / "githooks" / "commit-msg"
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is required")
    subprocess.run([git, "init", "-q", str(tmp_path)], check=True, capture_output=True)
    msg = tmp_path / "merge.msg"
    msg.write_text("Merge branch 'feature'\n", encoding="utf-8")
    (tmp_path / ".git" / "MERGE_HEAD").write_text("0" * 40 + "\n", encoding="utf-8")
    completed = _run_hook(hook, tmp_path, msg)
    assert completed.returncode == 0, completed.stderr

    (tmp_path / ".git" / "MERGE_HEAD").unlink()
    completed = _run_hook(hook, tmp_path, msg)
    assert completed.returncode != 0
    assert "至少需要一条实际变更" in completed.stderr or "不符合条目格式" in completed.stderr


def test_pre_commit_capability_prefix_matrix(tmp_path):
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is required")
    clone = tmp_path / "clone"
    subprocess.run(
        [git, "clone", "--quiet", "--no-hardlinks", str(REPO_ROOT), str(clone)],
        check=True,
        capture_output=True,
        timeout=60,
    )
    hook = clone / "githooks" / "pre-commit"
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is required")

    def _reset():
        subprocess.run([git, "reset", "--hard", "-q", "HEAD"], cwd=clone, check=True, capture_output=True)
        subprocess.run([git, "clean", "-fdq"], cwd=clone, check=True, capture_output=True)

    def _run_hook():
        return subprocess.run(
            [bash, str(hook)],
            cwd=clone,
            text=True,
            capture_output=True,
            timeout=10,
        )

    def _add(rel: str, text: str) -> Path:
        path = clone / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        subprocess.run([git, "add", rel], cwd=clone, check=True, capture_output=True)
        return path

    _reset()
    _add("openspec/changes/tmp/specs/frontend--page-example/spec.md", "# page\n")
    completed = _run_hook()
    assert completed.returncode == 0, completed.stderr

    _reset()
    _add("openspec/changes/tmp/specs/frontend--backend--example/spec.md", "# page\n")
    completed = _run_hook()
    assert completed.returncode != 0
    assert "叠加" in completed.stderr or "一个门类" in completed.stderr

    _reset()
    _add("openspec/changes/tmp/specs/example/spec.md", "# page\n")
    completed = _run_hook()
    assert completed.returncode != 0
    assert "缺少门类前缀" in completed.stderr

    _reset()
    existing = clone / "openspec" / "specs" / "backend--collaborator-accounts" / "spec.md"
    existing.write_text(existing.read_text(encoding="utf-8") + "\n<!-- touched -->\n", encoding="utf-8")
    subprocess.run(
        [git, "add", "openspec/specs/backend--collaborator-accounts/spec.md"],
        cwd=clone,
        check=True,
        capture_output=True,
    )
    completed = _run_hook()
    assert completed.returncode == 0, completed.stderr

    _reset()
    _add(
        "openspec/changes/tmp/specs/backend--collaborator-accounts/spec.md",
        "# delta\n",
    )
    completed = _run_hook()
    assert completed.returncode == 0, completed.stderr


def _load_check_pr():
    path = REPO_ROOT / "scripts" / "ci" / "check_pr.py"
    spec = importlib.util.spec_from_file_location("check_pr_for_anvil", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pr_title_is_ignored_by_checker(tmp_path, capsys):
    check_pr = _load_check_pr()
    body = "### 新增内容 | WHAT'S NEW\n- 新增账号测试\n"
    event = tmp_path / "event.json"
    event.write_text(
        json.dumps(
            {
                "pull_request": {
                    "title": "feat: 不应被校验的标题 __import__('os').system('echo pwned')",
                    "body": body,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    code = check_pr.main(["--event", str(event)])
    captured = capsys.readouterr()
    assert code == 0
    assert "feat:" not in captured.out
    assert "__import__" not in captured.out


def test_pr_body_canary_command_does_not_execute(tmp_path, capsys):
    check_pr = _load_check_pr()
    marker = tmp_path / "canary_marker"
    command = f"python -c \"open(r'{marker}', 'w').write('x')\""
    body = f"### 新增内容 | WHAT'S NEW\n- 修复 `{command}` 的展示转义\n"
    event = tmp_path / "event.json"
    event.write_text(
        json.dumps({"pull_request": {"title": "自然标题", "body": body}}, ensure_ascii=False),
        encoding="utf-8",
    )
    code = check_pr.main(["--event", str(event)])
    assert code == 0
    assert not marker.exists()
    assert marker.as_posix() not in capsys.readouterr().out

    fenced = f"```bash\n{command}\n```\n"
    event.write_text(
        json.dumps({"pull_request": {"title": "自然标题", "body": fenced}}, ensure_ascii=False),
        encoding="utf-8",
    )
    code = check_pr.main(["--event", str(event)])
    assert code == 1
    assert not marker.exists()
