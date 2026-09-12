"""create_container 服务层测试。

- 错误路径（默认集）：FakeDockerClient，无 daemon 无文件系统副作用
- happy path（-m docker）：真实 docker daemon，验证资源参数与 ssh 配置
"""
import os

import docker
import pytest

from FuxiYu_NodeKernel.services.container_service import build_image, create_container, CreateContainerReturn
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
    if hasattr(os, "chown"):  # POSIX-only；Windows 无此属性
        monkeypatch.setattr(os, "chown", lambda *a, **k: None)
    monkeypatch.setattr(os, "chmod", lambda *a, **k: None)
    if hasattr(os, "getuid"):  # POSIX-only
        monkeypatch.setattr(os, "getuid", lambda: 0)
    if hasattr(os, "getgid"):  # POSIX-only
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


def test_build_image_builds_missing_tag(monkeypatch):
    """build_image: tag 不存在时临时写 Dockerfile 并 build。"""
    build_calls = []

    class _Images:
        def get(self, tag):
            raise docker.errors.ImageNotFound("not found")

        def build(self, **kwargs):
            build_calls.append(kwargs)
            return ([], [])

    class _BuildAwareClient:
        def __init__(self):
            self.images = _Images()

    monkeypatch.setattr(extensions, "docker_client", _BuildAwareClient())
    build = {
        "dockerfile_text": "FROM ubuntu:22.04\nRUN echo hello\n",
        "image_tag": "fuxi/image-7:20260826T000000Z",
    }

    assert build_image(build) == build["image_tag"]
    assert build_calls and build_calls[0]["tag"] == build["image_tag"]
    assert build_calls[0]["dockerfile"] == "Dockerfile"


def test_create_container_uses_prepared_image_and_only_runs_sshd_gate(monkeypatch):
    """create_container 只接收已准备好的 image tag，不关心 Dockerfile/build。"""
    run_calls = []
    created = []

    class _BuildAwareContainers(FakeContainers):
        def run(self, *a, **k):
            run_calls.append((a, k))
            container = FakeContainer(name=k.get("name", "c1"))
            created.append(container)
            return container

    monkeypatch.setattr(extensions, "docker_client", FakeDockerClient(_BuildAwareContainers()))
    _patch_fs(monkeypatch)
    monkeypatch.setenv("NODE_CONTAINERS_BASE", "/tmp")

    cfg_data = dict(VALID_CFG)
    cfg_data["image"] = "fuxi/image-7:20260826T000000Z"
    result = create_container("admin", Container.Config_info(**cfg_data))

    assert isinstance(result, CreateContainerReturn)
    assert run_calls and run_calls[0][0][0] == cfg_data["image"]
    # 端口发布交给 docker（2026-08 决策）：22 与 EXPOSE 全部自动分配宿主端口
    assert run_calls[0][1]["ports"] == {"22/tcp": None}
    assert run_calls[0][1]["publish_all_ports"] is True
    exec_commands = [
        call[0][2] for call in created[0].exec_calls
        if isinstance(call[0], list) and len(call[0]) >= 3
    ]
    joined = "\n".join(exec_commands)
    assert "apt-get update" not in joined
    assert "apt-get install" not in joined
    assert "mkdir -p /run/sshd" in joined
    assert "ssh-keygen -A" in joined
    assert "/usr/sbin/sshd" in joined


