"""端口映射的提取（唯一实现，采集侧与创建侧共用）。

★ 为什么每轮都要**从 attrs 重算**，而不是沿用创建时那份：端口是 docker 的事实。
容器重建、映射变化之后，创建那一刻的快照就是错的——而快照每轮推给 Ctrl 会把它写回库，
于是"库里按 docker 事实手改的值"永远留不住（2026-09 实测）。

★ 为什么必须**去重**：docker 为一个已发布端口会返回两条 binding —— IPv4 的 `0.0.0.0`
与 IPv6 的 `::`，端口号完全相同：

    {"22/tcp": [{"HostIp": "0.0.0.0", "HostPort": "32776"},
                {"HostIp": "::",      "HostPort": "32776"}]}

逐条摊平就会得到两条一模一样的记录（2026-09 实测：22 / 50000 / 8080 每个都出现两次，
而映射结构里没有 host_ip 字段，两条连区分都区分不出来）。
"""


def extract_port_info(attrs: dict | None) -> tuple[int | None, list[dict]]:
    """从 `container.attrs` 提取 (SSH 宿主机端口, 端口映射列表)。

    端口映射按 (container_port, host_port, protocol) 去重，顺序沿用 docker 返回的顺序。
    SSH 端口取 container_port=22 的第一条（没有就是 None）。
    """
    ports = ((attrs or {}).get("NetworkSettings") or {}).get("Ports") or {}
    mappings: list[dict] = []
    seen: set[tuple[int, int, str]] = set()
    ssh_port: int | None = None

    for key, bindings in ports.items():
        container_port_str, _, protocol = str(key).partition("/")
        protocol = protocol or "tcp"
        try:
            container_port = int(container_port_str)
        except (TypeError, ValueError):
            continue

        for binding in bindings or []:
            host_port_raw = (binding or {}).get("HostPort")
            if not host_port_raw:
                continue
            try:
                host_port = int(host_port_raw)
            except (TypeError, ValueError):
                continue

            token = (container_port, host_port, protocol)
            if token in seen:
                continue
            seen.add(token)
            mappings.append({
                "container_port": container_port,
                "host_port": host_port,
                "protocol": protocol,
            })
            if container_port == 22 and ssh_port is None:
                ssh_port = host_port

    return ssh_port, mappings
