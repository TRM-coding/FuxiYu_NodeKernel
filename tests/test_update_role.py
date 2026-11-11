"""update_role 服务层测试。

- 错误路径（默认集）：FakeDockerClient
- happy path（-m docker）：真实 docker daemon
"""
import uuid

import pytest
import docker as docker_pkg
from pydantic import SecretStr

from FuxiYu_NodeKernel import extensions
from FuxiYu_NodeKernel.services.container_service import update_role
from FuxiYu_NodeKernel.constant import ROLE

from .conftest import FakeContainers, FakeDockerClient
from .password_fakes import PasswordFakeContainer

PW = SecretStr("Role#Password9")
ROOT_PW = SecretStr("Root#Password9")


def test_error_path_invalid_config(monkeypatch):
    """未知角色 → ValueError 上抛。"""
    c = PasswordFakeContainer("c1")
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
    c = PasswordFakeContainer("c1", user_exists=True, exec_exit_code=1)
    monkeypatch.setattr(extensions, "docker_client", FakeDockerClient(FakeContainers([c])))
    assert update_role("c1", "u1", ROLE.ADMIN) is False


def test_error_path_the_same_role(monkeypatch):
    """服务层不检查当前角色，重复设置同样角色照常执行命令；结果取决于命令退出码。"""
    c = PasswordFakeContainer("c1", user_exists=True)
    monkeypatch.setattr(extensions, "docker_client", FakeDockerClient(FakeContainers([c])))
    assert update_role("c1", "u1", ROLE.ADMIN) is True


def test_demote_removes_from_both_admin_groups(monkeypatch):
    """降级 COLLABORATOR 回归：旧 `deluser u sudo || deluser u wheel` 在用户同属
    sudo+wheel 时短路只摘第一组，残留另一组管理员权限。命令必须分号串行摘两个组；
    至少摘掉一组 → rc=0 成功，两组都不在 → 仍失败（沿用旧语义）。"""
    c = PasswordFakeContainer("c1", user_exists=True)
    monkeypatch.setattr(extensions, "docker_client", FakeDockerClient(FakeContainers([c])))
    assert update_role("c1", "u1", ROLE.COLLABORATOR) is True
    assert c.exec_calls, "预期执行过容器命令"
    cmd = c.exec_calls[0][0][2]
    assert "deluser u1 sudo && rc=0" in cmd
    assert "deluser u1 wheel && rc=0" in cmd
    assert "exit $rc" in cmd
    assert "|| deluser u1 wheel" not in cmd  # 旧短路结构不得复活


def test_root_branch_clears_both_admin_groups(monkeypatch):
    """ROOT 分支用幂等组清理；密码不在命令里。"""
    c = PasswordFakeContainer("c1", user_exists=True)
    client = FakeDockerClient(FakeContainers([c]))
    monkeypatch.setattr(extensions, "docker_client", client)
    assert update_role("c1", "u1", ROLE.ROOT, root_password=ROOT_PW) is True
    assert c.exec_calls, "预期执行过容器命令"
    cmd = c.exec_calls[0][0][2]
    assert "for g in sudo wheel" in cmd
    assert 'deluser u1 "$g"' in cmd
    assert "user_name123" not in cmd
    assert client.api.started[0]["socket"].sent == b"root:Root#Password9\n"


def test_error_path_role_are_root(monkeypatch):
    """ROOT 角色路径：用 Ctrl 密码 + 幂等组清理 + 删用户，命令成功 → True。"""
    c = PasswordFakeContainer("c1", user_exists=True)
    monkeypatch.setattr(extensions, "docker_client", FakeDockerClient(FakeContainers([c])))
    assert update_role("c1", "u1", ROLE.ROOT, root_password=ROOT_PW) is True


def test_admin_ensure_user_home_in_collaborators(monkeypatch):
    """旧 ROOT 降 ADMIN 建号时家目录仍在 /root/.collaborators（持久化挂载）。"""
    c = PasswordFakeContainer("c1", user_exists=False)
    client = FakeDockerClient(FakeContainers([c]))
    monkeypatch.setattr(extensions, "docker_client", client)
    assert update_role("c1", "u1", ROLE.ADMIN, password=PW) is True
    assert c.exec_calls, "预期执行过容器命令"
    create_cmd = next(call[0][2] for call in c.exec_calls if "useradd -M" in call[0][2])
    assert "useradd -M -d /root/.collaborators/u1" in create_cmd
    assert "useradd -m" not in create_cmd
    assert "chpasswd" not in create_cmd
    assert "u1:u1123" not in create_cmd
    assert client.api.started[0]["socket"].sent == b"u1:Role#Password9\n"


def test_admin_existing_without_password_does_not_chpasswd(monkeypatch):
    c = PasswordFakeContainer("c1", user_exists=True)
    client = FakeDockerClient(FakeContainers([c]))
    monkeypatch.setattr(extensions, "docker_client", client)
    assert update_role("c1", "u1", ROLE.ADMIN) is True
    assert client.api.created == []


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
