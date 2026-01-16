#TODO: 完成测试用例编写
import pytest
import uuid

from FuxiYu_NodeKernel import extensions
from FuxiYu_NodeKernel.services.container_service import add_collaborator
from FuxiYu_NodeKernel.constant import ROLE


def test_happy_path():
    # 0) 确保 docker_client 可用
    if extensions.docker_client is None:
        extensions.init_docker()
    client = extensions.docker_client

    # 1) 创建一个轻量测试容器
    c = client.containers.run(
        "ubuntu:20.04",
        "tail -f /dev/null",
        detach=True,
        tty=True,
        name=f"pytest_add_{uuid.uuid4().hex[:8]}",
    )

    user = f"u{uuid.uuid4().hex[:8]}"
    # role = ROLE.ADMIN  # 你也可以改成 ROLE.COLLABORATOR 测普通用户
    role = ROLE.COLLABORATOR

    try:
        # 2) 调用被测函数
        ok = add_collaborator(c.id, user, role)
        if not ok:
            # 直接在容器里跑一遍“你函数里那条命令”，看看真实错误
            cmd = f"useradd -m -s /bin/bash {user} && echo '{user}:{user}' | chpasswd"
            r = c.exec_run(["/bin/sh", "-c", cmd], user="root")
            print("DEBUG exit:", r.exit_code)
            print("DEBUG out:", r.output.decode(errors="ignore"))
        assert ok is True, "add_collaborator 返回 False"

        # 3) 验证用户确实被创建：id -u <user> 成功即可
        r = c.exec_run(["/bin/sh", "-c", f"id -u {user}"], user="root")
        assert r.exit_code == 0, f"用户未创建成功: {r.output!r}"

        # 4) 如果是 ADMIN，验证加到了 sudo 组
        if role == ROLE.ADMIN:
            r = c.exec_run(["/bin/sh", "-c", f"id -nG {user} | grep -w sudo"], user="root")
            assert r.exit_code == 0, f"用户未加入 sudo 组: {r.output!r}"

        # 5) （可选）验证密码是否设置成功：不能直接读密码，这里只检查 /etc/shadow 有该用户条目
        r = c.exec_run(["/bin/sh", "-c", f"grep -E '^{user}:' /etc/shadow"], user="root")
        assert r.exit_code == 0, "未在 /etc/shadow 找到用户记录，密码可能未设置"

    finally:
        # 6) 清理容器
        try:
            c.remove(force=True)
        except Exception:
            pass

def test_error_path_invalid_config():
    raise NotImplementedError

def test_error_path_collaborator_not_exist():
    raise NotImplementedError

def test_error_path_collaborator_are_root():
    raise NotImplementedError

def test_error_path_container_not_exist():
    raise NotImplementedError

