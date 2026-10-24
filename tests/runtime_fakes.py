"""Node runtime/state tests 的可编程 Docker 替身与交错屏障。

只替换 Docker 边界，不替换被测的 status_cache/服务层/HTTP/WSS 入口。
"""
from __future__ import annotations

import threading

import docker

from FuxiYu_NodeKernel import extensions


def not_found(name: str = "ghost") -> docker.errors.NotFound:
    class _Resp:
        status_code = 404
        content = b"not found"
        url = f"http://docker/containers/{name}"
        reason = "Not Found"

    return docker.errors.NotFound(f"no such container: {name}", response=_Resp())


class Trace:
    """确定性交错日志：记录标签、线程名与单调序号。"""

    def __init__(self):
        self.events = []
        self._lock = threading.Lock()

    def add(self, label: str):
        with self._lock:
            self.events.append((len(self.events), label, threading.current_thread().name))
            return self.events[-1]

    def labels(self):
        with self._lock:
            return [item[1] for item in self.events]

    def has(self, label: str) -> bool:
        return label in self.labels()

    def index(self, label: str) -> int:
        return self.labels().index(label)


class Barrier:
    """可注入屏障：wait() 阻塞到 release()；带超时防止永久挂死。"""

    def __init__(self):
        self.entered = threading.Event()
        self.released = threading.Event()
        self.calls = 0
        self._lock = threading.Lock()

    def wait(self, timeout: float = 5.0):
        with self._lock:
            self.calls += 1
        self.entered.set()
        if not self.released.wait(timeout):
            raise TimeoutError("barrier timeout")
        self.released.clear()

    def release(self):
        self.released.set()

    def wait_entered(self, timeout: float = 5.0):
        assert self.entered.wait(timeout), "barrier not entered"

    def reset(self):
        self.entered.clear()
        self.released.clear()
        self.calls = 0


class ExecResult:
    def __init__(self, exit_code: int = 0, output: bytes = b"ok"):
        self.exit_code = exit_code
        self.output = output

    def __getitem__(self, index: int):
        if index == 0:
            return self.exit_code
        raise IndexError(index)


