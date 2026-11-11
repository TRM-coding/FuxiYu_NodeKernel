from __future__ import annotations

import os
import threading
import uuid

from fastapi.testclient import TestClient

from FuxiYu_NodeKernel import create_app, extensions
from FuxiYu_NodeKernel.network import api as api_module
from FuxiYu_NodeKernel.services.container_service import CreateContainerReturn
from FuxiYu_NodeKernel.services.mount_cleanup import (
    MountCleanupManager,
    MountPathBusy,
)

from .mount_cleanup_fakes import FakeProcessFactory, wait_until


ROOT_PW = "Root#Password9"


def _cfg(name):
    return {
        "gpu_list": [],
        "cpu_number": 2,
        "memory": 4,
        "shared_memory": 0,
        "name": name,
        "port": 2233,
        "image": "ubuntu:22.04",
    }


def _payload(name, restore_path):
    return {
        "owner_name": "admin",
        "config": _cfg(name),
        "root_password": ROOT_PW,
        "restore_mount_path": str(restore_path),
    }


def _env(tmp_path, monkeypatch, *, process_kwargs=None):
    base = tmp_path / "containers-root"
    base.mkdir()
    path = base / "admin" / "containers" / "c1"
    path.mkdir(parents=True)
    monkeypatch.setenv("NODE_CONTAINERS_BASE", str(base))
    factory = FakeProcessFactory(**(process_kwargs or {}))
    manager = MountCleanupManager(
        use_launcher=False,
        rm_path="rm",
        process_factory=factory,
    )
    monkeypatch.setattr(extensions, "mount_cleanup", manager)
    monkeypatch.setattr(api_module, "container_exists", lambda name: False)
    return base, path, factory, manager


def _client():
    return TestClient(create_app())


def _wait_task(manager, task_id, state, timeout=3.0):
    assert wait_until(lambda: (manager.get_status(task_id) or {}).get("state") == state, timeout)


def test_restore_reserves_path_before_accepting(tmp_path, monkeypatch):
    base, path, factory, manager = _env(tmp_path, monkeypatch, process_kwargs={"block": True})
    entered = threading.Event()
    release = threading.Event()
    name = f"restore_{uuid.uuid4().hex[:8]}"

    def create_stub(owner_name, cfg, *, root_password, public_key=None, restore_mount_path=None):
        entered.set()
        release.wait(2)
        return CreateContainerReturn("cid", cfg.name)

    monkeypatch.setattr(api_module, "create_container", create_stub)
    client = _client()
    response = client.post("/api/create_container", json=_payload(name, path))

    assert response.status_code == 200
    assert entered.wait(2)
    busy = client.post(
        "/api/start_clean_mount",
        json={"config": {"mount_path": str(path)}},
    )
    assert busy.status_code == 409
    assert busy.json()["error_reason"] == "restore_in_progress"

    release.set()
    assert wait_until(lambda: not manager._restore_tokens)
    accepted = client.post(
        "/api/start_clean_mount",
        json={"config": {"mount_path": str(path)}},
    )
    assert accepted.status_code == 200
    factory.processes[0].finish(0)


def test_restore_rejected_when_cleanup_running(tmp_path, monkeypatch):
    _, path, factory, manager = _env(tmp_path, monkeypatch, process_kwargs={"block": True})
    manager.start_cleanup(path)
    assert wait_until(lambda: bool(factory.processes))
    called = []
    monkeypatch.setattr(
        api_module,
        "create_container",
        lambda *args, **kwargs: called.append(kwargs) or CreateContainerReturn("cid", "c"),
    )
    client = _client()

    response = client.post("/api/create_container", json=_payload(f"restore_{uuid.uuid4().hex[:8]}", path))

    assert response.status_code == 409
    assert response.json()["error_reason"] == "cleanup_in_progress"
    assert called == []
    factory.processes[0].finish(0)


