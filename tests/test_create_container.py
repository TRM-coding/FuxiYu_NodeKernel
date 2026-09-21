"""create_container 服务层测试。

- 错误路径（默认集）：FakeDockerClient，无 daemon 无文件系统副作用
- happy path（-m docker）：真实 docker daemon，验证资源参数与 ssh 配置
"""
import os

import docker
import pytest

from FuxiYu_NodeKernel.config import PortConfig
from FuxiYu_NodeKernel.docker_operates import port_allocator
from FuxiYu_NodeKernel.services.container_service import build_image, create_container, CreateContainerReturn
from FuxiYu_NodeKernel.utils.Container import Container
from FuxiYu_NodeKernel import extensions

from .conftest import FakeContainer, FakeContainers, FakeDockerClient, FakeImages

# 与本进程代理相关的环境变量（大小写都认）
_PROXY_KEYS = ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "no_proxy", "NO_PROXY")

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
    # 回归锁：**不能传 decode=True**。`ImageCollection.build` 自己会把响应流过一遍
    # `json_stream`（块已是 dict），再传 decode 会让底层先解一次、上层又对 dict 调
    # `.decode()`，报 `'dict' object has no attribute 'decode'` —— 实测直接把整条创建链路
    # 打挂，而单测用的假客户端不会暴露它，只有真 daemon 才看得见。
    assert "decode" not in build_calls[0]


def test_build_proxy_is_injected_as_arg_after_from(monkeypatch):
    """代理必须以 `ARG` 写进 **FROM 之后**——那是唯一绕开 buildargs 的路。

    docker-py 把 `buildargs` 塞在 URL query 里，而 CLI/BuildKit 走 body：某些 daemon 的
    构建路径不读 query，于是"手动 --build-arg 就通、走 SDK 就不通"，且两侧日志一模一样
    （2026-09 实测）。写进 Dockerfile 的 ARG 不经过那条路，谁调都一样。
    """
    from FuxiYu_NodeKernel.services.container_service import _inject_build_proxy

    for k in _PROXY_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example:8091")   # 大写也认，注入时统一小写
    monkeypatch.setenv("https_proxy", "http://proxy.example:8091")

    out = _inject_build_proxy("FROM ubuntu:24.04\n\nUSER root\nRUN apt-get update\n")

    lines = out.splitlines()
    assert lines[0] == "FROM ubuntu:24.04"
    assert lines[1].startswith("# fuxi: 本机构建代理")
    assert lines[2] == "ARG http_proxy=http://proxy.example:8091"
    assert lines[3] == "ARG https_proxy=http://proxy.example:8091"
    assert "RUN apt-get update" in out, "原内容一个不落"


def test_build_proxy_absent_leaves_text_untouched(monkeypatch):
    """没配就**一字不改**——默认行为与从前完全一致。"""
    from FuxiYu_NodeKernel.services.container_service import _inject_build_proxy

    for k in _PROXY_KEYS:
        monkeypatch.delenv(k, raising=False)
    text = "FROM ubuntu:24.04\n\nUSER root\n"
    assert _inject_build_proxy(text) == text


def test_build_proxy_never_injects_no_proxy(monkeypatch):
    """**no_proxy 绝不注入**：它会让构建里的请求绕开代理直连。

    实测（2026-09）：某台机器上 apt 主站解析到内网地址，而 no_proxy 写着
    `10.0.0.0/8,192.168.0.0/16` → apt 绕开代理 → 被校园网拦下 → 报的却是
    `Clearsigned file isn't valid, got 'NOSPLIT'`，极难定位。
    """
    from FuxiYu_NodeKernel.services.container_service import _inject_build_proxy

    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example:8091")
    monkeypatch.setenv("NO_PROXY", "localhost,10.0.0.0/8")

    out = _inject_build_proxy("FROM ubuntu:24.04\n")
    assert "no_proxy" not in out.lower()
    assert "10.0.0.0/8" not in out


