"""status_cache 对真实 docker daemon 的集成测试（-m docker 显式开启）。

覆盖冷启动复合确认、sshd 探测/保障、FAILED 终态语义在真实环境的行为——
默认集（-m "not docker"）用 FakeContainer 只测逻辑，这里的测试才验证 exec/apt 的真实行为。
前置：本机有 docker daemon；fixture 内 apt 安装 sshd 需要容器网络。
"""
import pytest

from FuxiYu_NodeKernel import extensions
from FuxiYu_NodeKernel.constant import ContainerStatus
from FuxiYu_NodeKernel.docker_operates.status_cache import ContainerStatusCache

pytestmark = pytest.mark.docker

RUN_IMAGE = "ubuntu:22.04"


def _ensure_docker():
    if extensions.docker_client is None:
        extensions.init_docker()
    return extensions.docker_client


def _run_container(client, name, image, cmd=None):
    """起一个常驻容器；预清理同名残留。"""
    import docker as docker_pkg

    try:
        old = client.containers.get(name)
        old.remove(force=True)
    except docker_pkg.errors.NotFound:
        pass
    container = client.containers.run(
        image,
        name=name,
        command=cmd or ["sleep", "infinity"],
        detach=True,
        remove=False,
    )
    container.reload()
    return container


def _exec(container, cmd: str):
    import docker as docker_pkg

    try:
        # docker-py exec_run 不支持 timeout 参数，这里与生产代码保持一致（无 timeout）
        r = container.exec_run(["/bin/sh", "-c", cmd], user="root")
        return getattr(r, "exit_code", r[0]), r.output
    except docker_pkg.errors.APIError as e:
        return -1, str(e).encode("utf-8", errors="ignore")


@pytest.fixture(scope="module")
def sshd_container():
    """带 sshd 的常驻容器（apt 安装一次，模块级复用）。"""
    client = _ensure_docker()
    name = "pytest_sshd_fixture"
    container = _run_container(client, name, RUN_IMAGE)
    try:
        code, out = _exec(
            container,
            "apt-get update >/dev/null 2>&1 && "
            "DEBIAN_FRONTEND=noninteractive apt-get install -y openssh-server >/dev/null 2>&1 && "
            "mkdir -p /run/sshd && /usr/sbin/sshd && echo READY",
        )
        assert code == 0, f"sshd fixture install failed: {out}"
        yield container
    finally:
        try:
            container.remove(force=True)
        except Exception:
            pass


@pytest.fixture()
def no_sshd_container():
    """无 sshd 的常驻容器（测 FAILED 终态路径）。"""
    client = _ensure_docker()
    name = "pytest_no_sshd"
    container = _run_container(client, name, RUN_IMAGE)
    try:
        yield container
    finally:
        try:
            container.remove(force=True)
        except Exception:
            pass


def test_cold_start_running_container_marks_ready_check(sshd_container):
    """冷启动复合确认（真实环境）：running 容器 → starting + ready_check，不直接 online。"""
    cache = ContainerStatusCache()
    cache._apply_container(sshd_container)
    assert cache.get_state(sshd_container.name)["status"] == "starting"
    assert cache.get(sshd_container.name)["ready_check"] is True


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
