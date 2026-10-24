"""Password-change test doubles.

These fakes validate the Node-side contract: exec argv/stdin shape and
service decisions. They do not claim a real Docker daemon was exercised.
"""

from __future__ import annotations

from FuxiYu_NodeKernel import extensions

from .conftest import FakeContainer, FakeContainers, FakeDockerClient


class FakeExecSocket:
    def __init__(self):
        self.sent = b""
        self.closed = False
        self.write_shutdown = False

    def settimeout(self, _timeout):
        pass

    def sendall(self, data):
        self.sent += data

    def shutdown(self, _how):
        self.write_shutdown = True

    def recv(self, _size):
        return b""

    def close(self):
        self.closed = True


class FakeExecAPI:
    def __init__(self, exit_code: int = 0):
        self.exit_code = exit_code
        self.created = []
        self.started = []
        self.inspected = []
        self.sockets = {}

    def exec_create(self, container_id, cmd, **kwargs):
        exec_id = f"exec-{len(self.created)}"
        self.created.append({"container_id": container_id, "cmd": cmd, "kwargs": kwargs, "id": exec_id})
        return {"Id": exec_id}

    def exec_start(self, exec_id, **kwargs):
        sock = FakeExecSocket()
        self.started.append({"id": exec_id, "kwargs": kwargs, "socket": sock})
        self.sockets[exec_id] = sock
        return sock

    def exec_inspect(self, exec_id):
        self.inspected.append(exec_id)
        return {"ExitCode": self.exit_code, "Running": False}


class PasswordFakeDockerClient(FakeDockerClient):
    def __init__(self, containers=None, images=None, exit_code: int = 0):
        super().__init__(containers=containers, images=images)
        self.api = FakeExecAPI(exit_code=exit_code)


class PasswordFakeContainer(FakeContainer):
    """Fake container with per-command exit codes for id/useradd/group paths."""

    def __init__(self, name: str = "c1", *, user_exists: bool = False, **kwargs):
        super().__init__(name=name, **kwargs)
        self.user_exists = user_exists
        self.command_codes = {}

    def result(self, code: int):
        class _Result:
            def __init__(self, exit_code: int):
                self.exit_code = exit_code
                self.output = b"ok"

            def __getitem__(self, idx: int):
                if idx == 0:
                    return self.exit_code
                raise IndexError(idx)

        return _Result(code)

    def exec_run(self, cmd, **kw):
        self.exec_calls.append((cmd, kw))
        text = cmd[-1] if isinstance(cmd, (list, tuple)) and cmd else str(cmd)
        for marker, code in self.command_codes.items():
            if marker in text:
                return self.result(code)
        if "id -u" in text and "useradd" not in text:
            return self.result(0 if self.user_exists else 1)
        return self.result(self._exit_code)


def install_password_docker(monkeypatch, container: PasswordFakeContainer, *, exit_code: int = 0):
    client = PasswordFakeDockerClient(
        FakeContainers([container]),
        exit_code=exit_code,
    )
    monkeypatch.setattr(extensions, "docker_client", client)
    return client
