from __future__ import annotations

import json
import os
import threading
import time

import pytest
from fastapi.testclient import TestClient

from FuxiYu_NodeKernel import create_app, extensions
from FuxiYu_NodeKernel.services.mount_cleanup import (
    MountCleanupManager,
    MountPathBusy,
)
from FuxiYu_NodeKernel.network import wss as wss_module

from .mount_cleanup_fakes import (
    FakeProcessFactory,
    wait_for_process,
    wait_for_process_for_path,
    wait_until,
)


def _make_env(tmp_path, monkeypatch, *, process_kwargs=None, **manager_kwargs):
    base = tmp_path / "containers-root"
    base.mkdir(exist_ok=True)
    path = base / "alice" / "containers" / "c1"
    path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("NODE_CONTAINERS_BASE", str(base))
    factory = FakeProcessFactory(**(process_kwargs or {}))
    manager = MountCleanupManager(
        use_launcher=False,
        rm_path="rm",
        process_factory=factory,
        **manager_kwargs,
    )
    monkeypatch.setattr(extensions, "mount_cleanup", manager)
    return base, path, factory, manager


def _client():
    return TestClient(create_app())


def _start(client, path):
    return client.post("/api/start_clean_mount", json={"config": {"mount_path": str(path)}})


def _status(client, task_id):
    return client.post(
        "/api/get_clean_mount_status",
        json={"config": {"task_id": task_id}},
    )


def _wait_task(manager, task_id, state, timeout=3.0):
    result = wait_until(
        lambda: (manager.get_status(task_id) or {}).get("state") == state,
        timeout=timeout,
    )
    assert result, manager.get_status(task_id)
    return manager.get_status(task_id)


def test_start_returns_acceptance_and_task_id(tmp_path, monkeypatch):
    _, path, factory, _ = _make_env(tmp_path, monkeypatch, process_kwargs={"block": True})
    client = _client()

    response = _start(client, path)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"success", "task_id"}
    assert body["success"] == 1
    assert isinstance(body["task_id"], str) and body["task_id"]
    assert "state" not in body
    assert "succeeded" not in body
    process = wait_for_process(factory)
    assert process.poll() is None, "受理响应不应等待清理进程完成"
    process.finish(0)


def test_status_reports_running_task(tmp_path, monkeypatch):
    _, path, factory, manager = _make_env(tmp_path, monkeypatch, process_kwargs={"block": True})
    client = _client()
    task_id = _start(client, path).json()["task_id"]

    body = _status(client, task_id).json()

    assert body == {
        "success": 1,
        "task_id": task_id,
        "state": "running",
        "error_reason": None,
    }
    wait_for_process(factory).finish(0)


def test_status_reports_running_then_terminal_sequence(tmp_path, monkeypatch):
    _, path, factory, manager = _make_env(tmp_path, monkeypatch, process_kwargs={"block": True})
    client = _client()
    task_id = _start(client, path).json()["task_id"]

    assert _status(client, task_id).json()["state"] == "running"
    wait_for_process(factory).finish(0)
    _wait_task(manager, task_id, "succeeded")
    body = _status(client, task_id).json()
    assert body["task_id"] == task_id
    assert body["state"] == "succeeded"
    assert body["error_reason"] is None


def test_status_reports_succeeded_task(tmp_path, monkeypatch):
    _, path, factory, manager = _make_env(tmp_path, monkeypatch)
    client = _client()
    task_id = _start(client, path).json()["task_id"]

    _wait_task(manager, task_id, "succeeded")
    response = _status(client, task_id)

    assert response.status_code == 200
    assert response.json() == {
        "success": 1,
        "task_id": task_id,
        "state": "succeeded",
        "error_reason": None,
    }


def test_status_failed_task_is_query_success(tmp_path, monkeypatch):
    _, path, factory, manager = _make_env(
        tmp_path,
        monkeypatch,
        process_kwargs={"returncode": 1, "stderr": "secret rm stderr"},
    )
    client = _client()
    task_id = _start(client, path).json()["task_id"]
    _wait_task(manager, task_id, "failed")

    response = _status(client, task_id)

    assert response.status_code == 200
    body = response.json()
    assert body["success"] == 1
    assert body["state"] == "failed"
    assert body["error_reason"] == "rm_failed"
    assert "secret rm stderr" not in response.text


def test_invalid_path_returns_400_without_task(tmp_path, monkeypatch):
    _, path, factory, manager = _make_env(tmp_path, monkeypatch)
    client = _client()

    response = _start(client, tmp_path / "outside" / "containers" / "x")

    assert response.status_code == 400
    assert response.json()["error_reason"] == "invalid_path"
    assert manager._tasks == {}
    assert factory.calls == []