class FakeRuntimeContainer:
    def __init__(
        self,
        name: str,
        *,
        status: str = "running",
        docker_id: str | None = None,
        started_at: str = "2026-10-17T19:00:00.000000000Z",
        pid: int = 4321,
        mounts: list | None = None,
        size_rw: int = 1024,
        paused: bool | None = None,
        restarting: bool = False,
        dead: bool = False,
        stats_payload: dict | None = None,
        exec_exit_code: int = 0,
    ):
        self.name = name
        self.id = docker_id or f"dockerid-{name}"
        self.status = status
        self._paused = status == "paused" if paused is None else paused
        self._restarting = restarting or status == "restarting"
        self._dead = dead or status == "dead"
        self._pid = pid
        self._started_at = started_at
        self._size_rw = size_rw
        self._stats_payload = stats_payload
        self._exec_exit_code = exec_exit_code
        self._mounts = list(mounts) if mounts is not None else [
            {"Type": "bind", "Destination": "/root", "Source": "/tmp/fake-root"}
        ]
        self.attrs = self._build_attrs()
        self.reload_calls = 0
        self.exec_calls = []
        self.remove_calls = 0
        self.start_calls = 0
        self.stop_calls = 0
        self.restart_calls = 0
        self.pause_calls = 0
        self.unpause_calls = 0
        self.remove_calls = 0
        self.on_reload = None
        self.on_start = None
        self.on_stop = None
        self.on_restart = None
        self.on_pause = None
        self.on_unpause = None
        self.raise_on_start = None
        self.raise_on_stop = None
        self.raise_on_restart = None
        self.raise_on_pause = None
        self.raise_on_unpause = None
        self.removed = False

    def _build_attrs(self):
        return {
            "Id": self.id,
            "State": {
                "Status": self.status,
                "Running": self.status == "running" or self._paused,
                "Paused": self._paused,
                "Restarting": self._restarting,
                "Dead": self._dead,
                "Pid": self._pid,
                "StartedAt": self._started_at,
                "OOMKilled": False,
                "ExitCode": 0,
                "Error": "",
            },
            "Mounts": list(self._mounts),
            "SizeRw": self._size_rw,
            "HostConfig": {"DeviceRequests": []},
            "NetworkSettings": {"Ports": {}},
        }

    def set_status(self, status: str, *, started_at: str | None = None):
        self.status = status
        if status == "running":
            self._paused = False
            self._restarting = False
            self._dead = False
        elif status == "paused":
            self._paused = True
        elif status == "restarting":
            self._restarting = True
        elif status == "dead":
            self._dead = True
        if started_at is not None:
            self._started_at = started_at
        self.attrs = self._build_attrs()

    def set_mounts(self, mounts: list):
        self._mounts = list(mounts)
        self.attrs = self._build_attrs()

    def reload(self):
        self.reload_calls += 1
        if self.on_reload is not None:
            self.on_reload(self)

    def start(self, *args, **kwargs):
        self.start_calls += 1
        if self.on_start is not None:
            self.on_start(self)
        if self.raise_on_start is not None:
            raise self.raise_on_start
        # 每次启动都是新的运行进程。
        self.set_status("running", started_at=f"2026-10-17T20:00:{self.start_calls:02d}.000000000Z")

    def stop(self, *args, **kwargs):
        self.stop_calls += 1
        if self.on_stop is not None:
            self.on_stop(self)
        if self.raise_on_stop is not None:
            raise self.raise_on_stop
        self.set_status("exited")

    def restart(self, *args, **kwargs):
        self.restart_calls += 1
        if self.on_restart is not None:
            self.on_restart(self)
        if self.raise_on_restart is not None:
            raise self.raise_on_restart
        self.set_status("running", started_at=f"2026-10-17T21:00:{self.restart_calls:02d}.000000000Z")

    def pause(self, *args, **kwargs):
        self.pause_calls += 1
        if self.on_pause is not None:
            self.on_pause(self)
        if self.raise_on_pause is not None:
            raise self.raise_on_pause
        self.set_status("paused")

    def unpause(self, *args, **kwargs):
        self.unpause_calls += 1
        if self.on_unpause is not None:
            self.on_unpause(self)
        if self.raise_on_unpause is not None:
            raise self.raise_on_unpause
        self.set_status("running")

    def remove(self, *args, **kwargs):
        self.remove_calls += 1
        self.removed = True

    def exec_run(self, cmd, **kwargs):
        self.exec_calls.append((cmd, kwargs))
        return ExecResult(self._exec_exit_code)

    def stats(self, **kwargs):
        if self._stats_payload is None:
            raise RuntimeError("stats not available")
        return self._stats_payload


class FakeRuntimeContainers:
    def __init__(self, containers: list[FakeRuntimeContainer] | None = None):
        self._containers = list(containers or [])
        self.get_calls = []
        self.list_calls = 0
        self.get_barrier = None
        self.after_get = None

    def add(self, container: FakeRuntimeContainer):
        self._containers.append(container)
        return container

    def remove(self, name: str):
        self._containers = [c for c in self._containers if c.name != name]

    def get(self, name_or_id):
        self.get_calls.append(name_or_id)
        if self.get_barrier is not None:
            self.get_barrier.wait()
        for container in self._containers:
            if container.name == name_or_id or container.id == name_or_id:
                if self.after_get is not None:
                    self.after_get(container)
                return container
        raise not_found(str(name_or_id))

    def list(self, *args, **kwargs):
        self.list_calls += 1
        return list(self._containers)


class FakeRuntimeClient:
    def __init__(self, containers: list[FakeRuntimeContainer] | None = None):
        self.containers = FakeRuntimeContainers(containers)
        self.events_calls = []

    def events(self, **kwargs):
        self.events_calls.append(kwargs)
        return iter(())


def install_runtime(monkeypatch, containers: list[FakeRuntimeContainer] | None = None) -> FakeRuntimeClient:
    client = FakeRuntimeClient(containers)
    monkeypatch.setattr(extensions, "docker_client", client)
    return client


def install_disk_client(monkeypatch, containers: list[FakeRuntimeContainer] | None = None) -> FakeRuntimeClient:
    return install_runtime(monkeypatch, containers)
