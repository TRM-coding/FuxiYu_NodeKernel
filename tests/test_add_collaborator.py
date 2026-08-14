"""add_collaborator 服务层测试。

- 错误路径（默认集）：FakeDockerClient
- happy path（-m docker）：真实 docker daemon
"""
import uuid

import pytest

from FuxiYu_NodeKernel.services.container_service import add_collaborator
from FuxiYu_NodeKernel.constant import ROLE
from FuxiYu_NodeKernel import extensions

from .conftest import FakeContainer, FakeContainers, FakeDockerClient


def test_error_path_invalid_config(monkeypatch):
    """非法用户名 → sanitizer 拒绝 → False。"""
    c = FakeContainer("c1")
    monkeypatch.setattr(extensions, "docker_client", FakeDockerClient(FakeContainers([c])))
    assert add_collaborator("c1", "bad;name", ROLE.ADMIN) is False


def test_error_path_container_not_exist(monkeypatch):
    monkeypatch.setattr(extensions, "docker_client", FakeDockerClient())
    assert add_collaborator("ghost", "u1", ROLE.COLLABORATOR) is False


def test_error_path_collaborator_not_exist(monkeypatch):
    """容器内 useradd 失败（exec 退出码非 0）→ False。"""
    c = FakeContainer("c1", exec_exit_code=1)
    monkeypatch.setattr(extensions, "docker_client", FakeDockerClient(FakeContainers([c])))
    assert add_collaborator("c1", "u1", ROLE.ADMIN) is False


@pytest.mark.docker
def test_happy_path():
    """真实 docker：建容器 → 加用户 → 验证用户存在 → 清理。"""
    if extensions.docker_client is None:
        extensions.init_docker()
    client = extensions.docker_client

    c = client.containers.run(
        "ubuntu:22.04",
        "tail -f /dev/null",
        detach=True,
        tty=True,
        name=f"pytest_add_{uuid.uuid4().hex[:8]}",
    )
    user = f"u{uuid.uuid4().hex[:8]}"
    role = ROLE.COLLABORATOR

    try:
        ok = add_collaborator(c.id, user, role)
        assert ok is True, "add_collaborator 返回 False"

        r = c.exec_run(["/bin/sh", "-c", f"id -u {user}"], user="root")
        assert r.exit_code == 0, f"用户未创建成功: {r.output!r}"

        if role == ROLE.ADMIN:
            r = c.exec_run(["/bin/sh", "-c", f"id -nG {user} | grep -w sudo"], user="root")
            assert r.exit_code == 0, f"用户未加入 sudo 组: {r.output!r}"
    finally:
        try:
            c.remove(force=True)
        except Exception:
            pass
