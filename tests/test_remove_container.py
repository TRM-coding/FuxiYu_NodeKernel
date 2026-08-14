"""remove_container 服务层测试。

- 错误路径（默认集）：FakeDockerClient
- happy path（-m docker）：真实 docker daemon
"""
import pytest
import docker as docker_pkg

from FuxiYu_NodeKernel.services.container_service import remove_container, RemoveContinaerReturn
from FuxiYu_NodeKernel import extensions

from .conftest import FakeContainers, FakeDockerClient


def test_error_path_container_not_exist(monkeypatch):
    """容器不存在 → NOTFOUND。"""
    monkeypatch.setattr(extensions, "docker_client", FakeDockerClient())
    assert remove_container("ghost") == RemoveContinaerReturn.NOTFOUND


def test_error_path_invalid_config(monkeypatch):
    """docker 查询抛出意外异常（既非 NotFound 也非可识别错误）→ FAILED。"""

    class _BoomContainers(FakeContainers):
        def get(self, name_or_id):
            raise RuntimeError("boom")

    monkeypatch.setattr(extensions, "docker_client", FakeDockerClient(_BoomContainers()))
    assert remove_container("c1") == RemoveContinaerReturn.FAILED


@pytest.mark.docker
def test_happy_path():
    """真实 docker：创建临时容器 → 删除 → 确认 get 抛 NotFound。"""
    import uuid

    if extensions.docker_client is None:
        extensions.init_docker()
    client = extensions.docker_client

    name = f"pytest_rm_{uuid.uuid4().hex[:8]}"
    c = client.containers.run("ubuntu:22.04", "tail -f /dev/null", detach=True, tty=True, name=name)

    try:
        code = remove_container(c.id)
        assert code == RemoveContinaerReturn.SUCCESS
        with pytest.raises(docker_pkg.errors.NotFound):
            client.containers.get(c.id)
    finally:
        try:
            c.remove(force=True)
        except Exception:
            pass
