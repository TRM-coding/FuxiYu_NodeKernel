from __future__ import annotations

import json

import pytest
from pydantic import SecretStr

from FuxiYu_NodeKernel import extensions
from FuxiYu_NodeKernel.constant import ROLE
from FuxiYu_NodeKernel.docker_operates import port_allocator
from FuxiYu_NodeKernel.services.container_service import (
    add_collaborator,
    create_container,
    reset_container_password,
    update_role,
)
from FuxiYu_NodeKernel.utils.Container import Container

from .conftest import FakeContainers, FakeDockerClient, FakeImages
from .password_fakes import PasswordFakeContainer, PasswordFakeDockerClient, install_password_docker

PW = SecretStr("Role#Password9")
ROOT_PW = SecretStr("Root#Password9")
VALID_CFG = {
    "gpu_list": [],
    "cpu_number": 2,
    "memory": 4,
    "shared_memory": 0,
    "name": "pytest_pw_c",
    "port": 2233,
    "image": "ubuntu:22.04",
}


def _client(container, *, exit_code=0):
    return PasswordFakeDockerClient(FakeContainers([container]), exit_code=exit_code)


def test_add_collaborator_uses_password(monkeypatch, capsys):
    for role in (ROLE.ADMIN, ROLE.COLLABORATOR):
        c = PasswordFakeContainer("c1", user_exists=True)
        client = _client(c)
        monkeypatch.setattr(extensions, "docker_client", client)
        assert add_collaborator("c1", "u1", role, password=PW) is True
        commands = "\n".join(call[0][2] for call in c.exec_calls)
        assert "useradd -M -d /root/.collaborators/u1" in commands
        assert "chpasswd" not in commands
        assert "u1:u1123" not in commands
        assert client.api.started[0]["socket"].sent == b"u1:Role#Password9\n"

    c = PasswordFakeContainer("c1", user_exists=True)
    install_password_docker(monkeypatch, c, exit_code=1)
    assert add_collaborator("c1", "u1", ROLE.ADMIN, password=PW) is False
    out = capsys.readouterr().out
    assert PW.get_secret_value() not in out


def test_admin_demotion_creates_or_updates_account(monkeypatch):
    c = PasswordFakeContainer("c1", user_exists=False)
    client = _client(c)
    monkeypatch.setattr(extensions, "docker_client", client)
    assert update_role("c1", "old_root", ROLE.ADMIN, password=PW) is True
    commands = [call[0][2] for call in c.exec_calls]
    assert any("useradd -M -d /root/.collaborators/old_root" in cmd for cmd in commands)
    assert client.api.started[0]["socket"].sent == b"old_root:Role#Password9\n"

    c = PasswordFakeContainer("c1", user_exists=True)
    client = _client(c)
    monkeypatch.setattr(extensions, "docker_client", client)
    assert update_role("c1", "old_root", ROLE.ADMIN, password=PW) is True
    assert not any("useradd" in call[0][2] for call in c.exec_calls)
    assert client.api.started[0]["socket"].sent == b"old_root:Role#Password9\n"

    c = PasswordFakeContainer("c1", user_exists=True)
    client = _client(c)
    monkeypatch.setattr(extensions, "docker_client", client)
    assert update_role("c1", "u1", ROLE.ADMIN) is True
    assert client.api.created == []
    assert any("usermod -aG sudo u1" in call[0][2] for call in c.exec_calls)

    c = PasswordFakeContainer("c1", user_exists=False)
    client = _client(c)
    monkeypatch.setattr(extensions, "docker_client", client)
    assert update_role("c1", "u1", ROLE.ADMIN) is False
    assert client.api.created == []


def test_root_transfer_single_target(monkeypatch):
    c = PasswordFakeContainer("c1", user_exists=True)
    client = _client(c)
    monkeypatch.setattr(extensions, "docker_client", client)
    assert update_role("c1", "target", ROLE.ROOT, root_password=ROOT_PW) is True
    assert client.api.started[0]["socket"].sent == b"root:Root#Password9\n"
    commands = "\n".join(call[0][2] for call in c.exec_calls)
    assert "target" in commands
    assert "old_root" not in commands
    assert "root:target123" not in commands

    with pytest.raises(ValueError):
        update_role("c1", "target", ROLE.ROOT)


def test_root_handover_orchestration(monkeypatch):
    c = PasswordFakeContainer("c1", user_exists=False)
    client = _client(c)
    monkeypatch.setattr(extensions, "docker_client", client)
    assert update_role("c1", "old_root", ROLE.ADMIN, password=PW) is True
    assert update_role("c1", "target", ROLE.ROOT, root_password=ROOT_PW) is True
    sent = [started["socket"].sent for started in client.api.started]
    assert b"old_root:Role#Password9\n" in sent
    assert b"root:Root#Password9\n" in sent
    commands = "\n".join(call[0][2] for call in c.exec_calls)
    assert "old_root" in commands and "target" in commands

    # Second call failure does not execute a rollback command for the first call.
    c = PasswordFakeContainer("c1", user_exists=True)
    client = _client(c, exit_code=1)
    monkeypatch.setattr(extensions, "docker_client", client)
    with pytest.raises(RuntimeError):
        update_role("c1", "target", ROLE.ROOT, root_password=ROOT_PW)
    commands = "\n".join(call[0][2] for call in c.exec_calls)
    assert "useradd -M -d /root/.collaborators/old_root" not in commands


