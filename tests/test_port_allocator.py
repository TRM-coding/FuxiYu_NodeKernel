"""宿主端口分配器测试（无 daemon：docker 侧用 FakeDockerClient）。

覆盖三条不变量：
- **占用的两种来源都要看见**：docker 已发布（含停止容器）+ 宿主系统已绑定；
- **分配以容器为单位**：一组端口要么全给，要么整体失败；
- **环耗尽必须抛**，而不是悄悄回退到随机端口。
"""
import pytest

from FuxiYu_NodeKernel.config import PortConfig
from FuxiYu_NodeKernel.docker_operates import port_allocator
from FuxiYu_NodeKernel.docker_operates.port_allocator import (
    PortRangeExhausted,
    allocate_ports,
    container_ports_for,
)

from .conftest import FakeContainer, FakeContainers, FakeDockerClient, FakeImages


# 真实实现（下面那条 autouse fixture 会把模块属性换成空集，测 /proc 解析时要用原件）
_REAL_SYSTEM_BOUND_PORTS = port_allocator._system_bound_ports


@pytest.fixture(autouse=True)
def _no_system_ports(monkeypatch):
    """分配测试默认不看宿主 /proc：结果必须只由用例摆出的占用决定。"""
    monkeypatch.setattr(port_allocator, "_system_bound_ports", lambda: set())


def _live_ports(ports: dict[int, int]) -> dict:
    """NetworkSettings.Ports 的形态：每个已发布端口 IPv4/IPv6 各一条（真实 daemon 实测）。"""
    return {
        f"{p}/tcp": [
            {"HostIp": "0.0.0.0", "HostPort": str(h)},
            {"HostIp": "::", "HostPort": str(h)},
        ]
        for p, h in ports.items()
    }


def _explicit_container(name: str, ports: dict[int, int], status: str = "running") -> FakeContainer:
    """Node **显式绑定**建出来的容器（本方案之后的形态）。

    ★ 已停止时 NetworkSettings.Ports 会被 docker **清空**，号只剩下 HostConfig 里那一份
      ——这是 2026-09 在真机上实测出来的（见 _declared_bindings_host_ports 的表格）。
      早先的假实现把"停止了但 NetworkSettings 还在"当成常态，于是漏掉了整类占用者。
    """
    container = FakeContainer(name=name, status=status)
    container.attrs = {
        "State": {"Status": status},
        "HostConfig": {
            "PortBindings": {
                f"{p}/tcp": [{"HostIp": "", "HostPort": str(h)}] for p, h in ports.items()
            }
        },
        "NetworkSettings": {"Ports": _live_ports(ports) if status == "running" else {}},
    }
    return container


def _legacy_p_container(name: str, ports: dict[int, int]) -> FakeContainer:
    """`-P` 建出来的老容器：HostConfig 里是**空串**，真值只在 NetworkSettings。"""
    container = FakeContainer(name=name, status="running")
    container.attrs = {
        "State": {"Status": "running"},
        "HostConfig": {
            "PortBindings": {f"{p}/tcp": [{"HostIp": "", "HostPort": ""}] for p in ports}
        },
        "NetworkSettings": {"Ports": _live_ports(ports)},
    }
    return container


def _client_of(*containers: FakeContainer) -> FakeDockerClient:
    return FakeDockerClient(FakeContainers(list(containers)))


def _client_with(published: dict[str, dict[int, int]] | None = None) -> FakeDockerClient:
    """published: 容器名 -> {容器端口: 宿主端口}，按**运行中的显式绑定**形态构造。"""
    return _client_of(
        *[_explicit_container(name, ports) for name, ports in (published or {}).items()]
    )


# ── 镜像声明 → 容器端口集合 ─────────────────────────────────────────────


def test_ssh_port_is_forced_even_when_image_does_not_expose_it():
    """SSH 是平台的地基，不能依赖镜像作者写 EXPOSE。"""
    image = FakeImages(exposed={}).get("x")
    assert container_ports_for(image) == ["22/tcp"]


def test_declared_protocol_is_preserved_and_never_coerced_to_tcp():
    image = FakeImages(exposed={"8080/tcp": {}, "53/udp": {}, "9200": {}}).get("x")
    # 无协议后缀 = tcp；/udp 原样保留
    assert container_ports_for(image) == ["22/tcp", "8080/tcp", "9200/tcp", "53/udp"]


def test_exposed_ports_with_junk_keys_are_ignored(monkeypatch):
    image = FakeImages(exposed={"notaport": {}, "8080/sctp": {}, "8081/tcp": {}}).get("x")
    assert container_ports_for(image) == ["22/tcp", "8081/tcp"]


def test_missing_image_config_is_not_fatal():
    class _Bare:
        attrs = {}

    assert container_ports_for(_Bare()) == ["22/tcp"]


