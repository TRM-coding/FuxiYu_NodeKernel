from __future__ import annotations

import threading

from fastapi.testclient import TestClient

from FuxiYu_NodeKernel import create_app, extensions
from FuxiYu_NodeKernel.services.mount_cleanup import (
    SYNC_CLEANUP_TIMEOUT_SECONDS,
    MountCleanupManager,
)

from .mount_cleanup_fakes import FakeProcessFactory, wait_for_process, wait_until


def _env(tmp_path, monkeypatch, *, process_kwargs=None, **manager_kwargs):
    base = tmp_path / "containers-root"
    base.mkdir()
    path = base / "alice" / "containers" / "c1"
    path.mkdir(parents=True)
    monkeypatch.setenv("NODE_CONTAINERS_BASE", str(base))
    factory = FakeProcessFactory(**(process_kwargs or {}))
    manager = MountCleanupManager(
        use_launcher=False,
        rm_path="rm",
        process_factory=factory,
        **manager_kwargs,
    )
    monkeypatch.setattr(extensions, "mount_cleanup", manager)
    return path, factory, manager


def _client():
    return TestClient(create_app())


def _old_clean(client, path):
    return client.post("/api/clean_mount", json={"config": {"mount_path": str(path)}})


def test_old_sync_waits_for_exit_zero(tmp_path, monkeypatch):
    path, factory, _ = _env(tmp_path, monkeypatch, process_kwargs={"block": True})
    client = _client()
    result = {}

    def request():
        result["response"] = _old_clean(client, path)

    thread = threading.Thread(target=request)
    thread.start()
    process = wait_for_process(factory)
    assert thread.is_alive(), "legacy sync endpoint must not return before rm exits"

    process.finish(0)
    thread.join(timeout=3)
    assert result["response"].status_code == 200
    assert result["response"].json() == {"success": 1}


def test_old_sync_timeout_remains_500_timeout_with_30_seconds(tmp_path, monkeypatch):
    assert SYNC_CLEANUP_TIMEOUT_SECONDS == 30.0
    path, factory, _ = _env(
        tmp_path,
        monkeypatch,
        process_kwargs={"block": True},
        sync_timeout=0.01,
    )
    client = _client()
    response = _old_clean(client, path)

    assert response.status_code == 500
    assert response.json()["error_reason"] == "timeout"
    assert wait_for_process(factory).terminated is True


def test_old_sync_invalid_and_rm_failure_shapes(tmp_path, monkeypatch):
    path, factory, _ = _env(tmp_path, monkeypatch, process_kwargs={"returncode": 1, "stderr": "denied"})
    client = _client()

    invalid = _old_clean(client, tmp_path / "outside" / "containers" / "x")
    assert invalid.status_code == 400
    assert invalid.json()["error_reason"] == "invalid_path"

    failed = _old_clean(client, path)
    assert failed.status_code == 500
    assert failed.json()["success"] == 0
    assert failed.json()["error_reason"] == "internal_error"


def test_old_sync_conflicts_with_async_and_restore(tmp_path, monkeypatch):
    path, factory, manager = _env(tmp_path, monkeypatch, process_kwargs={"block": True})
    client = _client()
    task_id = manager.start_cleanup(path)
    process = wait_for_process(factory)

    busy = _old_clean(client, path)
    assert busy.status_code == 409
    assert busy.json()["error_reason"] == "cleanup_in_progress"

    process.finish(0)
    wait_until(lambda: (manager.get_status(task_id) or {}).get("state") == "succeeded")
    reservation = manager.reserve_restore(path)
    restore_busy = _old_clean(client, path)
    assert restore_busy.status_code == 409
    assert restore_busy.json()["error_reason"] == "restore_in_progress"
    manager.release_restore(reservation.token)


def test_two_old_sync_requests_only_one_rm(tmp_path, monkeypatch):
    path, factory, _ = _env(tmp_path, monkeypatch, process_kwargs={"block": True})
    client = _client()
    results = []

    def request():
        results.append(_old_clean(client, path))

    first = threading.Thread(target=request)
    first.start()
    process = wait_for_process(factory)

    second = _old_clean(client, path)
    assert second.status_code == 409
    assert second.json()["error_reason"] == "cleanup_in_progress"

    process.finish(0)
    first.join(timeout=3)
    assert len(factory.processes) == 1
    assert any(response.status_code == 200 for response in results)


def test_old_endpoint_remains_old_client_compatible(tmp_path, monkeypatch):
    path, factory, _ = _env(tmp_path, monkeypatch)
    client = _client()
    response = _old_clean(client, path)

    assert response.status_code == 200
    assert response.json() == {"success": 1}
    assert "task_id" not in response.json()
    assert len(factory.processes) == 1


def test_new_ctrl_three_cleanup_paths_use_async_contract(tmp_path, monkeypatch):
    path, factory, manager = _env(tmp_path, monkeypatch)
    client = _client()
    assert "/api/start_clean_mount" in client.get("/openapi.json").json()["paths"]
    assert "/api/get_clean_mount_status" in client.get("/openapi.json").json()["paths"]
    assert "/api/clean_mount" in client.get("/openapi.json").json()["paths"]

    started = client.post(
        "/api/start_clean_mount",
        json={"config": {"mount_path": str(path)}},
    )
    assert started.status_code == 200
    assert started.json()["task_id"]
    assert "state" not in started.json()
    wait_for_process(factory)