def test_build_proxy_rejects_illegal_values(monkeypatch):
    """非法值（会被拼进 Dockerfile 文本）一律忽略。"""
    from FuxiYu_NodeKernel.services.container_service import _inject_build_proxy

    text = "FROM ubuntu:24.04\n"
    for bad in ("proxy.example", "http://a b", "http://x\nRUN evil", "http://x'$(id)"):
        for k in _PROXY_KEYS:
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("http_proxy", bad)
        assert _inject_build_proxy(text) == text, bad


def _clear_proxy_env(monkeypatch):
    for k in _PROXY_KEYS:
        monkeypatch.delenv(k, raising=False)


def test_runtime_proxy_env_pairs_lower_and_upper(monkeypatch):
    """运行期代理：读到什么就大小写各出一份；**no_proxy 绝不跟着进去**。"""
    from FuxiYu_NodeKernel.services.container_service import _runtime_proxy_env

    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example:8091")   # 大写也认
    monkeypatch.setenv("NO_PROXY", "localhost,10.0.0.0/8")

    assert _runtime_proxy_env() == {
        "http_proxy": "http://proxy.example:8091",
        "HTTP_PROXY": "http://proxy.example:8091",
    }


def test_runtime_proxy_env_empty_without_proxy(monkeypatch):
    from FuxiYu_NodeKernel.services.container_service import _runtime_proxy_env

    _clear_proxy_env(monkeypatch)
    assert _runtime_proxy_env() == {}


def test_runtime_proxy_setup_merges_etc_environment(monkeypatch):
    """`/etc/environment` 是**合并**写入，不是覆盖。

    回归锁：旧实现是 `> /etc/environment`，会把镜像自带的 PATH 一起顶掉——2026-09 在学生的
    容器里实测看到该文件只剩一行 PATH（那行是镜像的），覆盖式写入会让 SSH 会话连 PATH 都没。
    """
    from FuxiYu_NodeKernel.services.container_service import _runtime_proxy_setup_command

    cmd = _runtime_proxy_setup_command(
        {"http_proxy": "http://p:8091", "https_proxy": "http://p:8091"}
    )

    assert ">> /etc/environment" in cmd, "追加而不是覆盖"
    assert "> /etc/environment" not in cmd.replace(">> /etc/environment", ""), "不能有覆盖式重定向"
    assert "[ -d /etc/apt/apt.conf.d ]" in cmd, "apt 配置只在 apt 系镜像上写"
    assert "http_proxy=http://p:8091" in cmd


def test_create_container_passes_runtime_proxy_environment(monkeypatch):
    """给容器主进程与 `docker exec` 的那一份（SSH 会话那份走 /etc/environment）。"""
    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv("https_proxy", "http://proxy.example:8091")

    _, kwargs = _run_and_capture(monkeypatch)

    assert kwargs["environment"]["https_proxy"] == "http://proxy.example:8091"
    assert kwargs["environment"]["HTTPS_PROXY"] == "http://proxy.example:8091"


def test_create_container_omits_environment_without_proxy(monkeypatch):
    """没配代理就**不传这个键**（空 dict 也会被 docker 当成"设了环境"）。"""
    _clear_proxy_env(monkeypatch)

    _, kwargs = _run_and_capture(monkeypatch)

    assert "environment" not in kwargs


def test_create_container_writes_proxy_into_container(monkeypatch):
    """代理必须在创建流程里**真的被写进容器**，且早于其它命令。

    回归锁：这段注入在 create_container 瘦身时被整块删掉过（38de262），学生的症状是
    "容器内网络不通"——平台侧什么都看不出来。锁住"有人再删它"这件事。
    """
    created = []

    class _Containers(FakeContainers):
        def run(self, *a, **k):
            c = FakeContainer(name=k.get("name", "c1"))
            created.append(c)
            return c

    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv("http_proxy", "http://proxy.example:8091")
    monkeypatch.setattr(extensions, "docker_client", FakeDockerClient(_Containers()))
    _patch_fs(monkeypatch)
    monkeypatch.setenv("NODE_CONTAINERS_BASE", "/tmp")

    create_container("admin", Container.Config_info(**VALID_CFG))

    cmds = [str(call[0]) for call in created[0].exec_calls]
    proxy_idx = next(i for i, c in enumerate(cmds) if "/etc/environment" in c)
    chpasswd_idx = next(i for i, c in enumerate(cmds) if "chpasswd" in c)
    assert proxy_idx < chpasswd_idx


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
    # 宿主端口由 Node 分配并**显式绑定**（2026-09 决策）：号跟着容器走，不再随 -P 漂
    ports = run_calls[0][1]["ports"]
    assert set(ports) == {"22/tcp"}
    assert PortConfig.NODE_PORT_RANGE_START <= ports["22/tcp"] <= PortConfig.NODE_PORT_RANGE_END
    assert run_calls[0][1]["publish_all_ports"] is False
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