# ── 选号 ────────────────────────────────────────────────────────────────


def test_ports_are_handed_out_sequentially_from_range_start():
    """顺序取号（不是真随机）：哪个容器拿哪几个号，肉眼可查。"""
    allocated = allocate_ports(["22/tcp", "8080/tcp", "50000/tcp"], client=_client_with())

    start = PortConfig.NODE_PORT_RANGE_START
    assert allocated == {"22/tcp": start, "8080/tcp": start + 1, "50000/tcp": start + 2}


def test_lowest_container_port_gets_the_lowest_host_port():
    """22 永远拿最小的号——分配结果与入参顺序无关。"""
    allocated = allocate_ports(["50000/tcp", "22/tcp"], client=_client_with())
    start = PortConfig.NODE_PORT_RANGE_START
    assert allocated == {"22/tcp": start, "50000/tcp": start + 1}


def test_docker_published_ports_are_skipped():
    start = PortConfig.NODE_PORT_RANGE_START
    client = _client_with({"old": {22: start}})

    allocated = allocate_ports(["22/tcp"], client=client)

    assert allocated == {"22/tcp": start + 1}


def test_stopped_container_still_holds_its_port():
    """★ 停容器没被删，`docker start` 时会拿同一个号重新绑——所以它算占用。

    这条是**真机实测逼出来的**：docker 停容器时把 NetworkSettings.Ports 清空了，号只剩下
    HostConfig 那一份。只读 NetworkSettings 的分配器会把停止容器的号再分给别人，等它被
    启动时就撞车。
    """
    start = PortConfig.NODE_PORT_RANGE_START
    stopped = _explicit_container("stopped", {22: start, 8080: start + 1}, status="exited")
    assert stopped.attrs["NetworkSettings"]["Ports"] == {}, "前提：停了就没有 NetworkSettings"
    client = _client_of(stopped)

    allocated = allocate_ports(["22/tcp"], client=client)

    assert allocated == {"22/tcp": start + 2}


def test_system_bound_ports_are_skipped(monkeypatch):
    """docker 扫描看不见的那一类：宿主非 docker 进程占着的号。"""
    start = PortConfig.NODE_PORT_RANGE_START
    monkeypatch.setattr(port_allocator, "_system_bound_ports", lambda: {start, start + 1})

    allocated = allocate_ports(["22/tcp"], client=_client_with())

    assert allocated == {"22/tcp": start + 2}


def test_excluded_ports_are_skipped_within_one_allocation():
    """重试时把上一次被 docker 拒掉的号排除掉，但**不落盘**。"""
    start = PortConfig.NODE_PORT_RANGE_START
    allocated = allocate_ports(["22/tcp"], client=_client_with(), exclude={start})
    assert allocated == {"22/tcp": start + 1}


def test_empty_request_allocates_nothing():
    assert allocate_ports([], client=_client_with()) == {}


# ── 环与耗尽 ────────────────────────────────────────────────────────────


def test_ring_wraps_within_the_range(monkeypatch):
    monkeypatch.setattr(PortConfig, "NODE_PORT_RANGE_START", 20000)
    monkeypatch.setattr(PortConfig, "NODE_PORT_RANGE_END", 20001)

    # 20000 被占 → 环内还剩 20001，能分配
    assert allocate_ports(["22/tcp"], client=_client_with(), exclude={20000}) == {"22/tcp": 20001}
    assert allocate_ports(["22/tcp", "8080/tcp"], client=_client_with()) == {
        "22/tcp": 20000, "8080/tcp": 20001
    }


def test_exhausted_ring_raises_instead_of_falling_back(monkeypatch):
    """★ 绝不许回退成随机端口：那正是要根治的漂移。"""
    monkeypatch.setattr(PortConfig, "NODE_PORT_RANGE_START", 20000)
    monkeypatch.setattr(PortConfig, "NODE_PORT_RANGE_END", 20001)

    with pytest.raises(PortRangeExhausted, match="no 3 free host port"):
        allocate_ports(["22/tcp", "8080/tcp", "50000/tcp"], client=_client_with())


def test_group_allocation_is_all_or_nothing(monkeypatch):
    """一组里有一个号分不出来 → 整组失败，不留半分配。"""
    monkeypatch.setattr(PortConfig, "NODE_PORT_RANGE_START", 20000)
    monkeypatch.setattr(PortConfig, "NODE_PORT_RANGE_END", 20002)

    with pytest.raises(PortRangeExhausted):
        allocate_ports(["22/tcp", "8080/tcp", "50000/tcp"], client=_client_with(), exclude={20000})


