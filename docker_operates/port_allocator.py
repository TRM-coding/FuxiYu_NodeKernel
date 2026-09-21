"""宿主端口分配（分配侧唯一实现）。

与 port_mappings.py 是同一件事的两面：那边读 docker 的事实并**如实汇报**，这边读同一份
事实用来**避开**它——所以回显那份事实直接复用 extract_port_info，不许另写一份解析。

差别只在"已停止的容器"：回显只关心**此刻真的接着**的映射（NetworkSettings），分配器还必须
把**已占住的号**（HostConfig 里写死的绑定）算进来。两处并集见 _docker_published_ports——
"分配器看不见的占用者"最终会变成启动时的端口冲突。

★ 为什么由 Node 分配，而不是让 docker `-P` 随机：随机出来的宿主端口号只在创建那一刻
  确定，容器重建/重跑就换一个，库里记的值永远追不上。**显式绑定写进
  HostConfig.PortBindings，跟着容器走**，stop / restart 都沿用（2026-09 决策）。

★ 为什么不持久化游标或租约表：docker 就是唯一事实来源——Node 重启不必恢复、停止但未删
  的容器天然占住自己的端口、少一份可能与 docker 漂移的状态。每次现扫的代价是每容器一次
  inspect（数十个容器 = 数十次本地调用），而创建容器本身是分钟级操作。

★ 为什么仍然要加锁：单机单 Node 不等于没有并发——创建走后台线程，两个请求会在同一个
  进程里同时选端口。
"""

from __future__ import annotations

import logging
import threading

from ..config import PortConfig
from .port_mappings import extract_port_info

logger = logging.getLogger(__name__)

# 镜像没声明也要发布的端口：SSH 是平台的地基，不能依赖镜像作者的 EXPOSE。
SSH_CONTAINER_PORT = "22/tcp"

# /proc/net 的四张表：IPv4/IPv6 × TCP/UDP。Node 以宿主身份运行，读到的就是宿主 netns
# （哪天 Node 进了容器，这里只会读到它自己的命名空间——所以它必须跑在宿主上）。
_PROC_NET_TABLES = ("/proc/net/tcp", "/proc/net/tcp6", "/proc/net/udp", "/proc/net/udp6")

# 占用扫描 + 选号必须在同一把锁内完成：扫描与绑定之间无论如何都有窗口（Docker 才是最终
# 裁决者），但"本进程内两个创建请求互相看不见对方的选择"这个窗口必须关掉。
_allocation_lock = threading.Lock()


class PortRangeExhausted(RuntimeError):
    """分配段内找不到足够的空闲端口。这是**信号**，不是常态路径。"""


def _spec_sort_key(spec: str) -> tuple[int, int]:
    """端口规格排序：tcp 在前，各自按端口号升序（让 22/tcp 拿到最小的那个号）。"""
    port, _, protocol = str(spec).partition("/")
    return (0 if (protocol or "tcp").lower() == "tcp" else 1, int(port))


def container_ports_for(image) -> list[str]:
    """镜像要发布的容器端口，含强制的 22/tcp。

    ★ 协议以镜像 `Config.ExposedPorts` 为准：`EXPOSE 8080` 等价 `8080/tcp`，写了
      `/udp` 就保留 udp。**绝不把 udp 改成 tcp** —— 改了对不上容器里真正在听的东西。
    """
    attrs = getattr(image, "attrs", None) or {}
    declared = (attrs.get("Config") or {}).get("ExposedPorts") or {}

    specs = {SSH_CONTAINER_PORT}
    for key in declared:
        port_raw, _, protocol = str(key).partition("/")
        protocol = (protocol or "tcp").lower()
        try:
            port = int(port_raw)
        except (TypeError, ValueError):
            logger.warning("ignoring unparsable ExposedPorts key: %r", key)
            continue
        if protocol not in ("tcp", "udp"):
            logger.warning("ignoring ExposedPorts key with unsupported protocol: %r", key)
            continue
        specs.add(f"{port}/{protocol}")

    return sorted(specs, key=_spec_sort_key)


def _system_bound_ports() -> set[int]:
    """宿主上已被绑定的本地端口（四张表、不分状态）。

    ★ 不分状态是**故意保守**：TCP 只看 LISTEN 会漏掉 TIME_WAIT 之类仍然占着号的套接字，
      而多算一个端口只是少用一个号，漏算一个才会选到别人的端口上。
      ephemeral 段（32768+）的客户端套接字会被一并收进来，但那与分配段不相交，无害。

    读不到（非 Linux、权限不足）就当空集——真正的裁决仍是 docker 自己的绑定结果。
    """
    bound: set[int] = set()
    for path in _PROC_NET_TABLES:
        try:
            with open(path, "r", encoding="ascii", errors="replace") as handle:
                next(handle, None)  # 表头
                for line in handle:
                    fields = line.split()
                    if len(fields) < 2:
                        continue
                    # 第 1 列是 local_address，形如 "0100007F:1F90"（端口是十六进制）
                    _, _, port_hex = fields[1].rpartition(":")
                    try:
                        bound.add(int(port_hex, 16))
                    except ValueError:
                        continue
        except OSError:
            continue
    return bound


