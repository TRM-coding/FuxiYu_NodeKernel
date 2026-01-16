#TODO: 完成测试用例编写
import pytest
import docker

from FuxiYu_NodeKernel.services.container_service import remove_container, RemoveContinaerReturn
from FuxiYu_NodeKernel import extensions


def test_happy_path():
    # 0) 确保 docker_client 可用
    if extensions.docker_client is None:
        extensions.init_docker()
    client = extensions.docker_client

    # 1) 先创建一个真实容器（用于删除）
    name = f"pytest_rm_{__import__('uuid').uuid4().hex[:8]}"
    c = client.containers.run(
        "ubuntu:20.04",
        "tail -f /dev/null",
        detach=True,
        tty=True,
        name=name,
    )

    try:
        # 2) 调用被测函数
        code = remove_container(c.id)

        # 3) 断言返回码正确
        assert code == RemoveContinaerReturn.SUCCESS, f"期望 SUCCESS(0)，实际是 {code}"

        # 4) 断言容器确实被删除：再次 get 应抛 NotFound
        with pytest.raises(docker.errors.NotFound):
            client.containers.get(c.id)

    finally:
        # 5) 防御性清理：防止中途断言失败导致残留
        try:
            c.remove(force=True)
        except Exception:
            pass

def test_error_path_invalid_config():
    raise NotImplementedError

def test_error_path_container_not_exist():
    raise NotImplementedError