def test_inverted_range_is_rejected(monkeypatch):
    monkeypatch.setattr(PortConfig, "NODE_PORT_RANGE_START", 29999)
    monkeypatch.setattr(PortConfig, "NODE_PORT_RANGE_END", 20000)

    with pytest.raises(RuntimeError, match="invalid host port range"):
        allocate_ports(["22/tcp"], client=_client_with())


# ── 占用来源：两条都要看见 ──────────────────────────────────────────────


def test_legacy_p_container_is_seen_through_network_settings():
    """回归锁（2026-09 实测）：`-P` 建的容器 HostConfig.PortBindings 里 HostPort 是**空串**，
    只读它会得出"一个号都没占"。这一半靠 NetworkSettings。"""
    start = PortConfig.NODE_PORT_RANGE_START
    legacy = _legacy_p_container("legacy", {22: start})
    assert legacy.attrs["HostConfig"]["PortBindings"]["22/tcp"][0]["HostPort"] == ""

    assert port_allocator._docker_published_ports(_client_of(legacy)) == {start}


def test_stopped_container_is_seen_through_host_config():
    """回归锁（2026-09 真机实测）：**另一半**——停止容器的 NetworkSettings.Ports 是空的
    （`{}`），只读它同样得出"一个号都没占"，然后把停止容器的号分给新容器。

    两份来源是互补的，并集才完整。"""
    start = PortConfig.NODE_PORT_RANGE_START
    stopped = _explicit_container("stopped", {22: start}, status="exited")
    assert stopped.attrs["NetworkSettings"]["Ports"] == {}

    assert port_allocator._docker_published_ports(_client_of(stopped)) == {start}


def test_duplicate_ipv4_and_ipv6_bindings_do_not_double_count():
    start = PortConfig.NODE_PORT_RANGE_START
    legacy = _legacy_p_container("legacy", {22: start})

    # extract_port_info 已按 (容器端口, 宿主端口, 协议) 去重：两条 binding 只算一个号
    assert port_allocator._docker_published_ports(_client_of(legacy)) == {start}


def test_running_explicit_container_is_counted_once_by_both_sources():
    """运行中的显式绑定两个字段都有值——并集不能把它算成两个号（都是同一个数字）。"""
    start = PortConfig.NODE_PORT_RANGE_START
    running = _explicit_container("running", {22: start, 8080: start + 1})

    assert port_allocator._docker_published_ports(_client_of(running)) == {start, start + 1}


def test_docker_scan_failure_refuses_to_allocate_blind(monkeypatch):
    """问不到 docker 时**必须硬失败**，不能降级成 warning。

    某个停止容器占着的号此刻不在宿主 /proc 里，盲选出来的号 docker 会痛快地绑上
    （宿主层面它确实空着），直到那个容器被启动时才炸——错误被推迟、还落到别人身上。
    所以这里要立刻失败，并且报错要说明是"问不到 docker"而不是"端口段有问题"。
    """

    def _boom(client):
        raise RuntimeError("cannot connect to docker")

    monkeypatch.setattr(port_allocator, "_docker_published_ports", _boom)

    with pytest.raises(RuntimeError, match="refusing to allocate blind"):
        allocate_ports(["22/tcp"], client=_client_with())


def test_system_bound_ports_parses_proc_net(tmp_path, monkeypatch):
    """读的是真实的 /proc/net 格式：第 1 列 local_address，端口是十六进制。"""
    table = tmp_path / "tcp"
    table.write_text(
        "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt\n"
        "   0: 00000000:4E20 00000000:0000 0A 00000000:00000000 00:00000000 00000000\n"
        "   1: 0100007F:1F90 00000000:0000 0A 00000000:00000000 00:00000000 00000000\n"
        "   2: 00000000000000000000000000000000:0050 00000000000000000000000000000000:0000 0A\n",
        encoding="ascii",
    )
    monkeypatch.setattr(port_allocator, "_PROC_NET_TABLES", (str(table),))

    # 走真实实现：autouse fixture 换掉的模块属性在这里必须绕开
    assert _REAL_SYSTEM_BOUND_PORTS() == {0x4E20, 0x1F90, 0x50} == {20000, 8080, 80}


def test_unreadable_proc_net_is_treated_as_empty(monkeypatch):
    """非 Linux / 权限不足 → 空集，而不是让创建挂掉（真正的裁决仍是 docker）。"""
    monkeypatch.setattr(port_allocator, "_PROC_NET_TABLES", ("/proc/net/definitely_missing",))
    assert _REAL_SYSTEM_BOUND_PORTS() == set()


def test_occupied_host_ports_is_the_union(monkeypatch):
    start = PortConfig.NODE_PORT_RANGE_START
    monkeypatch.setattr(port_allocator, "_system_bound_ports", lambda: {start + 1})

    assert port_allocator.occupied_host_ports(client=_client_with({"a": {22: start}})) == {
        start, start + 1
    }