def test_root_group_cleanup_idempotent(monkeypatch):
    c = PasswordFakeContainer("c1", user_exists=True)
    client = _client(c)
    monkeypatch.setattr(extensions, "docker_client", client)
    assert update_role("c1", "u1", ROLE.ROOT, root_password=ROOT_PW) is True
    cmd = next(call[0][2] for call in c.exec_calls if "for g in sudo wheel" in call[0][2])
    assert 'deluser u1 "$g"' in cmd
    assert "grep -qx" in cmd
    assert "rc=1" not in cmd


def test_plain_role_switch_no_password(monkeypatch):
    c = PasswordFakeContainer("c1", user_exists=True)
    client = _client(c)
    monkeypatch.setattr(extensions, "docker_client", client)
    assert update_role("c1", "u1", ROLE.COLLABORATOR) is True
    assert client.api.created == []
    assert update_role("c1", "u1", ROLE.ADMIN) is True
    assert client.api.created == []


def test_create_uses_root_password_and_no_fallback(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("NODE_CONTAINERS_BASE", str(tmp_path / "home"))
    monkeypatch.setattr(port_allocator, "_system_bound_ports", lambda: set())
    for key in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "no_proxy", "NO_PROXY"):
        monkeypatch.delenv(key, raising=False)
    containers = FakeContainers()
    client = PasswordFakeDockerClient(containers, FakeImages())
    monkeypatch.setattr(extensions, "docker_client", client)

    result = create_container("admin", Container.Config_info(**VALID_CFG), root_password=ROOT_PW)
    assert result.container_name == VALID_CFG["name"]
    assert client.api.started[0]["socket"].sent == b"root:Root#Password9\n"
    out = capsys.readouterr().out
    assert "owner123" not in out
    assert ROOT_PW.get_secret_value() not in out

    client = PasswordFakeDockerClient(FakeContainers(), FakeImages(), exit_code=1)
    monkeypatch.setattr(extensions, "docker_client", client)
    with pytest.raises(RuntimeError) as excinfo:
        create_container("admin", Container.Config_info(**VALID_CFG), root_password=ROOT_PW)
    assert ROOT_PW.get_secret_value() not in str(excinfo.value)
    assert "owner123" not in str(excinfo.value)


def test_create_password_not_in_docker_config(monkeypatch, tmp_path):
    monkeypatch.setenv("NODE_CONTAINERS_BASE", str(tmp_path / "home"))
    monkeypatch.setattr(port_allocator, "_system_bound_ports", lambda: set())
    for key in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "no_proxy", "NO_PROXY"):
        monkeypatch.delenv(key, raising=False)
    containers = FakeContainers()
    client = PasswordFakeDockerClient(containers, FakeImages())
    monkeypatch.setattr(extensions, "docker_client", client)
    create_container("admin", Container.Config_info(**VALID_CFG), root_password=ROOT_PW)
    _, kwargs = containers.run_calls[0]
    dumped = json.dumps({"args": list(containers.run_calls[0][0]), "kwargs": kwargs}, default=str)
    assert ROOT_PW.get_secret_value() not in dumped
    assert "environment" not in kwargs or ROOT_PW.get_secret_value() not in json.dumps(kwargs["environment"])


def test_logs_and_exceptions_no_secret(monkeypatch, capsys, caplog):
    c = PasswordFakeContainer("c1", user_exists=True)
    client = _client(c, exit_code=1)
    monkeypatch.setattr(extensions, "docker_client", client)
    with pytest.raises(RuntimeError):
        update_role("c1", "u1", ROLE.ROOT, root_password=ROOT_PW)
    out = capsys.readouterr().out + caplog.text
    assert ROOT_PW.get_secret_value() not in out


def test_add_collaborator_logs_no_secret(monkeypatch, capsys, caplog):
    c = PasswordFakeContainer("c1", user_exists=True)
    client = _client(c)
    monkeypatch.setattr(extensions, "docker_client", client)
    add_collaborator("c1", "u1", ROLE.ADMIN, password=PW)
    out = capsys.readouterr().out + caplog.text
    assert PW.get_secret_value() not in out
    assert "u1:u1123" not in out


def test_update_role_logs_no_secret(monkeypatch, capsys, caplog):
    c = PasswordFakeContainer("c1", user_exists=False)
    client = _client(c)
    monkeypatch.setattr(extensions, "docker_client", client)
    update_role("c1", "old_root", ROLE.ADMIN, password=PW)
    update_role("c1", "target", ROLE.ROOT, root_password=ROOT_PW)
    out = capsys.readouterr().out + caplog.text
    assert PW.get_secret_value() not in out
    assert ROOT_PW.get_secret_value() not in out