def test_duplicate_cleanup_returns_409_with_one_spawn(tmp_path, monkeypatch):
    _, path, factory, _ = _make_env(tmp_path, monkeypatch, process_kwargs={"block": True})
    client = _client()
    first = _start(client, path)
    assert first.status_code == 200
    first_process = wait_for_process(factory)

    second = _start(client, path)

    assert second.status_code == 409
    assert second.json()["error_reason"] == "cleanup_in_progress"
    assert len(factory.processes) == 1
    first_process.finish(0)


def test_cleanup_conflicts_with_restore_reservation(tmp_path, monkeypatch):
    _, path, factory, manager = _make_env(tmp_path, monkeypatch)
    reservation = manager.reserve_restore(path)
    client = _client()

    response = _start(client, path)

    assert response.status_code == 409
    assert response.json()["error_reason"] == "restore_in_progress"
    assert factory.calls == []
    manager.release_restore(reservation.token)


def test_unknown_task_returns_404_not_success(tmp_path, monkeypatch):
    _, _, factory, manager = _make_env(tmp_path, monkeypatch)
    client = _client()

    body = _status(client, "does-not-exist").json()

    assert body == {"success": 0, "error": "task not found", "error_reason": "not_found"}
    assert factory.calls == []


def test_internal_failure_returns_500_not_success(tmp_path, monkeypatch):
    _, path, factory, manager = _make_env(tmp_path, monkeypatch)
    monkeypatch.setattr(manager, "start_cleanup", lambda path: (_ for _ in ()).throw(RuntimeError("boom")))
    client = _client()

    response = _start(client, path)

    assert response.status_code == 500
    assert response.json()["error_reason"] == "internal_error"
    assert factory.calls == []


def test_path_aliases_share_one_canonical_lock(tmp_path, monkeypatch):
    _, path, factory, _ = _make_env(tmp_path, monkeypatch, process_kwargs={"block": True})
    client = _client()
    first = _start(client, path)
    assert first.status_code == 200
    first_process = wait_for_process(factory)

    equivalent = path.parent / "." / "c1"
    second = _start(client, equivalent)
    assert second.status_code == 409
    assert second.json()["error_reason"] == "cleanup_in_progress"

    alias = path.parent / "c1-alias"
    try:
        os.symlink(path, alias, target_is_directory=True)
    except (OSError, NotImplementedError):
        alias = None
    if alias is not None:
        third = _start(client, alias)
        assert third.status_code == 409
        assert third.json()["error_reason"] == "cleanup_in_progress"
    assert len(factory.processes) == 1
    first_process.finish(0)


def test_concurrent_start_only_one_registration(tmp_path, monkeypatch):
    _, path, factory, manager = _make_env(tmp_path, monkeypatch, process_kwargs={"block": True})
    barrier = threading.Barrier(2)
    results = []

    def run():
        barrier.wait()
        try:
            results.append(("ok", manager.start_cleanup(path)))
        except MountPathBusy as exc:
            results.append(("busy", exc.reason))

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)

    assert len([item for item in results if item[0] == "ok"]) == 1
    assert len([item for item in results if item[0] == "busy"]) == 1
    winner_process = wait_for_process(factory)
    assert len(factory.processes) == 1
    winner_process.finish(0)


def test_invalid_path_does_not_leave_reservation(tmp_path, monkeypatch):
    _, path, factory, manager = _make_env(tmp_path, monkeypatch, process_kwargs={"block": True})
    client = _client()

    invalid = _start(client, tmp_path / "outside" / "containers" / "x")
    assert invalid.status_code == 400

    valid = _start(client, path)
    assert valid.status_code == 200
    assert manager._active
    wait_for_process(factory).finish(0)


def test_terminal_releases_path_for_new_task(tmp_path, monkeypatch):
    _, path, factory, manager = _make_env(tmp_path, monkeypatch)
    client = _client()
    first = _start(client, path).json()["task_id"]
    _wait_task(manager, first, "succeeded")

    second_response = _start(client, path)
    second = second_response.json()["task_id"]

    assert second_response.status_code == 200
    assert second != first
    assert manager.get_status(first)["state"] == "succeeded"


def test_two_manager_instances_have_independent_locks(tmp_path, monkeypatch):
    base = tmp_path / "containers-root"
    base.mkdir()
    path = base / "alice" / "containers" / "c1"
    path.mkdir(parents=True)
    monkeypatch.setenv("NODE_CONTAINERS_BASE", str(base))
    factory1 = FakeProcessFactory(block=True)
    factory2 = FakeProcessFactory(block=True)
    manager1 = MountCleanupManager(
        use_launcher=False, rm_path="rm", process_factory=factory1,
    )
    manager2 = MountCleanupManager(
        use_launcher=False, rm_path="rm", process_factory=factory2,
    )

    first = manager1.start_cleanup(path)
    second = manager2.start_cleanup(path)

    assert first != second
    wait_for_process(factory1).finish(0)
    wait_for_process(factory2).finish(0)