def _declared_bindings_host_ports(attrs: dict | None) -> set[int]:
    """HostConfig.PortBindings 里写死的宿主端口（显式绑定那一份）。

    ★ 它和 NetworkSettings.Ports 是**互补的两个盲区，缺一不可**（2026-09 实测）：

        | 容器             | HostConfig.PortBindings | NetworkSettings.Ports |
        | 显式绑定·运行中   | "20000"                 | "20000"               |
        | 显式绑定·**已停止** | "20000"               | **{} 空**             |
        | `-P` 建的·运行中  | **"" 空**               | "32779"               |

      只看 NetworkSettings 会漏掉**已停止**的容器：docker 停容器时把网络拆了，那个号在
      attrs 里就没了，但它仍然占着——`docker start` 时会要回同一个号。只看 HostConfig 会
      漏掉所有 `-P` 建的容器。两个都读，空串直接跳过。
    """
    bindings = ((attrs or {}).get("HostConfig") or {}).get("PortBindings") or {}
    host_ports: set[int] = set()
    for entries in bindings.values():
        for entry in entries or []:
            raw = (entry or {}).get("HostPort")
            if not raw:  # `-P` 的占位是空串：号由 daemon 另给，见 NetworkSettings
                continue
            try:
                host_ports.add(int(raw))
            except (TypeError, ValueError):
                continue
    return host_ports


def _docker_published_ports(client) -> set[int]:
    """docker 已占用的宿主端口，**含已停止的容器**——停容器没被删，号还是它的。

    两份来源取并集，理由见 _declared_bindings_host_ports。docker-py 的 `containers.list()`
    默认非 sparse，返回的就是 inspect 形态的 attrs，可以直接喂给 extract_port_info。

    这里**不吞异常**：docker 都问不到的时候，瞎选一个号可能正是某个停止容器占着的那一个，
    而它此刻并不在宿主 /proc 里——那就等于把漂移重新放回来。
    """
    published: set[int] = set()
    for container in client.containers.list(all=True):
        attrs = getattr(container, "attrs", None)
        _, mappings = extract_port_info(attrs)
        for mapping in mappings:
            published.add(int(mapping["host_port"]))
        published |= _declared_bindings_host_ports(attrs)
    return published


def occupied_host_ports(client=None) -> set[int]:
    """必须避开的宿主端口 = docker 已发布 ∪ 宿主系统已绑定。"""
    if client is None:
        from .. import extensions

        if extensions.docker_client is None:
            extensions.init_docker()
        client = extensions.docker_client
    return _docker_published_ports(client) | _system_bound_ports()


def _pick_free_ports(count: int, taken: set[int], start: int, end: int) -> list[int] | None:
    """从 start 顺着环取 count 个空闲端口；走满一圈仍不够则 None。

    顺序取号而不是真随机：可预测的分配让"哪个容器拿了哪几个号"肉眼可查，机器之间的
    防火墙规则也好写。
    """
    size = end - start + 1
    if count > size:
        return None
    picks: list[int] = []
    for offset in range(size):
        candidate = start + offset
        if candidate in taken:
            continue
        picks.append(candidate)
        if len(picks) == count:
            return picks
    return None


def allocate_ports(
    container_ports,
    *,
    client=None,
    exclude=(),
) -> dict[str, int]:
    """为一整个容器分配一组宿主端口：`["22/tcp", "8080/tcp"] -> {"22/tcp": 20000, ...}`。

    ★ 单位是"一个容器的一组"，不是单个端口：锁、占用快照、以及调用方的重试都以容器为
      单位，这样不会留下半分配的结果（重试时整组重来，不做单端口修补）。

    `exclude` 是调用方已知的坏号（上一次绑定被 docker 拒掉的那几个），只在本次分配内叠加，
    不落盘——所以它不会成为第二份会漂移的状态。
    """
    wanted = sorted(container_ports, key=_spec_sort_key)
    if not wanted:
        return {}

    start = int(PortConfig.NODE_PORT_RANGE_START)
    end = int(PortConfig.NODE_PORT_RANGE_END)
    if end < start:
        raise RuntimeError(f"invalid host port range: {start}-{end}")

    excluded = {int(p) for p in exclude}

    with _allocation_lock:
        try:
            taken = occupied_host_ports(client) | excluded
        except Exception as e:
            # **问不到 docker 就不能瞎选**：某个停止容器占着的号此刻并不在宿主 /proc 里，
            # 盲选出来的号 docker 会痛快地绑上（宿主层面它确实空着），直到那个容器被启动时
            # 才炸——错误会推迟、并且落到别人身上。宁可在这里立刻、明确地失败。
            raise RuntimeError(
                f"cannot read the host ports docker already published; refusing to "
                f"allocate blind (a stopped container holds its port without appearing "
                f"in /proc): {e}"
            ) from e
        picks = _pick_free_ports(len(wanted), taken, start, end)

    if picks is None:
        raise PortRangeExhausted(
            f"no {len(wanted)} free host port(s) in {start}-{end}: "
            f"{len(taken)} port(s) already occupied on this host "
            f"(delete unused containers to release their ports)"
        )

    return dict(zip(wanted, picks))