def _create_and_capture(monkeypatch, *, exposed=None, missing_image=False, containers=None):
    """跑一次 create_container，返回 (containers 假实现, images 假实现)。

    宿主 /proc 的占用被打空：分配结果必须只由用例摆出的占用决定。
    """
    containers = containers or FakeContainers()
    images = FakeImages(exposed=exposed, missing=missing_image)
    monkeypatch.setattr(extensions, "docker_client", FakeDockerClient(containers, images))
    monkeypatch.setattr(port_allocator, "_system_bound_ports", lambda: set())
    _patch_fs(monkeypatch)
    monkeypatch.setenv("NODE_CONTAINERS_BASE", "/tmp")
    create_container("admin", Container.Config_info(**VALID_CFG))
    return containers, images


def test_all_exposed_ports_get_an_explicit_host_port(monkeypatch):
    """★ 保留 -P 的便利（镜像 EXPOSE 的端口全都发布），但号由 Node 写死。

    这是换掉 `-P` 的**唯一前提**：漏发一个 EXPOSE 端口，学生的服务就再也连不上了。
    """
    containers, _ = _create_and_capture(
        monkeypatch, exposed={"8080/tcp": {}, "50000/tcp": {}}
    )

    start = PortConfig.NODE_PORT_RANGE_START
    assert containers.run_calls[0][1]["ports"] == {
        "22/tcp": start, "8080/tcp": start + 1, "50000/tcp": start + 2,
    }


def test_image_absent_locally_is_pulled_to_read_its_expose(monkeypatch):
    """本地没有镜像就补拉一次（`docker run` 本来也会隐式拉），否则会静默退化成"只发 22"。"""
    containers, images = _create_and_capture(
        monkeypatch, exposed={"8080/tcp": {}}, missing_image=True
    )

    assert images.pulled == [VALID_CFG["image"]]
    assert set(containers.run_calls[0][1]["ports"]) == {"22/tcp", "8080/tcp"}


def test_port_conflict_reallocates_the_whole_group(monkeypatch):
    """扫描与绑定之间被别人抢了号 → 整组换号重试，不做单端口修补。"""
    start = PortConfig.NODE_PORT_RANGE_START
    attempts = []

    class _Flaky(FakeContainers):
        def run(self, *a, **k):
            attempts.append(k["ports"])
            if len(attempts) == 1:
                raise docker.errors.APIError(
                    f"driver failed programming external connectivity on endpoint c: "
                    f"Bind for 0.0.0.0:{start} failed: port is already allocated"
                )
            return super().run(*a, **k)

    _create_and_capture(monkeypatch, containers=_Flaky())

    assert attempts == [{"22/tcp": start}, {"22/tcp": start + 1}]


def test_leftover_container_is_removed_before_retry(monkeypatch):
    """端口冲突发生在 start 阶段：容器对象已经建出来了，不清掉下一次尝试会撞同名。"""
    start = PortConfig.NODE_PORT_RANGE_START
    attempts = []
    created = []

    class _Flaky(FakeContainers):
        def run(self, *a, **k):
            attempts.append(k["ports"])
            container = FakeContainer(name=k["name"], status="created")
            created.append(container)
            self._existing.append(container)  # 半成品容器确实存在于 daemon 里
            if len(attempts) == 1:
                raise docker.errors.APIError(
                    f"Bind for 0.0.0.0:{start} failed: port is already allocated"
                )
            return container

    _create_and_capture(monkeypatch, containers=_Flaky())

    assert created[0].removed is True