def test_terminal_tasks_evict_by_count_and_age(tmp_path, monkeypatch):
    base = tmp_path / "containers-root"
    base.mkdir()
    monkeypatch.setenv("NODE_CONTAINERS_BASE", str(base))
    factory = FakeProcessFactory()
    manager = MountCleanupManager(
        use_launcher=False,
        rm_path="rm",
        process_factory=factory,
        terminal_limit=2,
        terminal_ttl=600,
    )
    ids = []
    for name in ("c1", "c2", "c3"):
        path = base / "alice" / "containers" / name
        path.mkdir(parents=True)
        task_id = manager.start_cleanup(path)
        _wait_task(manager, task_id, "succeeded")
        ids.append(task_id)

    assert manager.get_status(ids[0]) is None
    assert manager.get_status(ids[1]) is not None
    assert manager.get_status(ids[2]) is not None


def test_active_tasks_are_not_evicted(tmp_path, monkeypatch):
    base = tmp_path / "containers-root"
    base.mkdir()
    monkeypatch.setenv("NODE_CONTAINERS_BASE", str(base))
    factory = FakeProcessFactory(block=True)
    manager = MountCleanupManager(
        use_launcher=False,
        rm_path="rm",
        process_factory=factory,
        terminal_limit=1,
        terminal_ttl=600,
    )
    done_path = base / "alice" / "containers" / "done"
    active_path = base / "alice" / "containers" / "active"
    extra_path = base / "alice" / "containers" / "extra"
    for path in (done_path, active_path, extra_path):
        path.mkdir(parents=True)

    done_id = manager.start_cleanup(done_path)
    wait_for_process_for_path(factory, done_path).finish(0)
    _wait_task(manager, done_id, "succeeded")
    active_id = manager.start_cleanup(active_path)
    extra_id = manager.start_cleanup(extra_path)

    wait_for_process_for_path(factory, extra_path).finish(0)
    _wait_task(manager, extra_id, "succeeded")
    assert manager.get_status(active_id)["state"] == "running"
    wait_for_process_for_path(factory, active_path).finish(0)


def test_terminal_state_is_not_overwritten_by_late_result(tmp_path, monkeypatch):
    _, path, factory, manager = _make_env(tmp_path, monkeypatch)
    client = _client()
    task_id = _start(client, path).json()["task_id"]
    _wait_task(manager, task_id, "succeeded")

    assert manager._finish_locked(task_id, "failed", "late") is False
    assert manager.get_status(task_id)["state"] == "succeeded"
    assert manager.get_status(task_id)["error_reason"] is None


def test_restart_drops_old_task_and_returns_404(tmp_path, monkeypatch):
    _, path, factory, manager = _make_env(tmp_path, monkeypatch)
    client = _client()
    task_id = _start(client, path).json()["task_id"]
    _wait_task(manager, task_id, "succeeded")

    restarted = MountCleanupManager(
        use_launcher=False, rm_path="rm", process_factory=FakeProcessFactory(),
    )

    assert restarted.get_status(task_id) is None


def test_new_epoch_never_reuses_old_task_id(tmp_path, monkeypatch):
    base = tmp_path / "containers-root"
    base.mkdir()
    monkeypatch.setenv("NODE_CONTAINERS_BASE", str(base))
    path = base / "alice" / "containers" / "c1"
    path.mkdir(parents=True)
    first = MountCleanupManager(
        use_launcher=False, rm_path="rm", process_factory=FakeProcessFactory(),
    )
    second = MountCleanupManager(
        use_launcher=False, rm_path="rm", process_factory=FakeProcessFactory(),
    )

    first_id = first.start_cleanup(path)
    second_id = second.start_cleanup(path)

    assert first_id.split(":")[0] != second_id.split(":")[0]
    assert first_id != second_id


def test_missing_directory_does_not_create_success(tmp_path, monkeypatch):
    _, _, factory, manager = _make_env(tmp_path, monkeypatch)
    client = _client()

    body = _status(client, "unknown-task").json()

    assert body["success"] == 0
    assert body["error_reason"] == "not_found"
    assert "succeeded" not in body


def test_task_lifecycle_does_not_write_db_wss_or_files(tmp_path, monkeypatch):
    base, path, factory, manager = _make_env(tmp_path, monkeypatch)
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")
    before = {item.name for item in tmp_path.iterdir()}
    monkeypatch.setattr(
        wss_module,
        "build_snapshot_batch",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("WSS must not be built")),
    )
    client = _client()
    task_id = _start(client, path).json()["task_id"]
    _wait_task(manager, task_id, "succeeded")
    _status(client, task_id)

    after = {item.name for item in tmp_path.iterdir()}
    assert after == before
    assert sentinel.read_text(encoding="utf-8") == "keep"
