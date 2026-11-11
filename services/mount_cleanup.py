"""Process-local mount cleanup task registry and executor.

The registry owns the Node-only path lock shared by asynchronous cleanup, the
legacy synchronous endpoint and restore admission. It also owns the bounded
task table and the launcher/rm child processes. No state is persisted.
"""

from __future__ import annotations

import collections
import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal

logger = logging.getLogger(__name__)

CleanupState = Literal["running", "succeeded", "failed"]

TERMINAL_TASK_LIMIT = 64
TERMINAL_TASK_TTL_SECONDS = 600.0
SYNC_CLEANUP_TIMEOUT_SECONDS = 30.0
SHUTDOWN_GRACE_SECONDS = 2.0
_SIGKILL = getattr(signal, "SIGKILL", None)


class MountPathError(ValueError):
    """The requested path is outside the cleanup whitelist."""


class MountPathBusy(RuntimeError):
    """The normalized path already has an active cleanup or restore reservation."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class MountCleanupShutdown(RuntimeError):
    """The manager is shutting down and refuses new work."""


class MountTaskStartError(RuntimeError):
    """A task record was prepared but its worker could not be started."""


@dataclass
class MountTask:
    task_id: str
    path: str
    key: str
    state: CleanupState = "running"
    error_reason: str | None = None
    created_monotonic: float = field(default_factory=time.monotonic)
    finished_monotonic: float | None = None


@dataclass(frozen=True)
class RestoreReservation:
    token: str
    real_path: str
    key: str


@dataclass
class _ActivePath:
    kind: Literal["cleanup", "restore"]
    token: str
    task_id: str | None = None


def _containers_base() -> str:
    return os.getenv("NODE_CONTAINERS_BASE", "/home")


def _path_key(real_path: str) -> str:
    return os.path.normcase(real_path)


def canonicalize_mount_path(
    mount_path: str,
    *,
    require_directory: bool = False,
) -> tuple[str, str]:
    """Return ``(realpath, normcase key)`` using the Node cleanup whitelist."""

    if isinstance(mount_path, os.PathLike):
        mount_path = os.fspath(mount_path)
    if not isinstance(mount_path, str) or not mount_path.strip():
        raise MountPathError("invalid mount_path")
    if "\x00" in mount_path:
        raise MountPathError("invalid mount_path")

    base = os.path.realpath(_containers_base())
    real = os.path.realpath(mount_path)
    base_key = _path_key(base)
    real_key = _path_key(real)
    base_prefix = base_key.rstrip("/\\") + os.sep

    if real_key == base_key or not real_key.startswith(base_prefix):
        raise MountPathError("invalid mount_path")

    parts = [part.lower() for part in os.path.normpath(real).split(os.sep)]
    if "containers" not in parts:
        raise MountPathError("invalid mount_path")

    if require_directory and not os.path.isdir(real):
        raise MountPathError("invalid mount_path")

    return real, real_key


def _bounded_command_output(text: str | None, *, limit: int = 10, max_chars: int = 1000) -> str:
    lines = [line for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return ""
    body = "\n".join(lines[:limit])[:max_chars]
    if len(lines) > limit:
        body += f"\n…（其余 {len(lines) - limit} 行已省略）"
    return body


def _format_rm_failure(path: str, returncode: int, stdout: str | None, stderr: str | None) -> str:
    detail = _bounded_command_output(stderr) or _bounded_command_output(stdout)
    suffix = f"\n--- rm output ---\n{detail}" if detail else ""
    return f"rm -rf failed (rc={returncode}): {path}{suffix}"


class MountCleanupManager:
    """One per Node process; all operations are guarded by one RLock."""

    def __init__(
        self,
        *,
        rm_path: str | None = None,
        process_factory: Callable[..., subprocess.Popen] | None = None,
        thread_factory: Callable[..., threading.Thread] | None = None,
        use_launcher: bool = True,
        launcher_path: str | os.PathLike[str] | None = None,
        terminal_limit: int = TERMINAL_TASK_LIMIT,
        terminal_ttl: float = TERMINAL_TASK_TTL_SECONDS,
        sync_timeout: float = SYNC_CLEANUP_TIMEOUT_SECONDS,
        shutdown_grace: float = SHUTDOWN_GRACE_SECONDS,
    ) -> None:
        self.node_epoch = uuid.uuid4().hex
        self._lock = threading.RLock()
        self._processes_done = threading.Condition(self._lock)
        self._tasks: collections.OrderedDict[str, MountTask] = collections.OrderedDict()
        self._active: dict[str, _ActivePath] = {}
        self._restore_tokens: dict[str, str] = {}
        self._processes: dict[str, subprocess.Popen] = {}
        self._accepting = True
        self._closed = False
        self._seq = 0

        self._rm_path = rm_path if rm_path is not None else shutil.which("rm")
        self._process_factory = process_factory or subprocess.Popen
        self._thread_factory = thread_factory or threading.Thread
        self._use_launcher = use_launcher
        self._launcher_path = (
            Path(launcher_path)
            if launcher_path
            else Path(__file__).resolve().parent / "mount_modules" / "cleanup_launcher.py"
        )
        self._terminal_limit = int(terminal_limit)
        self._terminal_ttl = float(terminal_ttl)
        self._sync_timeout = float(sync_timeout)
        self._shutdown_grace = float(shutdown_grace)

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        """Mark the service accepting work; called by app lifespan/create_app."""

        with self._lock:
            if self._closed:
                # A new application lifecycle in the same test process behaves
                # like a new Node process: old task ids and locks must not leak.
                self._tasks.clear()
                self._active.clear()
                self._restore_tokens.clear()
                self._processes.clear()
                self.node_epoch = uuid.uuid4().hex
                self._seq = 0
                self._closed = False
            self._accepting = True

    def stop(self) -> None:
        """Stop accepting work, terminate children and make running tasks fail."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._accepting = False
            for task in list(self._tasks.values()):
                if task.state == "running":
                    self._finish_locked(task.task_id, "failed", "shutdown")
            processes = list(self._processes.values())

        for process in processes:
            self._signal_process(process, signal.SIGTERM)
        self._wait_for_processes(self._shutdown_grace)

        with self._lock:
            remaining = list(self._processes.values())
        if remaining:
            for process in remaining:
                self._signal_process(process, _SIGKILL)
            self._wait_for_processes(self._shutdown_grace)

    def _wait_for_processes(self, timeout: float) -> None:
        deadline = time.monotonic() + max(0.0, timeout)
        with self._lock:
            while self._processes:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return
                self._processes_done.wait(remaining)

    # ------------------------------------------------------------------
    # status/task table
    # ------------------------------------------------------------------
    def get_status(self, task_id: str) -> dict | None:
        with self._lock:
            self._prune_locked()
            task = self._tasks.get(task_id)
            if task is None:
                return None
            return {
                "task_id": task.task_id,
                "state": task.state,
                "error_reason": task.error_reason,
            }

    def _prune_locked(self) -> None:
        now = time.monotonic()
        for task_id, task in list(self._tasks.items()):
            if task.state == "running":
                continue
            if task.finished_monotonic is None:
                continue
            if now - task.finished_monotonic > self._terminal_ttl:
                self._tasks.pop(task_id, None)

        terminal_ids = [
            task_id for task_id, task in self._tasks.items() if task.state != "running"
        ]
        while len(terminal_ids) > self._terminal_limit:
            self._tasks.pop(terminal_ids.pop(0), None)

    def _next_task_id_locked(self) -> str:
        self._seq += 1
        return f"{self.node_epoch}:{self._seq}"

    def _busy_for_active_locked(self, active: _ActivePath) -> MountPathBusy:
        reason = "cleanup_in_progress" if active.kind == "cleanup" else "restore_in_progress"
        return MountPathBusy(reason)

    def _finish_locked(self, task_id: str, state: Literal["succeeded", "failed"], reason: str | None) -> bool:
        task = self._tasks.get(task_id)
        if task is None or task.state != "running":
            return False
        task.state = state
        task.error_reason = reason
        task.finished_monotonic = time.monotonic()
        active = self._active.get(task.key)
        if active is not None and active.kind == "cleanup" and active.token == task_id:
            self._active.pop(task.key, None)
        self._prune_locked()
        return True

    # ------------------------------------------------------------------
    # cleanup admission
    # ------------------------------------------------------------------
    def start_cleanup(self, mount_path: str) -> str:
        with self._lock:
            if not self._accepting:
                raise MountCleanupShutdown("manager is shutting down")
            real_path, key = canonicalize_mount_path(mount_path)
            active = self._active.get(key)
            if active is not None:
                raise self._busy_for_active_locked(active)

            task_id = self._next_task_id_locked()
            self._tasks[task_id] = MountTask(task_id=task_id, path=real_path, key=key)
            self._active[key] = _ActivePath(kind="cleanup", token=task_id, task_id=task_id)

        try:
            thread = self._thread_factory(
                target=self._run_cleanup_task,
                args=(task_id,),
                name=f"mount-cleanup-{task_id}",
                daemon=True,
            )
            thread.start()
        except Exception:
            with self._lock:
                self._tasks.pop(task_id, None)
                active = self._active.get(key)
                if active is not None and active.token == task_id:
                    self._active.pop(key, None)
            raise MountTaskStartError("background_thread_failed")

        return task_id

    def _run_cleanup_task(self, task_id: str) -> None:
        process = None
        try:
            with self._lock:
                task = self._tasks.get(task_id)
                if task is None or task.state != "running":
                    return
                if not self._accepting:
                    self._finish_locked(task_id, "failed", "shutdown")
                    return
                process = self._spawn_cleanup_locked(task.path, task_id)

            stdout, stderr = process.communicate()
            returncode = process.returncode
            if returncode == 0:
                with self._lock:
                    self._finish_locked(task_id, "succeeded", None)
            else:
                detail = _bounded_command_output(stderr) or _bounded_command_output(stdout)
                logger.warning(
                    "mount cleanup failed: task_id=%s returncode=%s output=%s",
                    task_id,
                    returncode,
                    detail,
                )
                with self._lock:
                    self._finish_locked(task_id, "failed", "rm_failed")
        except Exception as exc:
            logger.warning("mount cleanup task failed: task_id=%s error=%s", task_id, exc)
            with self._lock:
                self._finish_locked(task_id, "failed", "internal_error")
        finally:
            with self._lock:
                self._processes.pop(task_id, None)
                self._processes_done.notify_all()

    def clean_sync(self, mount_path: str) -> bool:
        """Legacy synchronous cleanup: same lock, 30-second wait limit."""

        with self._lock:
            if not self._accepting:
                raise MountCleanupShutdown("manager is shutting down")
            real_path, key = canonicalize_mount_path(mount_path)
            active = self._active.get(key)
            if active is not None:
                raise self._busy_for_active_locked(active)

            token = uuid.uuid4().hex
            self._active[key] = _ActivePath(kind="cleanup", token=token)
            try:
                process = self._spawn_cleanup_locked(real_path, token)
            except Exception:
                self._active.pop(key, None)
                raise

        try:
            try:
                stdout, stderr = process.communicate(timeout=self._sync_timeout)
            except subprocess.TimeoutExpired:
                logger.warning("legacy clean_mount timed out: path=%s", real_path)
                self._terminate_and_reap(process)
                raise
            if process.returncode != 0:
                detail = _bounded_command_output(stderr) or _bounded_command_output(stdout)
                logger.warning(
                    "legacy clean_mount failed: path=%s returncode=%s output=%s",
                    real_path,
                    process.returncode,
                    detail,
                )
                raise RuntimeError(
                    _format_rm_failure(real_path, process.returncode, stdout, stderr)
                )
            return True
        finally:
            with self._lock:
                self._processes.pop(token, None)
                active = self._active.get(key)
                if active is not None and active.token == token:
                    self._active.pop(key, None)
                self._processes_done.notify_all()

    # ------------------------------------------------------------------
    # restore reservation
    # ------------------------------------------------------------------
    def reserve_restore(self, mount_path: str) -> RestoreReservation:
        with self._lock:
            if not self._accepting:
                raise MountCleanupShutdown("manager is shutting down")
            real_path, key = canonicalize_mount_path(mount_path, require_directory=True)
            active = self._active.get(key)
            if active is not None:
                raise self._busy_for_active_locked(active)

            token = uuid.uuid4().hex
            self._active[key] = _ActivePath(kind="restore", token=token)
            self._restore_tokens[token] = key
            return RestoreReservation(
                token=token,
                real_path=real_path,
                key=key,
            )

    def release_restore(self, token: str) -> None:
        with self._lock:
            key = self._restore_tokens.pop(token, None)
            if key is None:
                return
            active = self._active.get(key)
            if active is not None and active.kind == "restore" and active.token == token:
                self._active.pop(key, None)

    # ------------------------------------------------------------------
    # child process plumbing
    # ------------------------------------------------------------------
    def _spawn_cleanup_locked(self, real_path: str, token: str) -> subprocess.Popen:
        if not self._rm_path:
            raise RuntimeError("rm executable is unavailable")
        if self._use_launcher:
            command = [
                sys.executable,
                str(self._launcher_path),
                "--parent-pid",
                str(os.getpid()),
                "--rm-path",
                str(self._rm_path),
                "--path",
                real_path,
            ]
        else:
            command = [str(self._rm_path), "-rf", real_path]

        kwargs = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "errors": "replace",
        }
        if os.name == "posix":
            kwargs["start_new_session"] = True
        else:
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            if creationflags:
                kwargs["creationflags"] = creationflags

        process = self._process_factory(command, **kwargs)
        self._processes[token] = process
        return process

    def _signal_process(self, process: subprocess.Popen, sig: int) -> None:
        if process.poll() is not None:
            return
        if os.name == "posix":
            try:
                os.killpg(os.getpgid(process.pid), sig)
                return
            except (ProcessLookupError, PermissionError):
                pass
            except Exception:
                pass
        try:
            if sig is None or (_SIGKILL is not None and sig == _SIGKILL):
                process.kill()
            else:
                process.terminate()
        except Exception:
            pass

    def _terminate_and_reap(self, process: subprocess.Popen) -> None:
        self._signal_process(process, signal.SIGTERM)
        try:
            process.communicate(timeout=self._shutdown_grace)
            return
        except subprocess.TimeoutExpired:
            pass
        except Exception:
            pass
        self._signal_process(process, _SIGKILL)
        try:
            process.communicate(timeout=self._shutdown_grace)
        except Exception:
            try:
                process.wait(timeout=self._shutdown_grace)
            except Exception:
                pass