def test_repeated_bind_conflicts_stop_at_the_attempt_cap(monkeypatch):
    """反复冲突是**系统性信号**（扫描与 docker 不一致），不该退化成上万次 docker 调用。"""
    start = PortConfig.NODE_PORT_RANGE_START

    class _AlwaysConflicting(FakeContainers):
        def run(self, *a, **k):
            self.run_calls.append((a, k))
            raise docker.errors.APIError(
                "Bind for 0.0.0.0:20000 failed: port is already allocated"
            )

    containers = _AlwaysConflicting()
    with pytest.raises(RuntimeError, match="failed to bind host ports after 10 attempts"):
        _create_and_capture(monkeypatch, containers=containers)

    # 每次尝试都换了号（整组重分配），不是在同一号上死磕
    tried = [k["ports"]["22/tcp"] for _, k in containers.run_calls]
    assert tried == list(range(start, start + 10))


def test_unrelated_run_failure_is_not_retried(monkeypatch):
    """只对端口冲突重试：镜像缺失之类的失败重试十次只是把错误拖慢十倍。"""
    class _Boom(FakeContainers):
        def run(self, *a, **k):
            self.run_calls.append((a, k))
            raise docker.errors.APIError("No such image: fuxi/nope")

    containers = _Boom()
    with pytest.raises(docker.errors.APIError, match="No such image"):
        _create_and_capture(monkeypatch, containers=containers)

    assert len(containers.run_calls) == 1


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


def test_build_image_surfaces_the_raw_build_output(monkeypatch):
    """构建失败时必须把 docker build 的**原始输出**带出来。

    只报一句 "returned a non-zero code: 100" 的话，调用方看不出 apt 到底报了什么——
    2026-09 实测为此从"ssh-keygen 找不到"一路倒推到"构建时没有代理"。
    """
    class _Images:
        def get(self, tag):
            raise docker.errors.ImageNotFound("not found")

        def build(self, **kwargs):
            raise docker.errors.BuildError(
                "The command '/bin/sh -c apt-get update ...' returned a non-zero code: 100",
                build_log=[
                    {"stream": "Step 3/5 : RUN set -eu; apt-get update ...\n"},
                    {"stream": "Err:1 http://archive.ubuntu.com/ubuntu noble InRelease\n"},
                    {"stream": "  Clearsigned file isn't valid, got 'NOSPLIT'\n"},
                    {"stream": "E: The repository is not signed.\n"},
                ],
            )

    class _Client:
        def __init__(self):
            self.images = _Images()

    monkeypatch.setattr(extensions, "docker_client", _Client())

    with pytest.raises(RuntimeError) as excinfo:
        build_image({"dockerfile_text": "FROM ubuntu:24.04\n", "image_tag": "fuxi/image-1:x"})

    message = str(excinfo.value)
    assert "non-zero code: 100" in message, "原始异常仍要在"
    assert "NOSPLIT" in message, "docker build 的原始输出必须带出来"
    assert "not signed" in message


def test_build_log_tail_keeps_only_the_end():
    """只留末尾：真正的原因总在最后几行，整段塞进 failed_detail 反而没人看。"""
    from FuxiYu_NodeKernel.services.container_service import _build_log_tail

    log = [{"stream": f"line-{i}\n"} for i in range(50)]
    tail = _build_log_tail(log, limit=3)
    assert tail == "line-47\nline-48\nline-49"


def test_build_log_tail_tolerates_junk():
    from FuxiYu_NodeKernel.services.container_service import _build_log_tail

    assert _build_log_tail(None) == ""
    assert _build_log_tail([{"stream": ""}, {"error": "boom"}]) == "boom"


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


def _run_and_capture(monkeypatch):
    """跑一次 create_container，返回 docker containers.run 收到的 (args, kwargs)。"""
    run_calls = []

    class _Containers(FakeContainers):
        def run(self, *a, **k):
            run_calls.append((a, k))
            return FakeContainer(name=k.get("name", "c1"))

    monkeypatch.setattr(extensions, "docker_client", FakeDockerClient(_Containers()))
    _patch_fs(monkeypatch)
    monkeypatch.setenv("NODE_CONTAINERS_BASE", "/tmp")
    create_container("admin", Container.Config_info(**VALID_CFG))
    return run_calls[0]


