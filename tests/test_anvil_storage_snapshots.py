"""Anvil storage/snapshot mapping gap tests (Node batch 4).

The real target logic is exercised here: Pydantic wire models, FastAPI routes,
DiskUsageCache path/measurement state, WSS frame builders, status cache action
projection, LastSshCache read surface and SysSnapshotCache static extraction.
Only Docker containers, `/proc` identity, `du`/`rm` subprocesses, psutil/GPU
probes, host disk reads and connection entry points are replaced.

Q77 is deliberately not implemented here: the non-running LastSshCache
old-value assertion is tracked as a separate deferred locator in test-plan.md.
"""
from __future__ import annotations

import asyncio
import copy
import datetime as dt
import json
import os
import re
import socket
import subprocess
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from FuxiYu_NodeKernel import create_app, extensions, lifespan
from FuxiYu_NodeKernel.constant import ContainerStatus
from FuxiYu_NodeKernel.docker_operates import disk_usage_cache as du_module
from FuxiYu_NodeKernel.docker_operates import sys_cache
from FuxiYu_NodeKernel.docker_operates.docker_fact import fact_from_container
from FuxiYu_NodeKernel.docker_operates.disk_usage_cache import (
    DiskUsageCache,
    _norm_path,
    _utc_z,
)
from FuxiYu_NodeKernel.docker_operates.last_ssh_cache import LastSshCache
from FuxiYu_NodeKernel.docker_operates.status_cache import ContainerStatusCache
from FuxiYu_NodeKernel.docker_operates.sys_cache import STATIC_TTL_SEC, SysSnapshotCache
from FuxiYu_NodeKernel.network import api as api_module
from FuxiYu_NodeKernel.network import wss
from FuxiYu_NodeKernel.schemas import (
    CheckDiskUsageMessage,
    CheckDiskUsageResponse,
    CleanMountConfig,
    CleanMountMessage,
    CleanMountResponse,
    ContainerDiskUsage,
    DiskUsageResponse,
    MachineDiskUsage,
)
from FuxiYu_NodeKernel.services import container_service as cs
from FuxiYu_NodeKernel.services.container_service import clean_mount, list_last_ssh

from .runtime_fakes import FakeRuntimeClient, FakeRuntimeContainer, install_runtime

BANNED_WIRE_FIELDS = {
    "configured_mount_path",
    "mount_path_observed_at",
    "measurement_mount_path",
    "measurement_status",
    "measurement_reason",
    "disk_protocol_version",
    "collector_epoch",
    "observation_seq",
    "bind_identity",
    "measurement_identity",
    "docker_id",
}


