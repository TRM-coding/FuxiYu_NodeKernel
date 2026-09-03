"""NodeKernel 测试共享基础设施。

- 密钥路径从 CWD 相对改为仓库绝对路径（任意目录跑测试都稳）
- FakeDockerClient：默认测试集不依赖 docker daemon
- encrypted_body：用真实密钥构造 Node 侧 wire 格式请求体

WSS 迁移说明：加密/签名属于消息层协议，与传输层（HTTP / WSS）无关，
本文件提供的辅助函数届时原样复用。
"""
import base64
import json
from pathlib import Path

import pytest
import docker as docker_pkg

NODE_ROOT = Path(__file__).resolve().parents[1]

from FuxiYu_NodeKernel.utils import CheckKeys as node_ck  # noqa: E402
from FuxiYu_NodeKernel.utils.CheckKeys import KeyConfig  # noqa: E402


def configure_absolute_key_paths(monkeypatch) -> None:
    """把 CheckKeys 的密钥路径从 CWD 相对改为仓库绝对路径。"""
    monkeypatch.setattr(KeyConfig, "PRIVATE_KEY_PATH", str(NODE_ROOT / "private_A.pem"))
    monkeypatch.setattr(KeyConfig, "PUBLIC_KEY_PATH", str(NODE_ROOT / "public_A.pem"))
    monkeypatch.setattr(KeyConfig, "PUBLIC_KEY_CONTROL", str(NODE_ROOT / "public_A.pem"))


def docker_not_found() -> docker_pkg.errors.NotFound:
    """构造可打印（__str__ 安全）的 docker NotFound。"""

    class _Resp:
        status_code = 404
        content = b"not found"
        url = "http://docker/containers/ghost"
        reason = "Not Found"

    return docker_pkg.errors.NotFound("no such container", response=_Resp())


class FakeContainer:
    """可编程的 docker container 假实现。"""

    def __init__(self, name: str = "c1", status: str = "running", exec_exit_code: int = 0):
        self.name = name
        self.id = f"fakeid_{name}"
        self.status = status
        self.attrs = {"State": {"Status": status}}
        self._exit_code = exec_exit_code
        self.exec_calls = []

    def reload(self) -> None:
        pass

    def remove(self, *a, **k) -> None:
        pass

    def stop(self, *a, **k) -> None:
        pass

    def exec_run(self, cmd, **kw):
        self.exec_calls.append((cmd, kw))

        class _Result:
            def __init__(self, code: int):
                self.exit_code = code
                self.output = b"ok"

            # docker SDK 老式用法 r[0] == exit_code；生产代码里 getattr(r, 'exit_code', r[0])
            # 会急切求值默认值，所以假实现必须支持下标
            def __getitem__(self, idx: int):
                if idx == 0:
                    return self.exit_code
                raise IndexError(idx)

        return _Result(self._exit_code)


class FakeContainers:
    def __init__(self, existing=None):
        self._existing = list(existing or [])

    def get(self, name_or_id):
        for c in self._existing:
            if c.name == name_or_id or c.id == name_or_id:
                return c
        raise docker_not_found()

    def list(self, *a, **k):
        return list(self._existing)

    def run(self, *a, **k):
        return FakeContainer(name=k.get("name", "c1"))


class FakeDockerClient:
    def __init__(self, containers=None):
        self.containers = containers or FakeContainers()


def encrypted_body(payload: dict) -> dict:
    """用真实密钥构造 Node 侧 wire 格式请求体 {"message": b64, "signature": b64}。"""
    raw = json.dumps(payload)
    return {
        "message": base64.b64encode(node_ck.encryption(raw)).decode(),
        "signature": base64.b64encode(node_ck.signature(raw)).decode(),
    }


@pytest.fixture()
def key_paths(monkeypatch):
    configure_absolute_key_paths(monkeypatch)