def test_create_container_passes_no_command_and_does_not_touch_entrypoint(monkeypatch):
    """Node 是**纯执行器**：容器跑什么由镜像自己带，Node 一个字节都不插手。

    2026-09 决策：启动命令由 Ctrl 渲染成最终 Dockerfile 的**最后一行 ENTRYPOINT**，
    因此它已经是镜像的一部分。Node 这边必须**什么都不传**——

    - 传 command 会顶掉镜像的 CMD 语义（而且不置空 Entrypoint 时还会被镜像入口当参数吃掉，
      2026-09 实测复现过：镜像入口为 /bin/echo 时容器打印 "FROM-ENTRYPOINT tail -f /dev/null"）；
    - 传 entrypoint 更是越权：那是镜像的定义。

    这条断言同时是对"分工"的锁：Node 侧再出现任何关于"跑什么"的判断，都是回归。
    """
    args, kwargs = _run_and_capture(monkeypatch)
    assert args == (VALID_CFG["image"],), "只传镜像名，不传 command"
    assert "entrypoint" not in kwargs, "不碰镜像的 Entrypoint"
    assert "command" not in kwargs


def test_create_container_explains_image_that_exits_immediately(monkeypatch):
    """容器起来就死 → 报错要指向真正的原因，而不是 sshd。

    "sshd gate failed" 会把人引去查 sshd；真因通常是镜像的 ENTRYPOINT 立刻退出了。
    """

    class _ExitedContainer(FakeContainer):
        def __init__(self, **kw):
            super().__init__(status="exited", **kw)

        def exec_run(self, cmd, **kw):
            # 只让 sshd 那一关失败（前面的 chpasswd 等照常），模拟"容器一退出，
            # 到守门这一步所有 exec 都失败"的真实时序
            if isinstance(cmd, list) and len(cmd) >= 3 and "/usr/sbin/sshd" in cmd[2]:
                raise RuntimeError("container is not running")
            return super().exec_run(cmd, **kw)

    class _Containers(FakeContainers):
        def run(self, *a, **k):
            return _ExitedContainer(name=k.get("name", "c1"))

    monkeypatch.setattr(extensions, "docker_client", FakeDockerClient(_Containers()))
    _patch_fs(monkeypatch)
    monkeypatch.setenv("NODE_CONTAINERS_BASE", "/tmp")

    with pytest.raises(RuntimeError, match="exited immediately"):
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

    # 这个用例要跑得完，镜像里必须有 sshd（平台构建出来的镜像都有，裸 ubuntu 没有）。
    # 所以允许指一个真实镜像：NODE_TEST_IMAGE=fuxi/image-1:<tag>。
    docker_cfg = dict(VALID_CFG)
    docker_cfg["image"] = os.getenv("NODE_TEST_IMAGE", VALID_CFG["image"])
    test_config = Container.Config_info(**docker_cfg)
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

    bound_port = None
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
        # 宿主端口由 Node 从分配段里给并**显式写入** HostConfig.PortBindings：
        # 号跟着容器走，stop/restart 不会漂（2026-09 决策）。config.port 是 Ctrl 时代的
        # 遗留字段，Node 只记日志、不采用。
        binding = real.attrs["HostConfig"]["PortBindings"]["22/tcp"][0]["HostPort"]
        assert int(binding) in range(
            PortConfig.NODE_PORT_RANGE_START, PortConfig.NODE_PORT_RANGE_END + 1
        )
        assert real.attrs["NetworkSettings"]["Ports"]["22/tcp"][0]["HostPort"] == binding
        bound_port = int(binding)
        # 分配器读到的占用视图必须包含这个刚发布的号（与回显同一个字段）
        assert bound_port in port_allocator.occupied_host_ports(client=client)

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

    # 「删除即释放」——号回到池子里，下一个容器能接着用（生命周期规则的回归锁）
    assert bound_port is not None
    assert bound_port not in port_allocator.occupied_host_ports(client=client)