def _wait_until(predicate, timeout=5.0, message="condition not reached"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    raise AssertionError(message)


def _wait_queue_idle(cache, timeout=5.0):
    _wait_until(
        lambda: cache._mount_work.unfinished_tasks == 0,
        timeout=timeout,
        message="mount usage queue did not drain",
    )


def _wait_settled(cache, path, timeout=5.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = cache.read_mount_usage([path])[0]
        if not last["pending"]:
            return last
        time.sleep(0.01)
    raise AssertionError(f"measurement did not settle: {last}")


def _base(tmp_path, monkeypatch, name="fuxi-base"):
    base = tmp_path / name
    (base / "alice" / "containers").mkdir(parents=True)
    monkeypatch.setenv("NODE_CONTAINERS_BASE", str(base))
    return base


def _container_dir(base, name="c1", user="alice"):
    path = base / user / "containers" / name
    path.mkdir(parents=True)
    return path


def _mount(path):
    return [{"Type": "bind", "Destination": "/root", "Source": str(path)}]


def _proc_identity(cache, actual):
    actual_stat = os.stat(actual)

    def _identity(path):
        if str(path).startswith("/proc/"):
            return actual_stat.st_dev, actual_stat.st_ino
        st = os.stat(path)
        return st.st_dev, st.st_ino

    cache._dir_identity = _identity


def _seed_bind(cache, path, bytes_=4096, *, measured_at=None):
    with cache._lock:
        entry = cache._bind_entry_locked(_norm_path(str(path)))
        entry.update(
            {
                "bytes": bytes_,
                "status": "ok",
                "reason": None,
                "measured_at": measured_at or _utc_z(),
                "running": False,
                "updated_at": dt.datetime.now(dt.timezone.utc),
                "request_id": int(entry.get("request_id") or 0) + 1,
                "failed_at": None,
            }
        )
    return entry


def _seed_path(cache, name, path, *, status="resolved", path_version=0):
    cache._path_state[name] = {
        "bind_mount_path": str(path) if path is not None else None,
        "last_confirmed_path": str(path) if path is not None else None,
        "source_path": str(path) if path is not None else None,
        "check_seq": 0,
        "path_version": path_version,
        "mount_path_status": status,
    }


def _seed_usage(cache, name, path, *, total=30, overlay=10, bind=20, measured_at=None, source="fresh", status="resolved"):
    cache._container_cache[name] = {
        "usage": {
            "container_name": name,
            "overlay_rw_bytes": overlay,
            "bind_mount_bytes": bind,
            "bind_mount_path": str(path) if path is not None else None,
            "mount_path_status": status,
            "bind_mount_source": source,
            "total_bytes": total,
            "error": None,
            "measured_at": measured_at or _utc_z(),
        },
        "updated_at": dt.datetime.now(dt.timezone.utc),
    }


def _seed_online(cache, name="c1", *, status="running", docker_id="A"):
    container = FakeRuntimeContainer(name, status=status, docker_id=docker_id)
    ticket = cache.issue_observation(name, "seed")
    assert cache.publish_observed(name, ticket, fact_from_container(container), mark_ready=True)
    return container


class _OsView:
    def __init__(self, **overrides):
        self.__dict__.update(overrides)

    def __getattr__(self, name):
        return getattr(os, name)


class _RecordClient:
    def __init__(self, records):
        self.containers = self
        self._records = records

    def get(self, name):
        self._records.append(("docker.containers.get", name))
        raise AssertionError("read_mount_usage must not read Docker")

    def list(self, *args, **kwargs):
        self._records.append(("docker.containers.list", None))
        raise AssertionError("read_mount_usage must not enumerate Docker")


# ---------------------------------------------------------------------------
# 1. Data contracts / wire models
# ---------------------------------------------------------------------------


def test_check_disk_usage_message_request_validation(monkeypatch):
    message = CheckDiskUsageMessage(config={})
    assert message.config.container_name is None
    assert message.config.name is None
    with pytest.raises(ValidationError):
        CheckDiskUsageMessage()
    with pytest.raises(ValidationError):
        CheckDiskUsageMessage(config=[])

    calls = []
    monkeypatch.setattr(api_module, "list_disk_usage", lambda: calls.append("list"))
    client = TestClient(create_app())
    response = client.post("/api/check_disk_usage", json={})
    assert response.status_code == 422
    assert calls == []


def test_machine_disk_usage_defaults_and_null_capacity():
    empty = MachineDiskUsage()
    assert empty.total_gb is None
    assert empty.used_gb is None
    assert empty.free_gb is None
    assert empty.percent is None

    full = MachineDiskUsage(total_gb=100, used_gb=20.5, free_gb=79.5, percent=20.5)
    assert full.total_gb == 100
    assert full.used_gb == 20.5
    assert full.free_gb == 79.5
    assert full.percent == 20.5

    with pytest.raises(ValidationError):
        MachineDiskUsage(total_gb={"not": "a number"})


def test_container_disk_usage_rejects_invalid_status_and_types():
    assert ContainerDiskUsage(container_name="c1", mount_path_status="no_bind").mount_path_status == "no_bind"
    with pytest.raises(ValidationError):
        ContainerDiskUsage(container_name="c1", mount_path_status="broken")
    with pytest.raises(ValidationError):
        ContainerDiskUsage(container_name=["not", "a", "string"])
    with pytest.raises(ValidationError):
        ContainerDiskUsage(container_name="c1", overlay_rw_bytes={"not": "an int"})


def test_disk_usage_response_alias_preserves_wire_contract():
    assert DiskUsageResponse is CheckDiskUsageResponse
    payload = {
        "machine_disk": {"total_gb": 100, "used_gb": 20, "free_gb": 80, "percent": 20},
        "container": {
            "container_name": "c1",
            "overlay_rw_bytes": 10,
            "bind_mount_bytes": 20,
            "bind_mount_path": "/home/u/containers/c1",
            "mount_path_status": "resolved",
            "bind_mount_source": "fresh",
            "total_bytes": 30,
            "error": None,
            "measured_at": "2026-10-20T08:00:00Z",
        },
    }
    response = DiskUsageResponse.model_validate(payload)
    dumped = response.model_dump()
    assert dumped["success"] == 1
    assert set(dumped) == {"success", "machine_disk", "container"}
    assert dumped["machine_disk"]["total_gb"] == 100
    assert dumped["container"]["total_bytes"] == 30
    assert set(CheckDiskUsageResponse.model_fields) == {"success", "machine_disk", "container"}


def test_check_disk_usage_response_contract_reads_shared_cache(tmp_path, monkeypatch):
    base = _base(tmp_path, monkeypatch)
    path = _container_dir(base)
    cache = DiskUsageCache()
    _seed_path(cache, "c1", path)
    _seed_usage(cache, "c1", path, total=30, overlay=10, bind=20)
    collect_calls = []
    monkeypatch.setattr(cache, "collect_container", lambda name: collect_calls.append(name))
    monkeypatch.setattr(extensions, "disk_usage_cache", cache)
    monkeypatch.setattr(extensions, "docker_client", None)
    monkeypatch.setattr(extensions, "init_docker", lambda: (_ for _ in ()).throw(AssertionError("docker init")))

    assert CheckDiskUsageResponse(machine_disk={}, container={}).success == 1
    with pytest.raises(ValidationError):
        CheckDiskUsageResponse()

    response = TestClient(create_app()).post(
        "/api/check_disk_usage",
        json={"config": {"container_name": "c1"}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] == 1
    assert body["container"]["container_name"] == "c1"
    assert body["container"]["total_bytes"] == 30
    assert body["container"]["bind_mount_path"] == str(path)
    assert "mounts" not in body
    assert collect_calls == []
    assert "total_gb" in body["machine_disk"]


def test_clean_mount_wire_models():
    config = CleanMountConfig(mount_path="/home/u/containers/c1")
    message = CleanMountMessage(config=config)
    assert message.config.mount_path == "/home/u/containers/c1"
    with pytest.raises(ValidationError):
        CleanMountConfig()
    with pytest.raises(ValidationError):
        CleanMountConfig(mount_path=["not", "a", "string"])
    with pytest.raises(ValidationError):
        CleanMountMessage()
    assert CleanMountResponse().success == 1
    assert CleanMountResponse(success=0).success == 0
    assert CleanMountResponse().model_dump() == {"success": 1}


def test_old_usage_without_measured_at_is_not_current(tmp_path, monkeypatch):
    base = _base(tmp_path, monkeypatch)
    path = _container_dir(base)
    cache = DiskUsageCache()
    _seed_path(cache, "c1", path)
    cache._container_cache["c1"] = {
        "usage": {
            "container_name": "c1",
            "overlay_rw_bytes": 10,
            "bind_mount_bytes": 20,
            "bind_mount_path": str(path),
            "mount_path_status": "resolved",
            "bind_mount_source": "fresh",
            "total_bytes": 30,
            "error": None,
            "measured_at": None,
        },
        "updated_at": dt.datetime.now(dt.timezone.utc),
    }
    usage = cache.snapshot()["containers"]["c1"]
    assert usage["bind_mount_path"] == str(path)
    assert usage["total_bytes"] is None
    assert usage["bind_mount_bytes"] is None
    assert usage["measured_at"] is None
    assert usage["error"] == "measurement_invalid"

    monkeypatch.setattr(extensions, "disk_usage_cache", cache)
    disk = wss.build_disk_usage_snapshot()["payload"]["containers"]["c1"]
    assert disk["total_bytes"] is None
    assert disk["measured_at"] is None
    assert disk["bind_mount_path"] == str(path)


# ---------------------------------------------------------------------------
# 2. Path, measurement and cleanup boundaries
# ---------------------------------------------------------------------------


def test_path_correction_has_no_docker_or_directory_mutation(tmp_path, monkeypatch):
    base = _base(tmp_path, monkeypatch)
    source = _container_dir(base, "old_name")
    actual = _container_dir(base, "new_name")
    cache = DiskUsageCache()
    _proc_identity(cache, actual)
    container = FakeRuntimeContainer("c1", status="running", mounts=_mount(source))
    client = FakeRuntimeClient([container])

    result = cache.verify_mount_path("c1", container=container, client=client)
    assert result["status"] == "resolved"
    assert result["bind_mount_path"] == str(actual)

    install_runtime(monkeypatch, [container])
    monkeypatch.setattr(cache, "_ensure_bind_measure", lambda *a, **k: None)
    cache.collect_container("c1")
    usage = cache.snapshot()["containers"]["c1"]
    assert usage["bind_mount_path"] == str(actual)
    assert "source_path" not in usage
    assert not (BANNED_WIRE_FIELDS & set(usage))
    assert list(source.iterdir()) == []
    assert list(actual.iterdir()) == []
    assert container.start_calls == 0
    assert container.stop_calls == 0
    assert container.pause_calls == 0
    assert container.unpause_calls == 0
    assert container.restart_calls == 0
    assert container.remove_calls == 0


def test_path_correction_scoped_to_active_container(tmp_path, monkeypatch):
    base = _base(tmp_path, monkeypatch)
    old = _container_dir(base, "old")
    new = _container_dir(base, "new")
    other = _container_dir(base, "other")
    cache = DiskUsageCache()
    _proc_identity(cache, new)
    _seed_path(cache, "c1", old)
    _seed_usage(cache, "c1", old, total=41, overlay=11, bind=30)
    _seed_path(cache, "c2", other)
    _seed_usage(cache, "c2", other, total=99, overlay=44, bind=55)
    before_c2 = (copy.deepcopy(cache._path_state["c2"]), copy.deepcopy(cache._container_cache["c2"]))
    monkeypatch.setattr(cache, "_ensure_bind_measure", lambda *a, **k: None)

    container = FakeRuntimeContainer("c1", status="running", mounts=_mount(old))
    result = cache.verify_mount_path("c1", container=container, client=FakeRuntimeClient([container]))
    assert result["status"] == "resolved"
    assert result["bind_mount_path"] == str(new)
    assert cache._path_state["c1"]["bind_mount_path"] == str(new)
    assert cache._container_cache["c1"]["usage"]["bind_mount_path"] == str(new)
    assert before_c2 == (cache._path_state["c2"], cache._container_cache["c2"])


def test_resolved_path_du_failure_publishes_no_total(tmp_path, monkeypatch):
    base = _base(tmp_path, monkeypatch)
    path = _container_dir(base)
    cache = DiskUsageCache()
    _proc_identity(cache, path)
    old_at = _utc_z(dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=30))
    entry = _seed_bind(cache, path, 4096, measured_at=old_at)
    container = FakeRuntimeContainer("c1", status="running", mounts=_mount(path), size_rw=1024)
    install_runtime(monkeypatch, [container])
    monkeypatch.setattr(cache, "_ensure_bind_measure", lambda *a, **k: None)
    cache.collect_container("c1")
    assert cache.snapshot()["containers"]["c1"]["total_bytes"] == 5120

    monkeypatch.setattr(
        du_module.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 1, stdout="123\t/path\n", stderr="denied"),
    )
    cache.collect_bind(str(path), "c1", entry["request_id"])
    cache.collect_container("c1")
    usage = cache.snapshot()["containers"]["c1"]
    assert usage["mount_path_status"] == "resolved"
    assert usage["bind_mount_path"] == str(path)
    assert usage["total_bytes"] is None
    assert usage["bind_mount_bytes"] is None
    assert usage["measured_at"] is None
    assert usage["error"] == "non_zero_exit"
    assert entry["bytes"] == 4096
    assert entry["measured_at"] == old_at
    assert entry["status"] == "error"


def test_paused_container_keeps_path_and_measurement(tmp_path, monkeypatch):
    base = _base(tmp_path, monkeypatch)
    path = _container_dir(base)
    cache = DiskUsageCache()
    _proc_identity(cache, path)
    _seed_bind(cache, path, 4096)
    container = FakeRuntimeContainer("c1", status="paused", mounts=_mount(path), size_rw=1024)
    install_runtime(monkeypatch, [container])
    monkeypatch.setattr(cache, "_ensure_bind_measure", lambda *a, **k: None)
    cache.collect_container("c1")
    usage = cache.snapshot()["containers"]["c1"]
    assert usage["mount_path_status"] == "resolved"
    assert usage["bind_mount_path"] == str(path)
    assert usage["bind_mount_bytes"] == 4096
    assert usage["total_bytes"] == 5120
    assert usage["measured_at"] is not None


def test_bind_presence_blocks_overlay_only_and_no_bind_composes_overlay(tmp_path, monkeypatch):
    base = _base(tmp_path, monkeypatch)
    bind_path = _container_dir(base, "with-bind")

    bind_cache = DiskUsageCache()
    _proc_identity(bind_cache, bind_path)
    bind_container = FakeRuntimeContainer("with-bind", status="running", mounts=_mount(bind_path), size_rw=1024)
    install_runtime(monkeypatch, [bind_container])
    monkeypatch.setattr(bind_cache, "_ensure_bind_measure", lambda *a, **k: None)
    bind_cache.collect_container("with-bind")
    bind_usage = bind_cache.snapshot()["containers"]["with-bind"]
    assert bind_usage["mount_path_status"] == "resolved"
    assert bind_usage["bind_mount_path"] == str(bind_path)
    assert bind_usage["bind_mount_bytes"] is None
    assert bind_usage["total_bytes"] is None
    assert bind_usage["measured_at"] is None
    assert bind_usage["bind_mount_source"] == "measuring"

    no_bind_cache = DiskUsageCache()
    no_bind_container = FakeRuntimeContainer("no-bind", status="running", mounts=[], size_rw=1024)
    install_runtime(monkeypatch, [no_bind_container])
    monkeypatch.setattr(no_bind_cache, "_ensure_bind_measure", lambda *a, **k: None)
    no_bind_cache.collect_container("no-bind")
    no_bind_usage = no_bind_cache.snapshot()["containers"]["no-bind"]
    assert no_bind_usage["mount_path_status"] == "no_bind"
    assert no_bind_usage["bind_mount_path"] is None
    assert no_bind_usage["bind_mount_bytes"] is None
    assert no_bind_usage["total_bytes"] == 1024
    assert no_bind_usage["measured_at"] is not None


def test_path_measurement_does_not_authorize_cleanup(tmp_path, monkeypatch):
    base = _base(tmp_path, monkeypatch)
    path = _container_dir(base)
    outside = tmp_path / "outside" / "target"
    outside.mkdir(parents=True)
    cache = DiskUsageCache()
    _proc_identity(cache, path)
    _seed_bind(cache, path, 4096)
    container = FakeRuntimeContainer("c1", status="running", mounts=_mount(path), size_rw=1024)
    install_runtime(monkeypatch, [container])
    monkeypatch.setattr(cache, "_ensure_bind_measure", lambda *a, **k: None)
    cache.collect_container("c1")
    assert cache.snapshot()["containers"]["c1"]["total_bytes"] == 5120

    service_calls = []
    api_calls = []
    rm_calls = []
    monkeypatch.setattr(cs, "clean_mount", lambda value: service_calls.append(value) or True)
    monkeypatch.setattr(api_module, "clean_mount", lambda value: api_calls.append(value) or True)
    monkeypatch.setattr(
        du_module.subprocess,
        "run",
        lambda cmd, **kwargs: rm_calls.append(list(cmd)) or SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    monkeypatch.setattr(extensions, "disk_usage_cache", cache)

    cache.verify_mount_path("c1", container=container, client=FakeRuntimeClient([container]))
    cache.snapshot()
    wss.build_disk_usage_snapshot()
    assert service_calls == []
    assert api_calls == []
    assert rm_calls == []
    assert container.remove_calls == 0

    with pytest.raises(ValueError):
        clean_mount(str(outside))
    assert rm_calls == []
    assert service_calls == []
    assert api_calls == []


# ---------------------------------------------------------------------------
# 3. check_mount_usage path gate, cache and HTTP surface
# ---------------------------------------------------------------------------


def test_mount_usage_zero_bytes_is_real_success(tmp_path, monkeypatch):
    base = _base(tmp_path, monkeypatch)
    path = _container_dir(base)
    cache = DiskUsageCache()
    monkeypatch.setattr(
        du_module.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="0\t/path\n", stderr=""),
    )

    first = cache.read_mount_usage([str(path)])[0]
    assert first["pending"] is True
    settled = _wait_settled(cache, str(path))
    assert settled["pending"] is False
    assert settled["bytes"] == 0
    assert settled["error"] is None
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", settled["measured_at"])


def test_mount_usage_path_gate_accepts_case_insensitive_containers_segment(tmp_path, monkeypatch):
    base = _base(tmp_path, monkeypatch)
    mixed = base / "alice" / "Containers" / "c1"
    upper = base / "bob" / "CONTAINERS" / "c2"
    mixed.mkdir(parents=True)
    upper.mkdir(parents=True)
    cache = DiskUsageCache()

    for path in (mixed, upper):
        key, error = cache._validate_mount_path(str(path))
        assert error is None
        assert key == _norm_path(os.path.realpath(str(path)))


def test_mount_usage_does_not_enumerate_parent_or_scan(tmp_path, monkeypatch):
    base = _base(tmp_path, monkeypatch)
    allowed = _container_dir(base, "allowed")
    missing = base / "alice" / "containers" / "missing"
    cache = DiskUsageCache()
    records = []

    def _record(name):
        def _fn(*args, **kwargs):
            records.append((name, args))
            raise AssertionError(f"{name} must not be called")

        return _fn

    monkeypatch.setattr(du_module, "os", _OsView(scandir=_record("os.scandir"), listdir=_record("os.listdir")))
    monkeypatch.setattr(cache, "_dir_identity", _record("_dir_identity"))
    monkeypatch.setattr(cache, "collect_machine_disk", _record("collect_machine_disk"))
    monkeypatch.setattr(extensions, "docker_client", _RecordClient(records))
    monkeypatch.setattr(extensions, "init_docker", _record("extensions.init_docker"))
    monkeypatch.setattr(
        du_module.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="7\t/path\n", stderr=""),
    )

    results = cache.read_mount_usage([str(allowed), str(missing)])
    assert results[1]["error"] == "not_found"
    _wait_queue_idle(cache)
    assert records == []


