"""verify-bind-mount-identity：路径核对、业务路径测量与当前线路字段。

Docker、/proc 与 du 是可注入边界；路径整理、缓存键、路径变更失效和
HTTP/WSS 共用模型是真实实现。这里不修改 Ctrl，也不把目录对象编号/PID/
inode 当业务身份或线路字段。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import threading

import pytest
from fastapi.testclient import TestClient

from FuxiYu_NodeKernel import create_app, extensions
from FuxiYu_NodeKernel.docker_operates.disk_usage_cache import (
    BIND_DU_TIMEOUT_SEC,
    DiskUsageCache,
    _norm_path,
    _parse_utc,
    _same_path,
    _utc_z,
)
from FuxiYu_NodeKernel.network import wss
from FuxiYu_NodeKernel.schemas import ContainerDiskUsage

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


def _base(tmp_path, monkeypatch):
    base = tmp_path / "home"
    (base / "admin" / "containers").mkdir(parents=True)
    monkeypatch.setenv("NODE_CONTAINERS_BASE", str(base))
    return base


def _mount(path):
    return [{"Type": "bind", "Destination": "/root", "Source": str(path)}]


def _proc_identity(cache, actual, aliases=None):
    aliases = aliases or {}

    def _identity(path):
        if path.startswith("/proc/"):
            return os.stat(actual).st_dev, os.stat(actual).st_ino
        real = os.path.realpath(path)
        for key, value in aliases.items():
            if os.path.realpath(key) == real:
                return value
        return os.stat(path).st_dev, os.stat(path).st_ino

    cache._dir_identity = _identity


def _seed_bind(cache, path, bytes_=8192, *, measured_at=None, status="ok", reason=None):
    with cache._lock:
        entry = cache._bind_entry_locked(_norm_path(str(path)))
        entry["bytes"] = bytes_
        entry["status"] = status
        entry["reason"] = reason
        entry["measured_at"] = measured_at or _utc_z()
        entry["running"] = False
        entry["updated_at"] = dt.datetime.now(dt.timezone.utc)
        entry["request_id"] = int(entry.get("request_id") or 0) + 1
    return entry


def _verify(cache, name, *, status="running", mounts, pid=4321, docker_id="A"):
    container = FakeRuntimeContainer(
        name,
        status=status,
        docker_id=docker_id,
        mounts=mounts,
        pid=pid,
    )
    client = FakeRuntimeClient([container])
    return cache.verify_mount_path(name, container=container, client=client), container


def _collect(cache, name, container, monkeypatch):
    client = install_runtime(monkeypatch, [container])
    monkeypatch.setattr(cache, "_ensure_bind_measure", lambda *a, **k: None)
    cache.collect_container(name)
    return client


# ---------------------------------------------------------------------------
# 1. 路径确认与有界纠正
# ---------------------------------------------------------------------------


def test_source_matches_actual_resolved_without_wire_identity(tmp_path, monkeypatch):
    base = _base(tmp_path, monkeypatch)
    actual = base / "admin" / "containers" / "c1"
    actual.mkdir()
    cache = DiskUsageCache()
    _proc_identity(cache, actual)

    result, _ = _verify(cache, "c1", mounts=_mount(actual))

    assert result["status"] == "resolved"
    assert result["bind_mount_path"] == str(actual)
    assert result["path_version"] == 1
    assert cache._path_state["c1"]["mount_path_status"] == "resolved"
    assert "configured_mount_path" not in result
    assert "mount_path_observed_at" not in result


def test_mismatched_source_unique_candidate_corrects_business_path(tmp_path, monkeypatch):
    base = _base(tmp_path, monkeypatch)
    source = base / "admin" / "containers" / "old_name"
    actual = base / "admin" / "containers" / "new_name"
    source.mkdir()
    actual.mkdir()
    cache = DiskUsageCache()
    _proc_identity(cache, actual)

    result, _ = _verify(cache, "c1", mounts=_mount(source))

    assert result["status"] == "resolved"
    assert result["bind_mount_path"] == str(actual)
    assert not _same_path(result["bind_mount_path"], source)


def test_renamed_source_missing_still_finds_unique_new_path(tmp_path, monkeypatch):
    base = _base(tmp_path, monkeypatch)
    old = base / "admin" / "containers" / "older"
    new_path = base / "admin" / "containers" / "renamed"
    missing = base / "admin" / "containers" / "gone"
    old.mkdir()
    new_path.mkdir()
    cache = DiskUsageCache()
    cache._path_state["c1"] = {
        "bind_mount_path": str(old),
        "last_confirmed_path": str(old),
        "source_path": str(old),
        "check_seq": 0,
        "path_version": 0,
    }
    _proc_identity(cache, new_path)

    result, _ = _verify(cache, "c1", mounts=_mount(missing))

    assert result["status"] == "resolved"
    assert result["bind_mount_path"] == str(new_path)


def test_ambiguous_candidates_unresolved_and_preserve_existing(tmp_path, monkeypatch):
    base = _base(tmp_path, monkeypatch)
    existing = base / "admin" / "containers" / "c1"
    other = base / "admin" / "containers" / "c2"
    missing = base / "admin" / "containers" / "missing"
    existing.mkdir()
    other.mkdir()
    cache = DiskUsageCache()
    shared = (12345, 67890)
    cache._dir_identity = lambda path: shared
    cache._path_state["c1"] = {
        "bind_mount_path": str(existing),
        "last_confirmed_path": str(existing),
        "source_path": str(missing),
        "check_seq": 0,
        "path_version": 0,
    }

    result, _ = _verify(cache, "c1", mounts=_mount(missing))

    assert result["status"] == "unresolved"
    assert result["bind_mount_path"] == str(existing)
    assert result["reason"] == "ambiguous_candidates"
    assert cache._path_state["c1"]["bind_mount_path"] == str(existing)


def test_no_candidate_unresolved_and_no_business_path(tmp_path, monkeypatch):
    base = _base(tmp_path, monkeypatch)
    missing = base / "admin" / "containers" / "missing"
    cache = DiskUsageCache()
    cache._dir_identity = lambda path: (1, 2) if path.startswith("/proc/") else (3, 4)

    result, _ = _verify(cache, "c1", mounts=_mount(missing))

    assert result["status"] == "unresolved"
    assert result["bind_mount_path"] is None
    assert result["reason"] == "no_candidate"


def test_proc_unreadable_unresolved_preserves_existing_path(tmp_path, monkeypatch):
    base = _base(tmp_path, monkeypatch)
    existing = base / "admin" / "containers" / "c1"
    existing.mkdir()
    cache = DiskUsageCache()
    cache._path_state["c1"] = {
        "bind_mount_path": str(existing),
        "last_confirmed_path": str(existing),
        "source_path": str(existing),
        "check_seq": 0,
        "path_version": 0,
    }
    cache._dir_identity = lambda path: (_ for _ in ()).throw(PermissionError("proc"))

    result, _ = _verify(cache, "c1", mounts=_mount(existing))

    assert result["status"] == "unresolved"
    assert result["bind_mount_path"] == str(existing)
    assert result["reason"] == "actual_unreadable"


def test_no_pid_not_running_and_preserves_path(tmp_path, monkeypatch):
    base = _base(tmp_path, monkeypatch)
    existing = base / "admin" / "containers" / "c1"
    existing.mkdir()
    cache = DiskUsageCache()
    cache._path_state["c1"] = {
        "bind_mount_path": str(existing),
        "last_confirmed_path": str(existing),
        "source_path": str(existing),
        "check_seq": 0,
        "path_version": 0,
    }

    result, _ = _verify(cache, "c1", status="exited", mounts=_mount(existing), pid=0)

    assert result["status"] == "not_running"
    assert result["bind_mount_path"] == str(existing)


def test_paused_with_pid_is_verified_like_running(tmp_path, monkeypatch):
    base = _base(tmp_path, monkeypatch)
    actual = base / "admin" / "containers" / "c1"
    actual.mkdir()
    cache = DiskUsageCache()
    _proc_identity(cache, actual)

    result, _ = _verify(cache, "c1", status="paused", mounts=_mount(actual), pid=4321)

    assert result["status"] == "resolved"
    assert result["bind_mount_path"] == str(actual)


def test_docker_confirmed_no_bind_clears_paths(tmp_path, monkeypatch):
    _base(tmp_path, monkeypatch)
    cache = DiskUsageCache()
    cache._path_state["c1"] = {
        "bind_mount_path": "/old/path",
        "last_confirmed_path": "/old/path",
        "source_path": "/source",
        "check_seq": 0,
        "path_version": 2,
    }

    result, _ = _verify(cache, "c1", mounts=[])

    assert result["status"] == "no_bind"
    assert result["bind_mount_path"] is None
    state = cache._path_state["c1"]
    assert state["bind_mount_path"] is None
    assert state["path_version"] == 3


def test_inspect_failure_does_not_become_no_bind(tmp_path, monkeypatch):
    _base(tmp_path, monkeypatch)
    cache = DiskUsageCache()
    cache._path_state["c1"] = {
        "bind_mount_path": "/old/path",
        "last_confirmed_path": "/old/path",
        "source_path": "/source",
        "check_seq": 0,
        "path_version": 0,
    }
    install_runtime(monkeypatch, [])
    extensions.docker_client.containers.get = lambda name: (_ for _ in ()).throw(
        RuntimeError("inspect failed")
    )

    result = cache.verify_mount_path("c1")

    assert result["status"] == "unresolved"
    assert result["bind_mount_path"] == "/old/path"
    assert cache._path_state["c1"]["bind_mount_path"] == "/old/path"
    assert cache._path_state["c1"]["mount_path_status"] == "unresolved"


def test_bounded_search_only_scans_allowed_parents(tmp_path, monkeypatch):
    base = _base(tmp_path, monkeypatch)
    outside = tmp_path / "outside" / "containers" / "evil"
    outside.mkdir(parents=True)
    cache = DiskUsageCache()
    cache._dir_identity = lambda path: (9, 9) if path.startswith("/proc/") else (1, 1)
    scanned = []
    real_scandir = os.scandir

    def _scandir(path):
        scanned.append(os.path.realpath(path))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", _scandir)
    result, _ = _verify(cache, "c1", mounts=_mount(outside))

    assert result["status"] == "unresolved"
    assert all(os.path.realpath(p).startswith(os.path.realpath(str(base))) for p in scanned)
    assert os.path.realpath(str(outside.parent)) not in scanned


def test_late_path_check_result_is_dropped_by_check_sequence(tmp_path, monkeypatch):
    base = _base(tmp_path, monkeypatch)
    old_dir = base / "admin" / "containers" / "old"
    new_dir = base / "admin" / "containers" / "new"
    old_dir.mkdir()
    new_dir.mkdir()
    cache = DiskUsageCache()
    entered = threading.Event()
    release = threading.Event()

    def _identity(path):
        if path.startswith("/proc/"):
            if threading.current_thread().name == "old-check":
                entered.set()
                release.wait(3)
            return os.stat(new_dir).st_dev, os.stat(new_dir).st_ino
        return os.stat(path).st_dev, os.stat(path).st_ino

    cache._dir_identity = _identity
    old_container = FakeRuntimeContainer("c1", docker_id="A", mounts=_mount(old_dir))
    new_container = FakeRuntimeContainer("c1", docker_id="B", mounts=_mount(new_dir))
    old_client = FakeRuntimeClient([old_container])
    new_client = FakeRuntimeClient([new_container])
    result = {}

    def _old_check():
        result["old"] = cache.verify_mount_path("c1", container=old_container, client=old_client)

    thread = threading.Thread(target=_old_check, name="old-check")
    thread.start()
    assert entered.wait(2)
    cache.verify_mount_path("c1", container=new_container, client=new_client)
    release.set()
    thread.join(3)

    assert result["old"] is None
    assert cache._path_state["c1"]["docker_id"] == "B"
    assert cache._path_state["c1"]["bind_mount_path"] == str(new_dir)


@pytest.mark.parametrize("change", ["docker_id", "pid"])
def test_late_path_result_dropped_when_active_object_changes(tmp_path, monkeypatch, change):
    base = _base(tmp_path, monkeypatch)
    old_dir = base / "admin" / "containers" / "old"
    new_dir = base / "admin" / "containers" / "new"
    missing = base / "admin" / "containers" / "moved_away"
    old_dir.mkdir()
    new_dir.mkdir()
    cache = DiskUsageCache()
    _proc_identity(cache, old_dir)
    old_container = FakeRuntimeContainer(
        "c1",
        docker_id="A",
        pid=111,
        mounts=_mount(missing),
    )
    new_container = FakeRuntimeContainer(
        "c1",
        docker_id=("B" if change == "docker_id" else "A"),
        pid=(111 if change == "docker_id" else 222),
        mounts=_mount(new_dir),
    )

    class _Client:
        def __init__(self):
            self.current = old_container
            self.containers = self

        def get(self, name):
            return self.current

    client = _Client()
    entered = threading.Event()
    release = threading.Event()
    original = cache._bounded_matches

    def _blocked(*args, **kwargs):
        entered.set()
        release.wait(3)
        return original(*args, **kwargs)

    cache._bounded_matches = _blocked
    result = {}

    def _check():
        result["result"] = cache.verify_mount_path("c1", container=old_container, client=client)

    thread = threading.Thread(target=_check)
    thread.start()
    assert entered.wait(2)
    client.current = new_container
    release.set()
    thread.join(3)

    assert result["result"] is None
    state = cache._path_state.get("c1", {})
    assert state.get("mount_path_status") != "resolved"
    assert not _same_path(state.get("bind_mount_path"), str(old_dir))


@pytest.mark.parametrize("new_status", ["unresolved", "not_running"])
def test_lightweight_path_diagnostic_updates_snapshot_without_touching_measurement(
    tmp_path, monkeypatch, new_status
):
    """resolved 缓存转 unresolved/not_running 时只更新诊断，不清有效测量。"""
    base = _base(tmp_path, monkeypatch)
    actual = base / "admin" / "containers" / "c1"
    actual.mkdir()
    cache = DiskUsageCache()
    _proc_identity(cache, actual)
    _seed_bind(cache, actual, 4096)
    container = FakeRuntimeContainer("c1", mounts=_mount(actual), size_rw=1024)
    client = _collect(cache, "c1", container, monkeypatch)
    first = cache.snapshot()["containers"]["c1"]
    assert first["mount_path_status"] == "resolved"
    assert first["total_bytes"] == 5120
    assert first["measured_at"] is not None

    bind_calls = []
    monkeypatch.setattr(
        cache,
        "_ensure_bind_measure",
        lambda *a, **k: bind_calls.append((a, k)),
    )
    if new_status == "unresolved":
        # 轻量核对：actual 不可读，但不得清掉已有业务路径或有效测量。
        cache._dir_identity = lambda path: (_ for _ in ()).throw(PermissionError("proc"))
    else:
        # 容器进入 exited：无稳定 PID，同样只更新诊断。
        container.set_status("exited")

    result = cache.verify_mount_path("c1", container=container, client=client)
    assert result["status"] == new_status
    snapshot = cache.snapshot()["containers"]["c1"]
    assert snapshot["mount_path_status"] == new_status
    assert snapshot["bind_mount_path"] == str(actual)
    assert snapshot["total_bytes"] == 5120
    assert snapshot["measured_at"] == first["measured_at"]
    assert bind_calls == []


# ---------------------------------------------------------------------------
# 2. 按业务路径测量、真实时间与失败
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_mounts",
    [
        None,
        "not-a-list",
        [None],
        [[]],
    ],
)
def test_unreadable_mounts_are_unresolved_not_no_bind(tmp_path, monkeypatch, bad_mounts):
    base = _base(tmp_path, monkeypatch)
    existing = base / "admin" / "containers" / "c1"
    existing.mkdir()
    cache = DiskUsageCache()
    cache._path_state["c1"] = {
        "bind_mount_path": str(existing),
        "last_confirmed_path": str(existing),
        "source_path": str(existing),
        "check_seq": 0,
        "path_version": 0,
    }
    container = FakeRuntimeContainer("c1", status="running", mounts=_mount(existing))
    container.attrs["Mounts"] = bad_mounts

    result = cache.verify_mount_path(
        "c1",
        container=container,
        client=FakeRuntimeClient([container]),
    )

    assert result["status"] == "unresolved"
    assert result["reason"] == "mounts_unreadable"
    assert result["bind_mount_path"] == str(existing)
    assert cache._path_state["c1"]["bind_mount_path"] == str(existing)


def test_measurement_uses_business_path_and_earlier_component_time(tmp_path, monkeypatch):
    base = _base(tmp_path, monkeypatch)
    actual = base / "admin" / "containers" / "c1"
    actual.mkdir()
    cache = DiskUsageCache()
    _proc_identity(cache, actual)
    bind_at = _utc_z(dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=60))
    _seed_bind(cache, actual, 4096, measured_at=bind_at)
    container = FakeRuntimeContainer("c1", mounts=_mount(actual), size_rw=1024)

    _collect(cache, "c1", container, monkeypatch)
    usage = cache.snapshot()["containers"]["c1"]

    assert usage["bind_mount_path"] == str(actual)
    assert usage["mount_path_status"] == "resolved"
    assert usage["bind_mount_bytes"] == 4096
    assert usage["overlay_rw_bytes"] == 1024
    assert usage["total_bytes"] == 5120
    assert usage["measured_at"] == bind_at
    assert not (BANNED_WIRE_FIELDS & set(usage))


def test_measured_at_uses_earlier_component_when_bind_sample_is_newer(tmp_path, monkeypatch):
    base = _base(tmp_path, monkeypatch)
    actual = base / "admin" / "containers" / "c1"
    actual.mkdir()
    cache = DiskUsageCache()
    _proc_identity(cache, actual)
    now = dt.datetime.now(dt.timezone.utc)
    future_bind_at = _utc_z(now + dt.timedelta(seconds=30))
    _seed_bind(cache, actual, 4096, measured_at=future_bind_at)
    container = FakeRuntimeContainer("c1", mounts=_mount(actual), size_rw=1024)

    _collect(cache, "c1", container, monkeypatch)
    usage = cache.snapshot()["containers"]["c1"]

    assert usage["total_bytes"] == 5120
    assert usage["measured_at"] != future_bind_at
    measured = _parse_utc(usage["measured_at"])
    assert measured is not None
    assert measured <= now + dt.timedelta(seconds=5)


def test_path_change_drops_old_sample_until_new_path_measured(tmp_path, monkeypatch):
    base = _base(tmp_path, monkeypatch)
    path_a = base / "admin" / "containers" / "a"
    path_b = base / "admin" / "containers" / "b"
    path_a.mkdir()
    path_b.mkdir()
    cache = DiskUsageCache()
    _proc_identity(cache, path_a)
    _seed_bind(cache, path_a, 111)
    container_a = FakeRuntimeContainer("c1", mounts=_mount(path_a), size_rw=10)
    _collect(cache, "c1", container_a, monkeypatch)
    assert cache.snapshot()["containers"]["c1"]["total_bytes"] == 121

    # 路径核对先到 B；B 的新 du 尚未完成，旧 A 样本不能贴到 B。
    _proc_identity(cache, path_b)
    container_b = FakeRuntimeContainer("c1", docker_id="dockerid-c1", mounts=_mount(path_b), size_rw=20)
    cache.verify_mount_path("c1", container=container_b, client=FakeRuntimeClient([container_b]))
    usage = cache.snapshot()["containers"]["c1"]
    assert usage["bind_mount_path"] == str(path_b)
    assert usage["bind_mount_bytes"] is None
    assert usage["total_bytes"] is None
    assert usage["measured_at"] is None


def test_snapshot_does_not_publish_cached_path_bytes_under_new_path():
    cache = DiskUsageCache()
    now = _utc_z()
    with cache._lock:
        cache._path_state["c1"] = {
            "bind_mount_path": "/home/admin/containers/b",
            "mount_path_status": "resolved",
        }
        cache._container_cache["c1"] = {
            "usage": {
                "container_name": "c1",
                "overlay_rw_bytes": 100,
                "bind_mount_bytes": 200,
                "bind_mount_path": "/home/admin/containers/a",
                "mount_path_status": "resolved",
                "bind_mount_source": "fresh",
                "total_bytes": 300,
                "error": None,
                "measured_at": now,
            },
            "updated_at": dt.datetime.now(dt.timezone.utc),
        }

    usage = cache.snapshot()["containers"]["c1"]
    assert usage["bind_mount_path"] == "/home/admin/containers/b"
    assert usage["bind_mount_bytes"] is None
    assert usage["total_bytes"] is None
    assert usage["measured_at"] is None


def test_unresolved_with_existing_path_and_valid_measurement_stays_total(tmp_path, monkeypatch):
    base = _base(tmp_path, monkeypatch)
    existing = base / "admin" / "containers" / "c1"
    other = base / "admin" / "containers" / "c2"
    missing = base / "admin" / "containers" / "missing"
    existing.mkdir()
    other.mkdir()
    cache = DiskUsageCache()
    _seed_bind(cache, existing, 4096)
    cache._path_state["c1"] = {
        "bind_mount_path": str(existing),
        "last_confirmed_path": str(existing),
        "source_path": str(missing),
        "check_seq": 0,
        "path_version": 0,
    }
    cache._dir_identity = lambda path: (7, 8)
    container = FakeRuntimeContainer("c1", mounts=_mount(missing), size_rw=1024)

    _collect(cache, "c1", container, monkeypatch)
    usage = cache.snapshot()["containers"]["c1"]

    assert usage["mount_path_status"] == "unresolved"
    assert usage["bind_mount_path"] == str(existing)
    assert usage["total_bytes"] == 5120
    assert usage["error"] is None


def test_du_failure_keeps_last_success_diagnostic_but_publishes_no_total(tmp_path, monkeypatch):
    base = _base(tmp_path, monkeypatch)
    path = base / "admin" / "containers" / "c1"
    path.mkdir()
    cache = DiskUsageCache()
    old_time = _utc_z(dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=30))
    entry = _seed_bind(cache, path, 777, measured_at=old_time)
    monkeypatch.setattr(
        "FuxiYu_NodeKernel.docker_operates.disk_usage_cache.subprocess.run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 1, stdout="123\t/path\n", stderr="denied"),
    )

    cache.collect_bind(str(path), "c1", entry["request_id"])

    with cache._lock:
        assert entry["bytes"] == 777
        assert entry["measured_at"] == old_time
        assert entry["status"] == "error"
        assert entry["reason"] == "non_zero_exit"
    measurement = cache._measurement_for_path("c1", str(path), trigger=False)
    assert measurement["bind_mount_bytes"] is None
    assert measurement["error"] == "non_zero_exit"
    assert measurement["measured_at"] is None


@pytest.mark.parametrize(
    ("outcome", "reason"),
    [
        ({"completed": ("", 0)}, "empty_output"),
        ({"completed": ("not-a-size\t/path", 0)}, "parse_error"),
        ({"timeout": True}, "timeout"),
        ({"permission": True}, "permission_denied"),
        ({"missing_du": True}, "du_unavailable"),
        ({"completed": ("123\t/path", 2)}, "non_zero_exit"),
    ],
)
def test_every_du_failure_is_not_zero(monkeypatch, tmp_path, outcome, reason):
    path = tmp_path / "bind"
    path.mkdir()
    cache = DiskUsageCache()

    def _run(*args, **kwargs):
        if outcome.get("timeout"):
            raise subprocess.TimeoutExpired(args[0], BIND_DU_TIMEOUT_SEC)
        if outcome.get("permission"):
            raise PermissionError("denied")
        if outcome.get("missing_du"):
            raise FileNotFoundError("du")
        stdout, rc = outcome["completed"]
        return subprocess.CompletedProcess(args[0], rc, stdout=stdout, stderr="failed")

    monkeypatch.setattr(
        "FuxiYu_NodeKernel.docker_operates.disk_usage_cache.subprocess.run",
        _run,
    )
    entry = cache._bind_entry_locked(_norm_path(str(path)))
    entry["request_id"] = 1
    entry["running"] = True
    entry["status"] = "measuring"
    cache.collect_bind(str(path), "c1", 1)

    assert entry["status"] == "error"
    assert entry["reason"] == reason
    assert entry["bytes"] is None
    assert cache._measurement_for_path("c1", str(path), trigger=False)["error"] == reason


def test_old_path_du_late_does_not_become_new_path_total(tmp_path, monkeypatch):
    base = _base(tmp_path, monkeypatch)
    path_a = base / "admin" / "containers" / "a"
    path_b = base / "admin" / "containers" / "b"
    path_a.mkdir()
    path_b.mkdir()
    cache = DiskUsageCache()
    entered = threading.Event()
    release = threading.Event()

    def _run(args, **kwargs):
        if os.path.basename(args[-1]) == "a":
            entered.set()
            release.wait(3)
            return subprocess.CompletedProcess(args, 0, stdout="111\tpath\n", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="222\tpath\n", stderr="")

    monkeypatch.setattr(
        "FuxiYu_NodeKernel.docker_operates.disk_usage_cache.subprocess.run",
        _run,
    )
    with cache._lock:
        entry_a = cache._bind_entry_locked(_norm_path(str(path_a)))
        entry_a["request_id"] = 1
        entry_a["running"] = True
        entry_a["status"] = "measuring"
    thread = threading.Thread(target=cache.collect_bind, args=(str(path_a), "c1", 1))
    thread.start()
    assert entered.wait(2)

    _proc_identity(cache, path_b)
    _seed_bind(cache, path_b, 222)
    container_b = FakeRuntimeContainer("c1", mounts=_mount(path_b), size_rw=10)
    _collect(cache, "c1", container_b, monkeypatch)
    release.set()
    thread.join(3)

    usage = cache.snapshot()["containers"]["c1"]
    assert usage["bind_mount_path"] == str(path_b)
    assert usage["bind_mount_bytes"] == 222
    assert usage["total_bytes"] == 232
    assert cache._bind_cache[_norm_path(str(path_a))]["bytes"] == 111


def test_snapshot_does_not_trigger_du_or_refresh_measured_at(tmp_path, monkeypatch):
    base = _base(tmp_path, monkeypatch)
    actual = base / "admin" / "containers" / "c1"
    actual.mkdir()
    cache = DiskUsageCache()
    _proc_identity(cache, actual)
    _seed_bind(cache, actual, 4096)
    container = FakeRuntimeContainer("c1", mounts=_mount(actual), size_rw=1024)
    _collect(cache, "c1", container, monkeypatch)
    first = cache.snapshot()["containers"]["c1"]
    calls = []
    monkeypatch.setattr(cache, "_ensure_bind_measure", lambda *a, **k: calls.append(a))

    second = cache.snapshot()["containers"]["c1"]

    assert second["measured_at"] == first["measured_at"]
    assert second["total_bytes"] == first["total_bytes"]
    assert calls == []


def test_http_not_collected_is_none_not_zero(monkeypatch):
    cache = DiskUsageCache()
    monkeypatch.setattr(extensions, "disk_usage_cache", cache)
    client = TestClient(create_app())

    response = client.post("/api/check_disk_usage", json={"config": {"container_name": "missing"}})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] == 1
    assert body["container"]["total_bytes"] is None
    assert body["container"]["error"] == "not_collected"
    assert body["container"]["mount_path_status"] == "unresolved"
    assert body["container"]["measured_at"] is None
    assert not (BANNED_WIRE_FIELDS & set(body["container"]))


# ---------------------------------------------------------------------------
# 3. HTTP/WSS 字段、模型与控制面边界
# ---------------------------------------------------------------------------


def test_container_disk_usage_model_only_has_current_fields_and_null_round_trip():
    expected = {
        "container_name",
        "overlay_rw_bytes",
        "bind_mount_bytes",
        "bind_mount_path",
        "mount_path_status",
        "bind_mount_source",
        "total_bytes",
        "error",
        "measured_at",
    }
    assert set(ContainerDiskUsage.model_fields) == expected
    assert not (BANNED_WIRE_FIELDS & set(ContainerDiskUsage.model_fields))

    defaulted = ContainerDiskUsage(container_name="c1").model_dump()
    assert defaulted["mount_path_status"] == "unresolved"
    assert defaulted["measured_at"] is None

    explicit_null = ContainerDiskUsage(
        container_name="c1",
        bind_mount_path=None,
        mount_path_status=None,
        measured_at=None,
        total_bytes=None,
    ).model_dump()
    assert explicit_null["bind_mount_path"] is None
    assert explicit_null["mount_path_status"] is None
    assert explicit_null["measured_at"] is None

    old_payload = {
        "container_name": "c1",
        "overlay_rw_bytes": 1,
        "bind_mount_bytes": 2,
        "bind_mount_path": "/home/admin/containers/c1",
        "bind_mount_source": "fresh",
        "total_bytes": 3,
        "error": None,
    }
    old = ContainerDiskUsage(**old_payload).model_dump()
    assert old["measured_at"] is None
    assert old["mount_path_status"] == "unresolved"
    assert not (BANNED_WIRE_FIELDS & set(old))


def test_http_and_wss_share_same_disk_usage_fields(tmp_path, monkeypatch):
    base = _base(tmp_path, monkeypatch)
    actual = base / "admin" / "containers" / "c1"
    actual.mkdir()
    cache = DiskUsageCache()
    _proc_identity(cache, actual)
    _seed_bind(cache, actual, 4096)
    container = FakeRuntimeContainer("c1", mounts=_mount(actual), size_rw=1024)
    _collect(cache, "c1", container, monkeypatch)
    monkeypatch.setattr(extensions, "disk_usage_cache", cache)

    wss_frame = wss.build_disk_usage_snapshot()
    wss_usage = wss_frame["payload"]["containers"]["c1"]
    client = TestClient(create_app())
    http_body = client.post(
        "/api/check_disk_usage",
        json={"config": {"container_name": "c1"}},
    ).json()["container"]

    for key in (
        "bind_mount_path",
        "mount_path_status",
        "measured_at",
        "overlay_rw_bytes",
        "bind_mount_bytes",
        "total_bytes",
        "bind_mount_source",
        "error",
    ):
        assert wss_usage[key] == http_body[key]
    assert not (BANNED_WIRE_FIELDS & set(wss_usage))
    wire = json.loads(json.dumps(wss_frame, ensure_ascii=True))
    assert "disk_protocol_version" not in json.dumps(wire)
    assert "_link_generation" not in vars(wss)


def test_repeated_wss_json_does_not_refresh_measured_at(tmp_path, monkeypatch):
    base = _base(tmp_path, monkeypatch)
    actual = base / "admin" / "containers" / "c1"
    actual.mkdir()
    cache = DiskUsageCache()
    _proc_identity(cache, actual)
    _seed_bind(cache, actual, 4096)
    container = FakeRuntimeContainer("c1", mounts=_mount(actual), size_rw=1024)
    _collect(cache, "c1", container, monkeypatch)
    monkeypatch.setattr(extensions, "disk_usage_cache", cache)

    first = wss.build_disk_usage_snapshot()["payload"]["containers"]["c1"]
    second = wss.build_disk_usage_snapshot()["payload"]["containers"]["c1"]

    assert first["measured_at"] == second["measured_at"]
    assert first["total_bytes"] == second["total_bytes"]


def _ctrl_apply_disk_state(
    existing_path,
    existing_checked_at,
    usage,
    *,
    received_at,
    machine_id="m1",
    event_machine_id="m1",
    authenticated=True,
    active=True,
):
    """独立本地夹具，模拟 Ctrl 只消费当前三个字段，不写入任何新列。"""

    if not authenticated or not active or machine_id != event_machine_id:
        return {"bind_mount_path": existing_path, "disk_checked_at": existing_checked_at}
    status = usage.get("mount_path_status") or "unresolved"
    path = existing_path
    if status == "resolved":
        path = usage.get("bind_mount_path")
    elif status == "no_bind":
        path = None
    checked_at = usage.get("measured_at") or received_at
    return {"bind_mount_path": path, "disk_checked_at": checked_at}


def test_ctrl_compat_fixture_update_preserve_clear_and_old_node():
    usage_resolved = {"bind_mount_path": "/new", "mount_path_status": "resolved", "measured_at": "2026-10-18T00:00:00Z"}
    updated = _ctrl_apply_disk_state("/old", "2026-10-17T00:00:00Z", usage_resolved, received_at="2026-10-18T01:00:00Z")
    assert updated == {"bind_mount_path": "/new", "disk_checked_at": "2026-10-18T00:00:00Z"}

    usage_no_bind = {"bind_mount_path": None, "mount_path_status": "no_bind", "measured_at": "2026-10-18T00:00:00Z"}
    cleared = _ctrl_apply_disk_state("/old", "2026-10-17T00:00:00Z", usage_no_bind, received_at="2026-10-18T01:00:00Z")
    assert cleared["bind_mount_path"] is None

    inactive = _ctrl_apply_disk_state(
        "/old",
        "2026-10-17T00:00:00Z",
        usage_no_bind,
        received_at="2026-10-18T01:00:00Z",
        active=False,
    )
    assert inactive["bind_mount_path"] == "/old"
    wrong_machine = _ctrl_apply_disk_state(
        "/old",
        "2026-10-17T00:00:00Z",
        usage_resolved,
        received_at="2026-10-18T01:00:00Z",
        event_machine_id="m2",
    )
    assert wrong_machine["bind_mount_path"] == "/old"

    for status in ("unresolved", "not_running"):
        usage = {"bind_mount_path": "/wrong", "mount_path_status": status, "measured_at": None}
        preserved = _ctrl_apply_disk_state("/old", "2026-10-17T00:00:00Z", usage, received_at="2026-10-18T01:00:00Z")
        assert preserved["bind_mount_path"] == "/old"

    old_node = {"bind_mount_path": "/old-node", "total_bytes": 123}
    old_result = _ctrl_apply_disk_state("/corrected", "2026-10-17T00:00:00Z", old_node, received_at="2026-10-18T01:00:00Z")
    assert old_result["bind_mount_path"] == "/corrected"


def _q72_strategy_fixture(usage):
    """本地策略回放：只按有效测量事实动作，不检查路径诊断/inode。"""

    if usage.get("mount_path_status") not in {None, "resolved", "unresolved", "not_running", "no_bind"}:
        raise AssertionError("unexpected path status")
    return usage.get("total_bytes") is not None


def test_path_diagnostic_never_gates_measurement_or_q72_fixture():
    valid_unresolved = {
        "bind_mount_path": "/valid",
        "mount_path_status": "unresolved",
        "overlay_rw_bytes": 10,
        "bind_mount_bytes": 20,
        "total_bytes": 30,
        "measured_at": _utc_z(),
    }
    invalid_resolved = {
        "bind_mount_path": "/invalid",
        "mount_path_status": "resolved",
        "overlay_rw_bytes": 10,
        "bind_mount_bytes": None,
        "total_bytes": None,
        "measured_at": None,
    }
    assert _q72_strategy_fixture(valid_unresolved) is True
    assert _q72_strategy_fixture(invalid_resolved) is False
    # 恢复/长期/冻结/删除/清理都只消费同一测量事实，不读取路径诊断作门禁。
    for action in ("recover", "long_term", "freeze", "delete", "cleanup"):
        assert _q72_strategy_fixture(valid_unresolved) is True, action
        assert _q72_strategy_fixture(invalid_resolved) is False, action


def test_guard_runtime_identity_fields_are_not_disk_protocol():
    # 磁盘协议只保留业务路径控制/测量时间；运行态 DockerID/action_ref 归 guard。
    assert "docker_id" not in ContainerDiskUsage.model_fields
    assert "bind_identity" not in ContainerDiskUsage.model_fields
    assert "measurement_identity" not in ContainerDiskUsage.model_fields
    # 没有磁盘 epoch/seq，也没有 WSS 连接代际模块变量。
    assert not hasattr(wss, "_link_generation")