def test_create_container_gpu_request_uses_device_ids_without_driver(monkeypatch):
    """GPU 容器请求只指定设备 ID 和能力，保持旧部署链路的 Docker runtime 适配面。"""
    device_request_calls = []
    run_calls = []

    def _device_request_stub(**kwargs):
        device_request_calls.append(kwargs)
        return kwargs

    class _Containers(FakeContainers):
        def run(self, *a, **k):
            run_calls.append((a, k))
            return FakeContainer(name=k.get("name", "c1"))

    monkeypatch.setattr(docker.types, "DeviceRequest", _device_request_stub)
    monkeypatch.setattr(extensions, "docker_client", FakeDockerClient(_Containers()))
    _patch_fs(monkeypatch)
    monkeypatch.setenv("NODE_CONTAINERS_BASE", "/tmp")

    cfg_data = dict(VALID_CFG)
    cfg_data["gpu_list"] = [0, 2]

    result = create_container("admin", Container.Config_info(**cfg_data))

    assert isinstance(result, CreateContainerReturn)
    assert device_request_calls == [
        {
            "device_ids": ["0", "2"],
            "capabilities": [["gpu"]],
        }
    ]
    assert run_calls[0][1]["device_requests"] == device_request_calls


def test_create_container_restore_reuses_existing_mount(monkeypatch):
    run_calls = []

    class _Containers(FakeContainers):
        def run(self, *a, **k):
            run_calls.append((a, k))
            return FakeContainer(name=k.get("name", "c1"))

    monkeypatch.setattr(extensions, "docker_client", FakeDockerClient(_Containers()))
    _patch_fs(monkeypatch)
    monkeypatch.setenv("NODE_CONTAINERS_BASE", "/tmp")
    monkeypatch.setattr(os.path, "isdir", lambda path: path == os.path.realpath("/tmp/admin/containers/old_c"))

    result = create_container(
        "admin",
        Container.Config_info(**VALID_CFG),
        restore_mount_path="/tmp/admin/containers/old_c",
    )

    assert isinstance(result, CreateContainerReturn)
    assert result.bind_mount_path.replace("\\", "/").endswith("/tmp/admin/containers/old_c")
    assert run_calls[0][1]["mounts"][0]["Source"].replace("\\", "/").endswith("/tmp/admin/containers/old_c")


def test_create_container_restore_rejects_mount_outside_base(monkeypatch):
    monkeypatch.setattr(extensions, "docker_client", FakeDockerClient())
    _patch_fs(monkeypatch)
    monkeypatch.setenv("NODE_CONTAINERS_BASE", "/tmp")
    monkeypatch.setattr(os.path, "isdir", lambda path: True)

    with pytest.raises(RuntimeError, match="unsafe restore mount path"):
        create_container(
            "admin",
            Container.Config_info(**VALID_CFG),
            restore_mount_path="/etc/fuxi-leak",
        )


def test_build_image_uses_cached_image_tag(monkeypatch):
    """同 tag 已存在时命中 Node 本地缓存：跳过 build，直接返回 tag。"""
    build_calls = []

    class _Images:
        def get(self, tag):
            return object()

        def build(self, **kwargs):
            build_calls.append(kwargs)
            return ([], [])

    class _Client:
        def __init__(self):
            self.images = _Images()

    monkeypatch.setattr(extensions, "docker_client", _Client())

    build = {
        "dockerfile_text": "FROM ubuntu:22.04\nRUN echo hello\n",
        "image_tag": "fuxi/image-7:20260826T010203Z",
    }

    result = build_image(build)

    assert result == build["image_tag"]
    assert build_calls == []


def test_no_build_path_does_not_install_sshd_in_node(monkeypatch):
    """旧现场安装链路清退：没有 build payload 时也不再由 Node apt 安装 sshd。"""
    created = []

    class _Containers(FakeContainers):
        def run(self, *a, **k):
            container = FakeContainer(name=k.get("name", "c1"))
            created.append(container)
            return container

    monkeypatch.setattr(extensions, "docker_client", FakeDockerClient(_Containers()))
    _patch_fs(monkeypatch)
    monkeypatch.setenv("NODE_CONTAINERS_BASE", "/tmp")

    result = create_container("admin", Container.Config_info(**VALID_CFG))

    assert isinstance(result, CreateContainerReturn)
    exec_commands = [
        call[0][2] for call in created[0].exec_calls
        if isinstance(call[0], list) and len(call[0]) >= 3
    ]
    joined = "\n".join(exec_commands)
    assert "apt-get update" not in joined
    assert "apt-get install" not in joined
    assert "mkdir -p /run/sshd" in joined
    assert "ssh-keygen -A" in joined
    assert "/usr/sbin/sshd" in joined


