"""应用配置模块

提供不同环境的配置类，支持通过环境变量覆盖默认值。
网络配置采用三仓库统一键名：只填裸 IP 与端口，其余自动组装。
"""

import os


def _env_int(name: str, default: int) -> int:
    """读取整数型环境变量，空值/非法值回退默认。"""
    raw = os.getenv(name, "")
    if raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


class NetConfig:
    """三仓库统一网络键名。分发时只改这几个值。

    Node 只监听自己的 NODE_PORT：快照由 Ctrl 主动拨 `/ws/ctrl` 取，
    Node 不需要（也不应该需要）知道 Ctrl 的地址。
    """
    NODE_PORT = _env_int("NODE_PORT", 5789)


class PortConfig:
    """容器宿主端口的分配段（Node 分配，实现在 docker_operates/port_allocator.py）。

    默认 20000–29999 的理由：

    - 内核 ephemeral 段是 32768–60999，docker 自己的 `-P` 也从 32768 附近起 ——
      避开它，就不跟出站连接抢号；
    - 避开 K8s NodePort 段 30000–32767；
    - 一万个够用：每容器约 2–3 个端口 ≈ 数千容器/机，远未到规模。

    ★ 宿主防火墙/上游只放行小段时，把它改小成实际可放行的区间（例如 20000–21999）——
      这是唯一无法在代码里自愈的一条，改完要重启 Node。
    """
    NODE_PORT_RANGE_START = _env_int("NODE_PORT_RANGE_START", 20000)
    NODE_PORT_RANGE_END = _env_int("NODE_PORT_RANGE_END", 29999)


class KeyConfig:
    PUBLIC_KEY_PATH='public_A.pem'
    PRIVATE_KEY_PATH='private_A.pem'
    PUBLIC_KEY_CONTROL='public_control.pem'


class AppConfig(KeyConfig):
    PUBLIC_KEY_PATH = os.getenv("PUBLIC_KEY_PATH", KeyConfig.PUBLIC_KEY_PATH)
    PRIVATE_KEY_PATH = os.getenv("PRIVATE_KEY_PATH", KeyConfig.PRIVATE_KEY_PATH)
    SECRET_KEY = os.getenv("SECRET_KEY", "dev")


# 这里曾有 NodeProxyConfig(PROXY_HOST=...)：一次没有接线的代理尝试——类建好了，
# 但全仓无人引用（`get_config()` 返回的是 AppConfig），而且把一个**部署环境的地址**
# 硬编码成了源码默认值。已删除（2026-09）。
#
# 代理这件事现在的落点：
#   - 配置来源：Node 的 .env 里的 HTTP_PROXY / HTTPS_PROXY / NO_PROXY（run.py 加载）
#   - 用途：`services/container_service._proxy_build_args` 把它透传成构建参数——
#     因为 daemon 级代理只覆盖拉取，进不了构建的 RUN 步骤（见该函数注释）


def get_config(env: str | None = None):
    """
    返回用于 Flask app.config.from_object 的配置类。
    目前仅提供单一配置，如需可根据 env 扩展。
    """
    return AppConfig


