"""Test doubles for mount cleanup process and launcher seams."""

from __future__ import annotations

import os
import subprocess
import threading
import time


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
        self.condition = threading.Condition()

    def __call__(self, command, **kwargs):
        process = FakeProcess(command, **self.default_kwargs)
        with self.condition:
            self.calls.append({"command": list(command), "kwargs": dict(kwargs)})
            self.processes.append(process)
            self.condition.notify_all()
        return process


def wait_until(predicate, timeout=3.0, interval=0.01):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return predicate()


def wait_for_process(factory, index=0, timeout=3.0):
    """Event-wait until an accepted async cleanup has spawned its fake process."""

    deadline = time.monotonic() + timeout
    with factory.condition:
        while len(factory.processes) <= index:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            factory.condition.wait(remaining)
        assert len(factory.processes) > index, (
            f"cleanup process {index} was not spawned; calls={factory.calls!r}"
        )
        return factory.processes[index]


def wait_for_process_for_path(factory, path, timeout=3.0):
    """Wait for the fake process whose direct rm argv targets ``path``."""

    target = os.path.realpath(str(path))
    deadline = time.monotonic() + timeout
    with factory.condition:
        while True:
            matches = [
                process
                for process in factory.processes
                if process.command
                and os.path.realpath(str(process.command[-1])) == target
            ]
            if len(matches) == 1:
                return matches[0]
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            factory.condition.wait(remaining)
        raise AssertionError(
            f"cleanup process for {target!r} was not uniquely spawned; "
            f"calls={factory.calls!r}"
        )