def test_create_container_fails_when_sshd_gate_fails(monkeypatch):
    """22/sshd 是创建终末门禁：启动失败必须让 create_container 失败。"""

    class _SshdFailContainer(FakeContainer):
        def exec_run(self, cmd, **kw):
            if isinstance(cmd, list) and len(cmd) >= 3 and "/usr/sbin/sshd" in cmd[2]:
                self.exec_calls.append((cmd, kw))

                class _Result:
                    exit_code = 1
                    output = b"sshd missing"

                    def __getitem__(self, idx: int):
                        if idx == 0:
                            return self.exit_code
                        raise IndexError(idx)

                return _Result()
            return super().exec_run(cmd, **kw)

    class _Containers(FakeContainers):
        def run(self, *a, **k):
            return _SshdFailContainer(name=k.get("name", "c1"))

    monkeypatch.setattr(extensions, "docker_client", FakeDockerClient(_Containers()))
    _patch_fs(monkeypatch)
    monkeypatch.setenv("NODE_CONTAINERS_BASE", "/tmp")

    with pytest.raises(RuntimeError, match="sshd gate failed"):
        create_container("admin", Container.Config_info(**VALID_CFG))


@pytest.mark.docker
def test_happy_path(monkeypatch, tmp_path):
    """真实 docker：创建 → 校验返回 → 校验容器参数 → 校验 sshd 守门 → 清理。"""
    import docker as docker_pkg

    # 宿主挂载根指向可写 tmp 目录（生产默认 /home，测试环境非 root 无权建）
    monkeypatch.setenv("NODE_CONTAINERS_BASE", str(tmp_path))

    if extensions.docker_client is None:
        extensions.init_docker()
    client = extensions.docker_client

    test_config = Container.Config_info(**VALID_CFG)
    # 带公钥：验证守门重排（公钥先于 sshd 安装）
    dummy_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI dummy-key-for-test@fuxi"

    # 前置清理：避免同名残留
    try:
        old = client.containers.get(test_config.name)
        old.remove(force=True)
    except docker_pkg.errors.NotFound:
        pass

    def _exec(container, cmd):
        r = container.exec_run(["/bin/sh", "-c", cmd], user="root")
        return getattr(r, "exit_code", r[0]), r.output

    try:
        result = create_container("admin", test_config, public_key=dummy_key)

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

        # ── 守门重排验证（create 完成 ⟹ sshd 就绪；公钥先于 sshd 安装） ──
        code, out = _exec(real, "test -x /usr/sbin/sshd && echo SSH_BIN_OK")
        assert code == 0 and b"SSH_BIN_OK" in out, f"sshd 未安装: {out}"
        # sshd 在监听（create 直接启动）
        code, out = _exec(real, "pgrep -x sshd >/dev/null && echo SSH_RUN_OK")
        assert code == 0 and b"SSH_RUN_OK" in out, f"sshd 未运行: {out}"
        # 公钥先于 sshd 安装写入
        code, out = _exec(real, "test -f /root/.ssh/authorized_keys && echo KEY_OK")
        assert code == 0 and b"KEY_OK" in out, f"authorized_keys 未写入: {out}"
        # sshd_config 配置生效
        code, out = _exec(real, "grep -q '^PermitRootLogin yes' /etc/ssh/sshd_config && echo CFG_OK")
        assert code == 0 and b"CFG_OK" in out, f"sshd_config 未配置: {out}"
    finally:
        try:
            leftover = client.containers.get(test_config.name)
            leftover.remove(force=True)
        except docker_pkg.errors.NotFound:
            pass
