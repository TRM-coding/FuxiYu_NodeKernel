"""status_cache 对真实 docker daemon 的集成测试（-m docker 显式开启）。

覆盖冷启动复合确认、sshd 探测/保障、FAILED 终态语义在真实环境的行为——
默认集（-m "not docker"）用 FakeContainer 只测逻辑，这里的测试才验证 exec/apt 的真实行为。
前置：本机有 docker daemon；fixture 内 apt 安装 sshd 需要容器网络。
本文件不再按固定名称预删容器；每次 fixture 使用唯一名称/label，只清理自己
创建的 Docker ID。apt 安装有有界 timeout，失败时按环境前置 skip，不伪造行为通过。
"""
import os
import shlex
import uuid

import pytest

from FuxiYu_NodeKernel import extensions
from FuxiYu_NodeKernel.constant import ContainerStatus
from FuxiYu_NodeKernel.docker_operates.status_cache import ContainerStatusCache

def _local_docker_available() -> bool:
    try:
        import docker as _docker

        client = _docker.from_env()
        client.ping()
        return True
    except Exception:
        return False


pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(not _local_docker_available(), reason="local Docker daemon unavailable"),
]

RUN_IMAGE = os.getenv("NODE_TEST_SSHD_IMAGE", "ubuntu:22.04")
NO_SSHD_IMAGE = os.getenv("NODE_TEST_NO_SSHD_IMAGE", "ubuntu:22.04")
_LABEL_KEY = "fuxi.node.test"
_LABEL_VALUE = "docker-status-cache"


def _ensure_docker():
    if extensions.docker_client is None:
        extensions.init_docker()
    return extensions.docker_client


def _run_container(client, prefix, image, cmd=None):
    """起一个本次 fixture 独占的常驻容器；不预删任何同名容器。"""
    import docker as docker_pkg

    name = f"pytest-{prefix}-{uuid.uuid4().hex[:10]}"
    labels = {_LABEL_KEY: _LABEL_VALUE, "fuxi.node.test.id": name}
    try:
        container = client.containers.run(
            image,
            name=name,
            command=cmd or ["sleep", "infinity"],
            detach=True,
            remove=False,
            labels=labels,
        )
    except docker_pkg.errors.ImageNotFound as e:
        pytest.skip(f"local Docker test image unavailable: {image}: {e}")
    container.reload()
    if container.status != "running":
        logs = ""
        try:
            logs = container.logs().decode("utf-8", errors="replace")[-800:]
        except Exception:
            pass
        pytest.fail(f"fixture container did not stay running: status={container.status} logs={logs}")
    return container


def _remove_own_container(client, container):
    import docker as docker_pkg

    container_id = getattr(container, "id", None)
    if not container_id:
        return
    try:
        current = client.containers.get(container_id)
    except docker_pkg.errors.NotFound:
        return
    labels = ((getattr(current, "attrs", None) or {}).get("Config") or {}).get("Labels") or {}
    if labels.get(_LABEL_KEY) != _LABEL_VALUE:
        return
    try:
        current.remove(force=True)
    except docker_pkg.errors.NotFound:
        pass


def _exec(container, cmd: str, *, timeout: int = 120):
    import docker as docker_pkg

    # 容器内 timeout 把任意 exec 变成有界操作；docker-py exec_run 本身没有
    # timeout 参数，绝不能让它无限等待 apt/网络。
    wrapped = f"timeout {int(timeout)}s /bin/sh -c {shlex.quote(cmd)}"
    try:
        r = container.exec_run(["/bin/sh", "-c", wrapped], user="root")
        return getattr(r, "exit_code", r[0]), r.output
    except docker_pkg.errors.APIError as e:
        return -1, str(e).encode("utf-8", errors="ignore")


@pytest.fixture(scope="module")
def sshd_container():
    """带 sshd 的常驻容器（唯一名称；apt 安装有界，模块级复用）。"""
    client = _ensure_docker()
    container = _run_container(client, "sshd", RUN_IMAGE)
    try:
        code, out = _exec(container, "test -x /usr/sbin/sshd && echo READY", timeout=20)
        if code != 0:
            install = (
                "apt-get -o Acquire::http::Timeout=15 -o Acquire::https::Timeout=15 "
                "-o Acquire::Retries=0 update >/dev/null 2>&1 && "
                "DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::http::Timeout=15 "
                "-o Acquire::https::Timeout=15 -o Acquire::Retries=0 install -y openssh-server "
                ">/dev/null 2>&1 && mkdir -p /run/sshd && /usr/sbin/sshd && echo READY"
            )
            code, out = _exec(container, install, timeout=240)
        if code != 0:
            pytest.skip(
                "sshd fixture image cannot install openssh-server within bound "
                f"(image={RUN_IMAGE} rc={code} out={out[-500:]!r}); set NODE_TEST_SSHD_IMAGE "
                "to an image with /usr/sbin/sshd"
            )
        yield container
    finally:
        _remove_own_container(client, container)


@pytest.fixture()
def no_sshd_container():
    """无 sshd 的常驻容器（测 FAILED 终态路径）。"""
    client = _ensure_docker()
    container = _run_container(client, "no-sshd", NO_SSHD_IMAGE)
    try:
        yield container
    finally:
        _remove_own_container(client, container)


def test_cold_start_running_container_marks_ready_check(no_sshd_container):
    """冷启动复合确认（真实环境）：running 容器 → starting + ready_check，不直接 online。"""
    cache = ContainerStatusCache()
    cache._apply_container(no_sshd_container)
    assert cache.get_state(no_sshd_container.name)["status"] == "starting"
    assert cache.get(no_sshd_container.name)["ready_check"] is True


def test_probe_sshd_true_when_installed(sshd_container):
    cache = ContainerStatusCache()
    assert cache._probe_sshd(sshd_container.name) is True


def test_probe_and_ensure_online_chain(sshd_container):
    """复合确认全链：冷启动 → probe → online；对账不重挂 ready_check（无振荡）。"""
    cache = ContainerStatusCache()
    cache._apply_container(sshd_container)
    cache._probe_ready_checks_once()
    assert cache.get_state(sshd_container.name)["status"] == "online"
    cache._apply_container(sshd_container)
    assert cache.get_state(sshd_container.name)["status"] == "online"
    assert cache.get(sshd_container.name).get("ready_check") is not True


def test_ensure_sshd_idempotent(sshd_container):
    """保障幂等：已运行的 sshd 再拉起不破坏状态（真实 exec）。"""
    cache = ContainerStatusCache()
    status = cache._ensure_sshd_started(sshd_container.name)
    assert status in ("started", "transient")
    assert cache._probe_sshd(sshd_container.name) is True


def test_no_sshd_container_marked_failed(no_sshd_container):
    """无 sshd 容器：probe False → ensure 发现未装 → 终态 FAILED（真实 exec 127 路径）。"""
    cache = ContainerStatusCache()
    cache.mark_ready_check(no_sshd_container.name)
    cache._probe_ready_checks_once()
    assert cache.get_state(no_sshd_container.name)["status"] == "failed"
    assert cache.get(no_sshd_container.name).get("ready_check") is not True


def test_cold_start_reconcile_full_flow(sshd_container):
    """崩溃恢复仿真：新 cache 实例（Node 重启）→ 对账 → 复合确认 → probe → online。"""
    cache = ContainerStatusCache()
    cache._apply_container(sshd_container)
    assert cache.get_state(sshd_container.name)["status"] == "starting"
    cache._probe_ready_checks_once()
    assert cache.get_state(sshd_container.name)["status"] == "online"
