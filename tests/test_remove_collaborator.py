"""remove_collaborator 服务层测试。

- 错误路径（默认集）：FakeDockerClient
- happy path（-m docker）：真实 docker daemon
"""
import uuid

import pytest

from FuxiYu_NodeKernel.services.container_service import remove_collaborator
from FuxiYu_NodeKernel import extensions

from .conftest import FakeContainer, FakeContainers, FakeDockerClient


def test_error_path_invalid_config(monkeypatch):
    """非法用户名 → sanitizer 拒绝 → False。"""
    c = FakeContainer("c1")
    monkeypatch.setattr(extensions, "docker_client", FakeDockerClient(FakeContainers([c])))
    assert remove_collaborator("c1", "bad;name") is False


def test_error_path_container_not_exist(monkeypatch):
    monkeypatch.setattr(extensions, "docker_client", FakeDockerClient())
    assert remove_collaborator("ghost", "u1") is False


def test_error_path_collaborator_not_exist(monkeypatch):
    """容器内 userdel 失败（exec 退出码非 0）→ False。"""
    c = FakeContainer("c1", exec_exit_code=1)
    monkeypatch.setattr(extensions, "docker_client", FakeDockerClient(FakeContainers([c])))
    assert remove_collaborator("c1", "u1") is False


def test_error_path_collaborator_are_root(monkeypatch):
    """服务层目前不阻止删除 root —— 记录现状行为：命令照常执行并成功。

    TODO(WSS 重构期)：若设计上应禁止删除 root，需在服务层加守卫并改此断言。
    """
    c = FakeContainer("c1", exec_exit_code=0)
    monkeypatch.setattr(extensions, "docker_client", FakeDockerClient(FakeContainers([c])))
    assert remove_collaborator("c1", "root") is True


@pytest.mark.docker
def test_happy_path():
    """真实 docker：建容器 → 加用户再删除 → 验证用户不存在 → 清理。"""
    from FuxiYu_NodeKernel.services.container_service import add_collaborator
    from FuxiYu_NodeKernel.constant import ROLE

    if extensions.docker_client is None:
        extensions.init_docker()
    client = extensions.docker_client

    c = client.containers.run(
        "ubuntu:22.04",
        "tail -f /dev/null",
        detach=True,
        tty=True,
        name=f"pytest_rmc_{uuid.uuid4().hex[:8]}",
    )
    user = f"u{uuid.uuid4().hex[:8]}"

    try:
        assert add_collaborator(c.id, user, ROLE.COLLABORATOR) is True
        assert remove_collaborator(c.id, user) is True
        r = c.exec_run(["/bin/sh", "-c", f"id -u {user}"], user="root")
        assert r.exit_code != 0, "用户应已被删除"
    finally:
        try:
            c.remove(force=True)
        except Exception:
            pass