def test_mount_usage_cache_is_empty_after_process_restart(tmp_path, monkeypatch):
    base = _base(tmp_path, monkeypatch)
    path = _container_dir(base)
    cache1 = DiskUsageCache()
    monkeypatch.setattr(
        du_module.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="42\t/path\n", stderr=""),
    )
    assert cache1.read_mount_usage([str(path)])[0]["pending"] is True
    assert _wait_settled(cache1, str(path))["bytes"] == 42

    cache2 = DiskUsageCache()
    assert cache2._bind_cache == {}
    assert cache2._container_cache == {}
    assert cache2._path_state == {}
    monkeypatch.setattr(
        du_module.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="7\t/path\n", stderr=""),
    )
    assert cache2.read_mount_usage([str(path)])[0]["pending"] is True
    assert _wait_settled(cache2, str(path))["bytes"] == 7


def test_check_mount_usage_browser_surface_has_no_cors(tmp_path, monkeypatch):
    base = _base(tmp_path, monkeypatch)
    client = TestClient(create_app())

    options = client.options(
        "/api/check_mount_usage",
        headers={
            "Origin": "https://browser.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert "access-control-allow-origin" not in {key.lower() for key in options.headers}

    response = client.post(
        "/api/check_mount_usage",
        json={"config": {"mount_paths": ["relative/path"]}},
        headers={"Origin": "https://browser.example"},
    )
    assert response.status_code == 200
    assert response.json()["mounts"][0]["error"] == "invalid_path"
    assert "access-control-allow-origin" not in {key.lower() for key in response.headers}

    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/check_mount_usage" in paths
    assert "/check_mount_usage" not in paths


def test_lifespan_has_no_outbound_connection_attempt(monkeypatch):
    for key in list(os.environ):
        if "CTRL" in key.upper() or "WSS" in key.upper():
            monkeypatch.delenv(key, raising=False)

    calls = []
    monkeypatch.setattr(extensions.status_cache, "start", lambda: calls.append("status"))
    monkeypatch.setattr(extensions.last_ssh_cache, "start", lambda: calls.append("last_ssh"))
    monkeypatch.setattr(extensions.disk_usage_cache, "start", lambda: calls.append("disk"))
    monkeypatch.setattr(extensions.sys_cache, "start", lambda: calls.append("sys"))
    monkeypatch.setattr(extensions.sys_cache, "stop", lambda: calls.append("stop"))

    attempts = []

    def _attempt(name):
        def _fn(*args, **kwargs):
            attempts.append((name, args, kwargs))
            raise AssertionError(f"outbound attempt: {name}")

        return _fn

    async def _async_attempt(*args, **kwargs):
        attempts.append(("asyncio.open_connection", args, kwargs))
        raise AssertionError("outbound attempt: asyncio.open_connection")

    monkeypatch.setattr(socket, "create_connection", _attempt("socket.create_connection"))
    monkeypatch.setattr(socket.socket, "connect", _attempt("socket.socket.connect"))
    monkeypatch.setattr(asyncio, "open_connection", _async_attempt)
    try:
        import websockets

        monkeypatch.setattr(websockets, "connect", _attempt("websockets.connect"))
    except ImportError:
        pass

    class _App:
        state = SimpleNamespace()

    async def _run():
        async with lifespan(_App()):
            pass

    asyncio.run(_run())
    assert calls == ["status", "last_ssh", "disk", "sys", "stop"]
    assert attempts == []


# ---------------------------------------------------------------------------
# 4. WSS status/disk/system and LastSsh
# ---------------------------------------------------------------------------


def test_unpause_soft_failure_keeps_online_wss_frame(monkeypatch):
    cache = ContainerStatusCache()
    monkeypatch.setattr(extensions, "status_cache", cache)
    _seed_online(cache, "c1")
    ref = cache.accept_action("c1", "unpause", "unpausing")
    assert cache.finish_action_ref({**ref, "name": "c1"}, "failed", "docker_api_error")

    payload = wss.build_status_snapshot()["payload"]
    entry = payload["c1"]
    assert entry["status"] == "online"
    assert entry["last_action"]["action"] == "unpause"
    assert entry["last_action"]["phase"] == "failed"
    assert "unpause_failed" not in json.dumps(entry)


def test_confirmed_pause_last_action_keeps_online_snapshot(monkeypatch):
    cache = ContainerStatusCache()
    monkeypatch.setattr(extensions, "status_cache", cache)
    _seed_online(cache, "c1")
    ref = cache.accept_action("c1", "pause", "pausing")
    assert cache.finish_action_ref({**ref, "name": "c1"}, "confirmed")

    entry = wss.build_status_snapshot()["payload"]["c1"]
    assert entry["status"] == "online"
    assert entry["last_action"]["action"] == "pause"
    assert entry["last_action"]["phase"] == "confirmed"
    assert entry["status"] != ContainerStatus.PAUSED.value


def test_wss_status_snapshot_failed_and_unknown_frames(monkeypatch):
    cache = ContainerStatusCache()
    monkeypatch.setattr(extensions, "status_cache", cache)
    _seed_online(cache, "c_failed")
    cache.set_hard_block("c_failed", "docker_dead", "dead")
    ticket = cache.issue_observation("c_unknown", "collect_error")
    assert cache.publish_unknown("c_unknown", ticket, reason="inspect_failed")

    payload = wss.build_status_snapshot()["payload"]
    failed = payload["c_failed"]
    assert failed["status"] == "failed"
    assert failed["failed_reason"] == "docker_dead"
    unknown = payload["c_unknown"]
    assert unknown["status"] == "unknown"
    assert unknown["status_source"] == "inspect_failed"
    assert unknown["unknown_since"]


def test_wss_disk_usage_distinguishes_zero_missing_and_measuring(tmp_path, monkeypatch):
    base = _base(tmp_path, monkeypatch)
    path = str(base / "alice" / "containers" / "c1")
    cache = DiskUsageCache()
    measured = _utc_z()
    _seed_path(cache, "c_zero", path)
    _seed_usage(cache, "c_zero", path, total=0, overlay=0, bind=0, measured_at=measured)
    _seed_path(cache, "c_measuring", path)
    cache._container_cache["c_measuring"] = {
        "usage": {
            "container_name": "c_measuring",
            "overlay_rw_bytes": 5,
            "bind_mount_bytes": None,
            "bind_mount_path": path,
            "mount_path_status": "resolved",
            "bind_mount_source": "measuring",
            "total_bytes": None,
            "error": None,
            "measured_at": None,
        },
        "updated_at": dt.datetime.now(dt.timezone.utc),
    }
    monkeypatch.setattr(extensions, "disk_usage_cache", cache)

    containers = wss.build_disk_usage_snapshot()["payload"]["containers"]
    assert set(containers) == {"c_zero", "c_measuring"}
    assert containers["c_zero"]["total_bytes"] == 0
    assert containers["c_zero"]["bind_mount_bytes"] == 0
    assert containers["c_zero"]["measured_at"] == measured
    assert containers["c_measuring"]["total_bytes"] is None
    assert containers["c_measuring"]["bind_mount_bytes"] is None
    assert containers["c_measuring"]["measured_at"] is None
    assert containers["c_measuring"]["bind_mount_source"] == "measuring"
    assert "c_missing" not in containers


def test_last_ssh_empty_output_returns_none_and_serializes_updated_at(monkeypatch):
    class _EmptyContainer:
        attrs = {"State": {"Status": "running"}}

        def exec_run(self, *args, **kwargs):
            return SimpleNamespace(exit_code=0, output=b"")

    class _Client:
        class containers:
            @staticmethod
            def get(name):
                assert name == "c1"
                return _EmptyContainer()

    cache = LastSshCache()
    monkeypatch.setattr(extensions, "docker_client", _Client())
    monkeypatch.setattr(extensions, "last_ssh_cache", cache)
    cache.collect("c1")
    snapshot = list_last_ssh()
    assert snapshot["c1"]["last_ssh_connect_time"] is None
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", snapshot["c1"]["updated_at"])
    assert not snapshot["c1"]["updated_at"].endswith("Z")
    frame = wss.build_last_ssh_snapshot()
    assert frame["payload"]["c1"]["last_ssh_connect_time"] is None
    assert frame["payload"]["c1"]["updated_at"] == snapshot["c1"]["updated_at"]


def test_static_hardware_profile_uses_bind_mount_and_cache_expiry(tmp_path, monkeypatch):
    bind_root = tmp_path / "bind-root"
    docker_root = tmp_path / "docker-root"
    bind_root.mkdir()
    docker_root.mkdir()
    monkeypatch.setenv("NODE_CONTAINERS_BASE", str(bind_root))
    monkeypatch.setenv("NODE_DOCKER_DATA_ROOT", str(docker_root))

    bind_total = {"value": 100}
    paths = []

    def _fake_mount(cls, path):
        paths.append(path)
        total = bind_total["value"] if path == str(bind_root) else 50
        return {"path": path, "total_gb": total, "used_gb": 1, "free_gb": total - 1, "percent": 1.0}

    monkeypatch.setattr(SysSnapshotCache, "_mount_disk_usage", classmethod(_fake_mount))
    monkeypatch.setattr(sys_cache, "_cpu_info", lambda: {"cores": 8, "physical_cores": 4})
    monkeypatch.setattr(sys_cache, "_memory_info", lambda: {"total_gb": 16})
    monkeypatch.setattr(sys_cache, "_gpu_info", lambda: [])

    cache = SysSnapshotCache()
    static = cache.collect_static()
    assert static["cpu"]["cores"] == 8
    assert static["memory"]["total_gb"] == 16
    assert static["disk"]["total_gb"] == 100
    assert str(bind_root) in paths

    cache._static_at = dt.datetime.utcnow() - dt.timedelta(seconds=STATIC_TTL_SEC + 1)
    bind_total["value"] = 200
    refreshed = cache.collect_static()
    assert refreshed["disk"]["total_gb"] == 200
    assert paths.count(str(bind_root)) >= 2


def test_sys_snapshot_collects_bind_and_docker_data_partitions(tmp_path, monkeypatch):
    bind_root = tmp_path / "bind-root"
    docker_root = tmp_path / "docker-root"
    bind_root.mkdir()
    docker_root.mkdir()
    monkeypatch.setenv("NODE_CONTAINERS_BASE", str(bind_root))
    monkeypatch.setenv("NODE_DOCKER_DATA_ROOT", str(docker_root))

    calls = []

    def _fake_mount(cls, path):
        calls.append(path)
        total = 111 if path == str(bind_root) else 222
        return {"path": path, "total_gb": total, "used_gb": 1, "free_gb": total - 1, "percent": 1.0}

    monkeypatch.setattr(SysSnapshotCache, "_mount_disk_usage", classmethod(_fake_mount))
    monkeypatch.setattr(sys_cache, "_cpu_info", lambda: {"cores": 8})
    monkeypatch.setattr(sys_cache, "_memory_info", lambda: {"total_gb": 16})
    monkeypatch.setattr(sys_cache, "_gpu_info", lambda: [])

    disk = SysSnapshotCache._collect_disk()
    assert disk["bind_mount"]["path"] == str(bind_root)
    assert disk["bind_mount"]["total_gb"] == 111
    assert disk["docker_data"]["path"] == str(docker_root)
    assert disk["docker_data"]["total_gb"] == 222
    assert calls == [str(bind_root), str(docker_root)]

    cache = SysSnapshotCache()
    snapshot = cache.collect()
    assert snapshot["disk"] == disk
