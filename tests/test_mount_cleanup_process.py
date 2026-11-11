from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from FuxiYu_NodeKernel import create_app, extensions
from FuxiYu_NodeKernel.services.mount_cleanup import (
    MountCleanupManager,
    MountCleanupShutdown,
)

from .mount_cleanup_fakes import FakeProcessFactory, wait_for_process, wait_until


def _env(tmp_path, monkeypatch, *, process_kwargs=None, factory=None):
    base = tmp_path / "containers-root"
    base.mkdir()
    path = base / "alice" / "containers" / "c1"
    path.mkdir(parents=True)
    monkeypatch.setenv("NODE_CONTAINERS_BASE", str(base))
    factory = factory or FakeProcessFactory(**(process_kwargs or {}))
    manager = MountCleanupManager(
        use_launcher=False,
        rm_path="rm",
        process_factory=factory,
    )
    monkeypatch.setattr(extensions, "mount_cleanup", manager)
    return path, factory, manager


def _wait(manager, task_id, state, timeout=3.0):
    assert wait_until(lambda: (manager.get_status(task_id) or {}).get("state") == state, timeout)
    return manager.get_status(task_id)


def test_exit_zero_marks_succeeded(tmp_path, monkeypatch):
    path, factory, manager = _env(tmp_path, monkeypatch)
    task_id = manager.start_cleanup(path)

    status = _wait(manager, task_id, "succeeded")

    assert status["error_reason"] is None
    assert factory.processes


def test_rm_uses_argument_list_without_shell(tmp_path, monkeypatch):
    path, factory, manager = _env(tmp_path, monkeypatch)
    task_id = manager.start_cleanup(path)
    _wait(manager, task_id, "succeeded")

    call = factory.calls[0]
    assert call["command"][0] == "rm"
    assert call["command"][1:] == ["-rf", os.path.realpath(str(path))]
    assert "shell" not in call["kwargs"]


def test_nonzero_exit_marks_failed_with_rm_failed(tmp_path, monkeypatch):
    path, factory, manager = _env(
        tmp_path,
        monkeypatch,
        process_kwargs={"returncode": 1, "stderr": "secret rm stderr"},
    )
    task_id = manager.start_cleanup(path)

    status = _wait(manager, task_id, "failed")

    assert status["error_reason"] == "rm_failed"
    assert "secret rm stderr" not in str(status)


def test_slow_rm_stays_running_without_fixed_timeout(tmp_path, monkeypatch):
    path, factory, manager = _env(tmp_path, monkeypatch, process_kwargs={"block": True})
    task_id = manager.start_cleanup(path)
    process = wait_for_process(factory)

    assert wait_until(lambda: bool(process.communicate_timeouts))
    assert process.communicate_timeouts == [None]
    assert process.terminated is False
    assert manager.get_status(task_id)["state"] == "running"

    process.finish(0)
    _wait(manager, task_id, "succeeded")


def test_spawn_or_worker_exception_marks_internal_error(tmp_path, monkeypatch):
    path, _, manager = _env(tmp_path, monkeypatch)

    def failing_factory(command, **kwargs):
        raise OSError("rm unavailable")

    manager._process_factory = failing_factory
    task_id = manager.start_cleanup(path)

    status = _wait(manager, task_id, "failed")
    assert status["error_reason"] == "internal_error"


def test_partial_deletion_after_failure_is_not_success(tmp_path, monkeypatch):
    path, factory, manager = _env(tmp_path, monkeypatch)
    first = path / "first.txt"
    second = path / "second.txt"
    first.write_text("one", encoding="utf-8")
    second.write_text("two", encoding="utf-8")

    def delete_one(_process):
        first.unlink()

    factory.default_kwargs.update({"returncode": 1, "on_communicate": delete_one})
    task_id = manager.start_cleanup(path)

    status = _wait(manager, task_id, "failed")

    assert status["error_reason"] == "rm_failed"
    assert not first.exists()
    assert second.exists()


def test_shutdown_terminates_children_and_marks_shutdown(tmp_path, monkeypatch):
    path, factory, manager = _env(tmp_path, monkeypatch, process_kwargs={"block": True})
    task_id = manager.start_cleanup(path)
    process = wait_for_process(factory)

    manager.stop()

    assert process.terminated is True
    assert manager.get_status(task_id) == {
        "task_id": task_id,
        "state": "failed",
        "error_reason": "shutdown",
    }
    assert process.poll() is not None


def test_shutdown_rejects_new_cleanup_and_restore(tmp_path, monkeypatch):
    path, factory, manager = _env(tmp_path, monkeypatch)
    manager.stop()

    with pytest.raises(MountCleanupShutdown):
        manager.start_cleanup(path)
    with pytest.raises(MountCleanupShutdown):
        manager.reserve_restore(path)
    with pytest.raises(MountCleanupShutdown):
        manager.clean_sync(path)
    assert factory.calls == []


def test_api_start_reports_thread_start_failure(tmp_path, monkeypatch):
    path, factory, manager = _env(tmp_path, monkeypatch)

    class BrokenThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            raise RuntimeError("thread failed")

    monkeypatch.setattr(manager, "_thread_factory", BrokenThread)
    client = TestClient(create_app())

    response = client.post(
        "/api/start_clean_mount",
        json={"config": {"mount_path": str(path)}},
    )

    assert response.status_code == 500
    assert response.json()["error_reason"] == "background_thread_failed"
    assert manager._tasks == {}
    assert manager._active == {}
    assert factory.calls == []


def test_app_lifespan_shutdown_stops_running_cleanup(tmp_path, monkeypatch):
    path, factory, manager = _env(tmp_path, monkeypatch, process_kwargs={"block": True})
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/start_clean_mount",
            json={"config": {"mount_path": str(path)}},
        )
        task_id = response.json()["task_id"]
        process = wait_for_process(factory)

    status = manager.get_status(task_id)
    assert status["state"] == "failed"
    assert status["error_reason"] == "shutdown"
    assert process.terminated is True
