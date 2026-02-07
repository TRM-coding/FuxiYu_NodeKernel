#TODO: 完成测试用例编写
import pytest
import uuid

from FuxiYu_NodeKernel import extensions
from FuxiYu_NodeKernel.services.container_service import update_role
from FuxiYu_NodeKernel.constant import ROLE


def test_happy_path():
    # 0) 确保 docker_client 可用
    if extensions.docker_client is None:
        extensions.init_docker()
    client = extensions.docker_client

    # 1) 创建测试容器
    c = client.containers.run(
        "ubuntu:20.04",
        "tail -f /dev/null",
        detach=True,
        tty=True,
        name=f"pytest_role_{uuid.uuid4().hex[:8]}",
    )

    user = f"u{uuid.uuid4().hex[:8]}"

    try:
        # 2) 准备环境：安装 sudo + 创建用户
        r = c.exec_run(
            ["/bin/sh", "-c", "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y sudo"],
            user="root",
        )
        assert r.exit_code == 0, f"安装 sudo 失败: {r.output!r}"

        r = c.exec_run(["/bin/sh", "-c", f"useradd -m -s /bin/bash {user}"], user="root")
        assert r.exit_code == 0, f"创建用户失败: {r.output!r}"

        # 3) 升级为 ADMIN：应加入 sudo 组
        ok = update_role(c.id, user, ROLE.ADMIN)
        assert ok is True, "update_role(ADMIN) 返回 False"

        r = c.exec_run(["/bin/sh", "-c", f"id -nG {user} | tr ' ' '\\n' | grep -x sudo"], user="root")
        assert r.exit_code == 0, f"用户未加入 sudo 组: {r.output!r}"

        # 4) 降级为 COLLABORATOR：应移出 sudo 组
        ok = update_role(c.id, user, ROLE.COLLABORATOR)
        assert ok is True, "update_role(COLLABORATOR) 返回 False"

        r = c.exec_run(["/bin/sh", "-c", f"id -nG {user} | tr ' ' '\\n' | grep -x sudo"], user="root")
        assert r.exit_code != 0, "用户仍在 sudo 组（预期已移除）"

    finally:
        # 5) 清理容器
        try:
            c.remove(force=True)
        except Exception:
            pass

def test_error_path_invalid_config():
    raise NotImplementedError

def test_error_path_collaborator_not_exist():
    raise NotImplementedError

def test_error_path_the_same_role():
    raise NotImplementedError

def test_error_path_container_not_exist():
    raise NotImplementedError

def test_error_path_role_are_root():
    raise NotImplementedError