"""Test doubles for mount cleanup process and launcher seams."""

from __future__ import annotations

import subprocess
import threading


class FakeProcess:
    def __init__(
        self,
        command=None,
        *,
        returncode=0,
        stdout="",
        stderr="",
        block=False,
        on_communicate=None,
    ):
        self.command = list(command or [])
        self.pid = 424242
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = None if block else returncode
        self.returncode_after_wait = returncode
        self.terminated = False
        self.killed = False
        self.communicate_timeouts = []
        self.on_communicate = on_communicate
        self._done = threading.Event()
        if not block:
            self._done.set()

    def communicate(self, timeout=None):
        self.communicate_timeouts.append(timeout)
        if self.on_communicate is not None:
            self.on_communicate(self)
        if timeout is None:
            self._done.wait()
        elif not self._done.wait(timeout):
            raise subprocess.TimeoutExpired(self.command or ["rm"], timeout)
        self.returncode = self.returncode_after_wait
        return self.stdout, self.stderr

    def finish(self, returncode: int = 0) -> None:
        self.returncode_after_wait = returncode
        self.returncode = returncode
        self._done.set()

    def terminate(self):
        self.terminated = True
        self.returncode = -15
        self._done.set()

    def kill(self):
        self.killed = True
        self.returncode = -9
        self._done.set()

    def poll(self):
        return self.returncode if self._done.is_set() else None

    def wait(self, timeout=None):
        if timeout is None:
            self._done.wait()
        elif not self._done.wait(timeout):
            raise subprocess.TimeoutExpired(self.command or ["rm"], timeout)
        return self.returncode


class FakeProcessFactory:
    def __init__(self, **process_kwargs):
        self.default_kwargs = dict(process_kwargs)
        self.calls = []
        self.processes = []

    def __call__(self, command, **kwargs):
        self.calls.append({"command": list(command), "kwargs": dict(kwargs)})
        process = FakeProcess(command, **self.default_kwargs)
        self.processes.append(process)
        return process


def wait_until(predicate, timeout=3.0, interval=0.01):
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return predicate()
