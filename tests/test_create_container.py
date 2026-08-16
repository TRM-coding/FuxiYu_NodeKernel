"""create_container 服务层测试。

- 错误路径（默认集）：FakeDockerClient，无 daemon 无文件系统副作用
- happy path（-m docker）：真实 docker daemon，验证资源参数与 ssh 配置
"""
import os

import pytest

from FuxiYu_NodeKernel.services.container_service import create_container, CreateContainerReturn
from FuxiYu_NodeKernel.utils.Container import Container
from FuxiYu_NodeKernel import extensions

from .conftest import FakeContainer, FakeContainers, FakeDockerClient

VALID_CFG = dict(
    gpu_list=[],
    cpu_number=2,
    memory=4,
    shared_memory=0,
    name="pytest_create_c",
    port=2233,
    image="ubuntu:22.04",
)


def _stat_stub():
    class _Stat:
        st_uid = 0
        st_gid = 0

    return _Stat()


def _patch_fs(monkeypatch):
    """把 create_container 的宿主挂载目录准备逻辑全部打掉，避免真实文件系统副作用。"""
    monkeypatch.setattr(os, "makedirs", lambda *a, **k: None)
    monkeypatch.setattr(os, "stat", lambda *a, **k: _stat_stub())
    monkeypatch.setattr(os, "chown", lambda *a, **k: None)
    monkeypatch.setattr(os, "chmod", lambda *a, **k: None)
    monkeypatch.setattr(os, "getuid", lambda: 0)
    monkeypatch.setattr(os, "getgid", lambda: 0)


def test_error_path_invalid_config(monkeypatch):
    """unsafe owner_name → RuntimeError，发生在触碰 docker 之前。"""
    monkeypatch.setattr(extensions, "docker_client", FakeDockerClient())
    with pytest.raises(RuntimeError, match="unsafe owner_name"):
        create_container("bad;name", Container.Config_info(**VALID_CFG))


def test_error_path_container_exist(monkeypatch):
    """同名容器已存在 → RuntimeError，不触发真实创建。"""
    existing = FakeContainer(name=VALID_CFG["name"])
    monkeypatch.setattr(extensions, "docker_client", FakeDockerClient(FakeContainers([existing])))
    _patch_fs(monkeypatch)
    with pytest.raises(RuntimeError, match="already exists"):
        create_container("admin", Container.Config_info(**VALID_CFG))


@pytest.mark.docker
def test_happy_path():
    """真实 docker：创建 → 校验返回 → 校验容器参数 → 清理。"""
    import docker as docker_pkg

    if extensions.docker_client is None:
        extensions.init_docker()
    client = extensions.docker_client

    test_config = Container.Config_info(**VALID_CFG)

    # 前置清理：避免同名残留
    try:
        old = client.containers.get(test_config.name)
        old.remove(force=True)
    except docker_pkg.errors.NotFound:
        pass

    try:
        result = create_container("admin", test_config)

        assert isinstance(result, CreateContainerReturn)
        assert result.container_name == test_config.name
        assert len(result.container_id) > 0

        real = client.containers.get(result.container_id)
        assert real.name == test_config.name
        assert real.attrs["HostConfig"]["Memory"] == test_config.memory * 1024 * 1024 * 1024
        # 生产代码按 cpuset 固定核（cpu_number=2 → "0,1"），不是 CpuQuota 配额
        assert real.attrs["HostConfig"]["CpusetCpus"] == ",".join(str(i) for i in range(test_config.cpu_number))
        assert "22/tcp" in real.attrs["HostConfig"]["PortBindings"]
        assert real.attrs["HostConfig"]["PortBindings"]["22/tcp"][0]["HostPort"] == str(test_config.port)
    finally:
        try:
            leftover = client.containers.get(test_config.name)
            leftover.remove(force=True)
        except docker_pkg.errors.NotFound:
            pass
