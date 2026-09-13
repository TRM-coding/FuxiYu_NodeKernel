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


class KeyConfig:
    PUBLIC_KEY_PATH='public_A.pem'
    PRIVATE_KEY_PATH='private_A.pem'
    PUBLIC_KEY_CONTROL='public_control.pem'


class AppConfig(KeyConfig):
    PUBLIC_KEY_PATH = os.getenv("PUBLIC_KEY_PATH", KeyConfig.PUBLIC_KEY_PATH)
    PRIVATE_KEY_PATH = os.getenv("PRIVATE_KEY_PATH", KeyConfig.PRIVATE_KEY_PATH)
    SECRET_KEY = os.getenv("SECRET_KEY", "dev")

class NodeProxyConfig(AppConfig):
    # 代理服务器配置
    PROXY_HOST = os.getenv("PROXY_HOST", "http://202.205.102.121:8091")


def get_config(env: str | None = None):
    """
    返回用于 Flask app.config.from_object 的配置类。
    目前仅提供单一配置，如需可根据 env 扩展。
    """
    return AppConfig