def test_two_restore_requests_only_one_reservation(tmp_path, monkeypatch):
    _, path, _, manager = _env(tmp_path, monkeypatch)
    barrier = threading.Barrier(2)
    results = []

    def reserve():
        barrier.wait()
        try:
            results.append(("ok", manager.reserve_restore(path)))
        except MountPathBusy as exc:
            results.append(("busy", exc.reason))

    threads = [threading.Thread(target=reserve) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)

    assert len([item for item in results if item[0] == "ok"]) == 1
    assert len([item for item in results if item[0] == "busy"]) == 1
    ok = next(item[1] for item in results if item[0] == "ok")
    manager.release_restore(ok.token)


def test_invalid_restore_path_rejected_before_accept(tmp_path, monkeypatch):
    base, path, _, manager = _env(tmp_path, monkeypatch)
    called = []
    monkeypatch.setattr(
        api_module,
        "create_container",
        lambda *args, **kwargs: called.append(kwargs) or CreateContainerReturn("cid", "c"),
    )
    client = _client()

    response = client.post(
        "/api/create_container",
        json=_payload(f"restore_{uuid.uuid4().hex[:8]}", base / "missing" / "containers" / "x"),
    )

    assert response.status_code == 400
    assert response.json()["error_reason"] == "invalid_path"
    assert called == []
    assert manager._restore_tokens == {}


def test_normal_create_does_not_take_restore_reservation(tmp_path, monkeypatch):
    _, path, factory, manager = _env(tmp_path, monkeypatch)
    called = []

    def create_stub(owner_name, cfg, *, root_password, public_key=None, restore_mount_path=None):
        called.append(restore_mount_path)
        return CreateContainerReturn("cid", cfg.name)

    monkeypatch.setattr(api_module, "create_container", create_stub)
    client = _client()
    response = client.post(
        "/api/create_container",
        json={
            "owner_name": "admin",
            "config": _cfg(f"normal_{uuid.uuid4().hex[:8]}"),
            "root_password": ROOT_PW,
        },
    )

    assert response.status_code == 200
    assert wait_until(lambda: bool(called))
    assert called == [None]
    assert manager._restore_tokens == {}


def test_cleanup_rejected_during_restore_background(tmp_path, monkeypatch):
    _, path, factory, manager = _env(tmp_path, monkeypatch, process_kwargs={"block": True})
    entered = threading.Event()
    release = threading.Event()

    def create_stub(owner_name, cfg, *, root_password, public_key=None, restore_mount_path=None):
        entered.set()
        release.wait(2)
        return CreateContainerReturn("cid", cfg.name)

    monkeypatch.setattr(api_module, "create_container", create_stub)
    client = _client()
    response = client.post(
        "/api/create_container",
        json=_payload(f"restore_{uuid.uuid4().hex[:8]}", path),
    )
    assert response.status_code == 200
    assert entered.wait(2)

    async_busy = client.post(
        "/api/start_clean_mount",
        json={"config": {"mount_path": str(path)}},
    )
    old_busy = client.post(
        "/api/clean_mount",
        json={"config": {"mount_path": str(path)}},
    )
    assert async_busy.status_code == 409
    assert async_busy.json()["error_reason"] == "restore_in_progress"
    assert old_busy.status_code == 409
    assert old_busy.json()["error_reason"] == "restore_in_progress"
    assert factory.calls == []

    release.set()
    assert wait_until(lambda: not manager._restore_tokens)


def test_restore_cleanup_race_allows_one_winner(tmp_path, monkeypatch):
    _, path, factory, manager = _env(tmp_path, monkeypatch, process_kwargs={"block": True})
    barrier = threading.Barrier(2)
    results = []

    def reserve():
        barrier.wait()
        try:
            results.append(("restore", manager.reserve_restore(path)))
        except MountPathBusy as exc:
            results.append(("busy", exc.reason))

    def clean():
        barrier.wait()
        try:
            results.append(("cleanup", manager.start_cleanup(path)))
        except MountPathBusy as exc:
            results.append(("busy", exc.reason))

    threads = [threading.Thread(target=reserve), threading.Thread(target=clean)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)

    assert len([item for item in results if item[0] != "busy"]) == 1
    if any(item[0] == "cleanup" for item in results):
        factory.processes[0].finish(0)
    else:
        reservation = next(item[1] for item in results if item[0] == "restore")
        manager.release_restore(reservation.token)


