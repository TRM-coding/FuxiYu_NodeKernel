"""update_role 服务层测试。

- 错误路径（默认集）：FakeDockerClient
- happy path（-m docker）：真实 docker daemon
"""
import uuid

import pytest
import docker as docker_pkg

from FuxiYu_NodeKernel import extensions
from FuxiYu_NodeKernel.services.container_service import update_role
from FuxiYu_NodeKernel.constant import ROLE

from .conftest import FakeContainer, FakeContainers, FakeDockerClient


def test_error_path_invalid_config(monkeypatch):
    """未知角色 → ValueError 上抛。"""
    c = FakeContainer("c1")
    monkeypatch.setattr(extensions, "docker_client", FakeDockerClient(FakeContainers([c])))
    with pytest.raises(ValueError, match="Unknown role"):
        update_role("c1", "u1", "emperor")


def test_error_path_container_not_exist(monkeypatch):
    """容器不存在 → NotFound 原样上抛（服务层不吞）。"""
    monkeypatch.setattr(extensions, "docker_client", FakeDockerClient())
    with pytest.raises(docker_pkg.errors.NotFound):
        update_role("ghost", "u1", ROLE.ADMIN)


def test_error_path_collaborator_not_exist(monkeypatch):
    """容器内命令失败（exec 退出码非 0）→ False。"""
    c = FakeContainer("c1", exec_exit_code=1)
    monkeypatch.setattr(extensions, "docker_client", FakeDockerClient(FakeContainers([c])))
    assert update_role("c1", "u1", ROLE.ADMIN) is False


def test_error_path_the_same_role(monkeypatch):
    """服务层不检查当前角色，重复设置同样角色照常执行命令；结果取决于命令退出码。"""
    c = FakeContainer("c1", exec_exit_code=0)
    monkeypatch.setattr(extensions, "docker_client", FakeDockerClient(FakeContainers([c])))
    assert update_role("c1", "u1", ROLE.ADMIN) is True


def test_demote_removes_from_both_admin_groups(monkeypatch):
    """降级 COLLABORATOR 回归：旧 `deluser u sudo || deluser u wheel` 在用户同属
    sudo+wheel 时短路只摘第一组，残留另一组管理员权限。命令必须分号串行摘两个组；
    至少摘掉一组 → rc=0 成功，两组都不在 → 仍失败（沿用旧语义）。"""
    c = FakeContainer("c1", exec_exit_code=0)
    monkeypatch.setattr(extensions, "docker_client", FakeDockerClient(FakeContainers([c])))
    assert update_role("c1", "u1", ROLE.COLLABORATOR) is True
    assert c.exec_calls, "预期执行过容器命令"
    cmd = c.exec_calls[0][0][2]
    assert "deluser u1 sudo && rc=0" in cmd
    assert "deluser u1 wheel && rc=0" in cmd
    assert "exit $rc" in cmd
    assert "|| deluser u1 wheel" not in cmd  # 旧短路结构不得复活


def test_root_branch_clears_both_admin_groups(monkeypatch):
    """ROOT 分支（接管前清特权组）与降级分支同构：两个组都要摘，不能短路只摘一个。"""
    c = FakeContainer("c1", exec_exit_code=0)
    monkeypatch.setattr(extensions, "docker_client", FakeDockerClient(FakeContainers([c])))
    assert update_role("c1", "u1", ROLE.ROOT) is True
    assert c.exec_calls, "预期执行过容器命令"
    cmd = c.exec_calls[0][0][2]
    assert "rc=1; deluser u1 sudo && rc=0; deluser u1 wheel && rc=0; exit $rc" in cmd


def test_error_path_role_are_root(monkeypatch):
    """ROOT 角色路径：改 root 密码 + 清 sudo 组 + 删用户，命令成功 → True。"""
    c = FakeContainer("c1", exec_exit_code=0)
    monkeypatch.setattr(extensions, "docker_client", FakeDockerClient(FakeContainers([c])))
    assert update_role("c1", "u1", ROLE.ROOT) is True


def test_admin_ensure_user_home_in_collaborators(monkeypatch):
    """ADMIN 分支确保账号存在时，家目录必须建在 /root/.collaborators（持久化挂载），
    而非 useradd -m 默认的 /home（overlay2 可写层）。回归测试。"""
    c = FakeContainer("c1", exec_exit_code=0)
    monkeypatch.setattr(extensions, "docker_client", FakeDockerClient(FakeContainers([c])))
    assert update_role("c1", "u1", ROLE.ADMIN) is True
    assert c.exec_calls, "预期执行过容器命令"
    cmd = c.exec_calls[0][0][2]  # exec_run(["/bin/sh", "-c", cmd], user="root")
    assert "useradd -M -d /root/.collaborators/u1" in cmd
    assert "useradd -m" not in cmd
    assert "ln -s /root/.collaborators/u1 /home/u1" in cmd


@pytest.mark.docker
def test_happy_path():
    """真实 docker：建容器 → 升 ADMIN（入 sudo 组）→ 降 COLLABORATOR（出 sudo 组）→ 清理。"""
    if extensions.docker_client is None:
        extensions.init_docker()
    client = extensions.docker_client

    c = client.containers.run(
        "ubuntu:22.04",
        "tail -f /dev/null",
        detach=True,
        tty=True,
        name=f"pytest_role_{uuid.uuid4().hex[:8]}",
    )
    user = f"u{uuid.uuid4().hex[:8]}"

    try:
        r = c.exec_run(
            ["/bin/sh", "-c", "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y sudo"],
            user="root",
        )
        assert r.exit_code == 0, f"安装 sudo 失败: {r.output!r}"

        r = c.exec_run(["/bin/sh", "-c", f"useradd -m -s /bin/bash {user}"], user="root")
        assert r.exit_code == 0, f"创建用户失败: {r.output!r}"

        ok = update_role(c.id, user, ROLE.ADMIN)
        assert ok is True, "update_role(ADMIN) 返回 False"
        r = c.exec_run(["/bin/sh", "-c", f"id -nG {user} | tr ' ' '\\n' | grep -x sudo"], user="root")
        assert r.exit_code == 0, f"用户未加入 sudo 组: {r.output!r}"

        ok = update_role(c.id, user, ROLE.COLLABORATOR)
        assert ok is True, "update_role(COLLABORATOR) 返回 False"
        r = c.exec_run(["/bin/sh", "-c", f"id -nG {user} | tr ' ' '\\n' | grep -x sudo"], user="root")
        assert r.exit_code != 0, "用户仍在 sudo 组（预期已移除）"
    finally:
        try:
            c.remove(force=True)
        except Exception:
            pass
