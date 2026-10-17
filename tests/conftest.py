"""NodeKernel 测试共享基础设施。

- 密钥路径从 CWD 相对改为仓库绝对路径（任意目录跑测试都稳）
- FakeDockerClient：默认测试集不依赖 docker daemon
- encrypted_body：用真实密钥构造 Node 侧 wire 格式请求体

WSS 迁移说明：加密/签名属于消息层协议，与传输层（HTTP / WSS）无关，
本文件提供的辅助函数届时原样复用。
"""
from pathlib import Path

import pytest
import docker as docker_pkg

NODE_ROOT = Path(__file__).resolve().parents[1]


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
        self.removed = False

    def reload(self) -> None:
        pass

    def remove(self, *a, **k) -> None:
        self.removed = True

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
        self.run_calls = []

    def get(self, name_or_id):
        for c in self._existing:
            if c.name == name_or_id or c.id == name_or_id:
                return c
        raise docker_not_found()

    def list(self, *a, **k):
        return list(self._existing)

    def run(self, *a, **k):
        self.run_calls.append((a, k))
        return FakeContainer(name=k.get("name", "c1"))


class FakeImage:
    """docker image 假实现：分配器只读 `attrs.Config.ExposedPorts`。"""

    def __init__(self, exposed=None, tag: str = "fake:latest"):
        default = {"22/tcp": {}}
        self.tag = tag
        self.attrs = {"Config": {"ExposedPorts": dict(default if exposed is None else exposed)}}


class FakeImages:
    def __init__(self, exposed=None, missing: bool = False):
        self.exposed = exposed
        self.missing = missing
        self.pulled = []

    def get(self, tag):
        if self.missing:
            raise docker_pkg.errors.ImageNotFound("no such image")
        return FakeImage(self.exposed, tag)

    def pull(self, tag):
        self.pulled.append(tag)
        self.missing = False
        return FakeImage(self.exposed, tag)


class FakeDockerClient:
    def __init__(self, containers=None, images=None):
        self.containers = containers or FakeContainers()
        self.images = images or FakeImages()


def encrypted_body(payload: dict) -> dict:
    """check_keys 信封已退役：直接返回明文 payload（Node FastAPI 端点收 Pydantic）。"""
    return payload


@pytest.fixture()
def key_paths(monkeypatch):
    """check_keys 已退役：空 fixture 占位（保留签名，避免调用方改动）。"""
    pass