def test_restore_reservation_released_after_success(tmp_path, monkeypatch):
    _, path, factory, manager = _env(tmp_path, monkeypatch, process_kwargs={"block": True})
    release = threading.Event()

    def create_stub(owner_name, cfg, *, root_password, public_key=None, restore_mount_path=None):
        release.wait(2)
        return CreateContainerReturn("cid", cfg.name)

    monkeypatch.setattr(api_module, "create_container", create_stub)
    client = _client()
    assert client.post(
        "/api/create_container",
        json=_payload(f"restore_{uuid.uuid4().hex[:8]}", path),
    ).status_code == 200
    assert wait_until(lambda: bool(manager._restore_tokens))
    release.set()
    assert wait_until(lambda: not manager._restore_tokens)

    response = client.post(
        "/api/start_clean_mount",
        json={"config": {"mount_path": str(path)}},
    )
    assert response.status_code == 200
    factory.processes[0].finish(0)


def test_restore_reservation_released_after_failure(tmp_path, monkeypatch):
    _, path, _, manager = _env(tmp_path, monkeypatch)
    monkeypatch.setattr(
        api_module,
        "create_container",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("create failed")),
    )
    monkeypatch.setattr(extensions.status_cache, "refresh_from_docker", lambda *a, **k: None)
    client = _client()
    assert client.post(
        "/api/create_container",
        json=_payload(f"restore_{uuid.uuid4().hex[:8]}", path),
    ).status_code == 200
    assert wait_until(lambda: not manager._restore_tokens)

    response = client.post(
        "/api/start_clean_mount",
        json={"config": {"mount_path": str(path)}},
    )
    assert response.status_code == 200


def test_restart_drops_restore_reservation(tmp_path, monkeypatch):
    _, path, _, manager = _env(tmp_path, monkeypatch)
    reservation = manager.reserve_restore(path)
    restarted = MountCleanupManager(
        use_launcher=False,
        rm_path="rm",
        process_factory=FakeProcessFactory(),
    )

    new_reservation = restarted.reserve_restore(path)

    assert new_reservation.token != reservation.token
    manager.release_restore(reservation.token)
    restarted.release_restore(new_reservation.token)


def test_cleanup_failure_releases_path_for_restore(tmp_path, monkeypatch):
    _, path, factory, manager = _env(tmp_path, monkeypatch, process_kwargs={"returncode": 1})
    task_id = manager.start_cleanup(path)
    _wait_task(manager, task_id, "failed")

    reservation = manager.reserve_restore(path)
    assert reservation.real_path == os.path.realpath(str(path))
    manager.release_restore(reservation.token)


def test_partial_cleanup_survives_restart_and_restore_is_accepted(tmp_path, monkeypatch):
    _, path, factory, manager = _env(tmp_path, monkeypatch)
    first = path / "first.txt"
    second = path / "second.txt"
    first.write_text("one", encoding="utf-8")
    second.write_text("two", encoding="utf-8")

    def delete_one(_process):
        first.unlink()

    factory.default_kwargs.update({"returncode": 1, "on_communicate": delete_one})
    task_id = manager.start_cleanup(path)
    _wait_task(manager, task_id, "failed")
    assert not first.exists()
    assert second.exists()

    restarted = MountCleanupManager(
        use_launcher=False,
        rm_path="rm",
        process_factory=FakeProcessFactory(),
    )
    reservation = restarted.reserve_restore(path)
    assert reservation.real_path == os.path.realpath(str(path))
    restarted.release_restore(reservation.token)
