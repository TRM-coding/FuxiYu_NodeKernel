"""check_mount_usage 的路径门禁、缓存投影、并发与清理测试。"""
import datetime as dt
import os
import re
import shutil
import subprocess
import threading
import time
from types import SimpleNamespace

import pytest

from FuxiYu_NodeKernel.docker_operates import disk_usage_cache as du_module
from FuxiYu_NodeKernel.docker_operates.disk_usage_cache import (
    BIND_CACHE_TTL_SEC,
    BIND_DU_TIMEOUT_SEC,
    MOUNT_USAGE_FAILURE_COOLDOWN_SEC,
    MOUNT_USAGE_MAX_CONCURRENCY,
    DiskUsageCache,
    _norm_path,
    _utc_z,
)


class _ModuleOsView:
    """只替换单个模块看到的 ``os``，其余属性继续委托真实 os。

    直接 monkeypatch ``du_module.os.stat`` 实际改到进程全局 os 模块，
    pytest 的 linecache/traceback 也会看到替身；把作用域收回被测模块。
    """

    def __init__(self, **overrides):
        self.__dict__.update(overrides)

    def __getattr__(self, name):
        return getattr(os, name)


class FakeClock:
    def __init__(self, start):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += dt.timedelta(seconds=seconds)


def _utc(year=2026, month=1, day=1, hour=0, minute=0, second=0):
    return dt.datetime(year, month, day, hour, minute, second, tzinfo=dt.timezone.utc)


def _wait_until(predicate, timeout=5.0, message="condition not reached"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    raise AssertionError(message)


def _wait_for_settled(cache, path, timeout=5.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = cache.read_mount_usage([path])[0]
        if not last["pending"]:
            return last
        time.sleep(0.01)
    raise AssertionError(f"measurement did not settle: {last}")


def _wait_queue_idle(cache, timeout=5.0):
    _wait_until(
        lambda: cache._mount_work.unfinished_tasks == 0,
        timeout=timeout,
        message="mount usage queue did not drain",
    )


def _ok(stdout="7\t/path\n"):
    return SimpleNamespace(returncode=0, stdout=stdout, stderr="")


def _seed_success(cache, path, *, bytes_, measured_at, status="ok", failed_at=None):
    key = _norm_path(os.path.realpath(str(path)))
    with cache._lock:
        entry = cache._bind_entry_locked(key)
        entry.update(
            {
                "bytes": bytes_,
                "status": status,
                "reason": None,
                "measured_at": measured_at,
                "running": False,
                "request_id": 0,
                "failed_at": failed_at,
                "updated_at": None,
            }
        )
    return key


def _entry(cache, key):
    with cache._lock:
        return dict(cache._bind_cache.get(key) or {})


@pytest.fixture()
def base(tmp_path, monkeypatch):
    containers_base = tmp_path / "fuxi-base"
    containers_base.mkdir()
    monkeypatch.setenv("NODE_CONTAINERS_BASE", str(containers_base))
    return containers_base


def _container_dir(base, name="c1", user="alice"):
    path = base / user / "containers" / name
    path.mkdir(parents=True)
    return path


# ---------------------------------------------------------------------------
# 路径门禁
# ---------------------------------------------------------------------------


def test_path_gate_accepts_allowed_directory_and_normalized_aliases(base):
    path = _container_dir(base)
    cache = DiskUsageCache()
    expected_key = _norm_path(os.path.realpath(str(path)))

    assert cache._validate_mount_path(str(path)) == (expected_key, None)
    aliases = [
        f"{path}/",
        f"{path}/.",
        str(base / "alice" / "containers" / "c1" / ".." / "c1"),
    ]
    for alias in aliases:
        assert cache._validate_mount_path(alias) == (expected_key, None)


def test_path_gate_rejects_out_of_scope_relative_missing_segment_file_and_missing(base, tmp_path):
    cache = DiskUsageCache()
    outside = tmp_path / "outside" / "alice" / "containers" / "c1"
    outside.mkdir(parents=True)
    no_segment = base / "alice" / "data" / "c1"
    no_segment.mkdir(parents=True)
    plain_file = base / "alice" / "containers" / "plain.txt"
    plain_file.parent.mkdir(parents=True, exist_ok=True)
    plain_file.write_text("x", encoding="utf-8")
    missing = base / "alice" / "containers" / "missing"

    assert cache._validate_mount_path(str(outside)) == (None, "invalid_path")
    assert cache._validate_mount_path("alice/containers/c1") == (None, "invalid_path")
    assert cache._validate_mount_path(str(base)) == (None, "invalid_path")
    assert cache._validate_mount_path(str(no_segment)) == (None, "invalid_path")
    assert cache._validate_mount_path(str(plain_file))[1] == "invalid_path"
    key, error = cache._validate_mount_path(str(missing))
    assert error == "not_found"
    assert key == _norm_path(os.path.realpath(str(missing)))


def test_path_gate_rejects_symlink_and_dangling_symlink(base):
    cache = DiskUsageCache()
    target = _container_dir(base, "target")
    link = base / "alice" / "containers" / "link"
    dangling = base / "alice" / "containers" / "dangling"
    try:
        os.symlink(str(target), str(link), target_is_directory=True)
        os.symlink(str(base / "alice" / "containers" / "gone"), str(dangling))
    except (OSError, NotImplementedError):
        pytest.skip("symlink not permitted in this environment")

    assert cache._validate_mount_path(str(link)) == (None, "invalid_path")
    assert cache._validate_mount_path(f"{link}/") == (None, "invalid_path")
    assert cache._validate_mount_path(str(dangling)) == (None, "invalid_path")


def test_path_gate_maps_permission_error_without_stat(base, monkeypatch):
    cache = DiskUsageCache()
    target = _container_dir(base)
    real_stat = os.stat

    def guarded_stat(path, *args, **kwargs):
        if os.path.normcase(os.fspath(path)) == os.path.normcase(os.fspath(target)):
            raise PermissionError("denied")
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(du_module, "os", _ModuleOsView(stat=guarded_stat))

    key, error = cache._validate_mount_path(str(target))
    assert error == "permission_denied"
    assert key == _norm_path(os.path.realpath(str(target)))
    assert os.stat is real_stat, "必须只替换 du_module 的 os 视图"


def test_invalid_not_found_and_permission_never_start_du(base, tmp_path, monkeypatch):
    cache = DiskUsageCache()
    outside = tmp_path / "outside" / "alice" / "containers" / "c1"
    outside.mkdir(parents=True)
    missing = base / "alice" / "containers" / "missing"
    permission_dir = _container_dir(base, "no-read")
    plain_file = base / "alice" / "containers" / "plain.txt"
    plain_file.write_text("x", encoding="utf-8")
    no_segment = base / "alice" / "data" / "c1"
    no_segment.mkdir(parents=True)

    real_stat = os.stat

    def guarded_stat(path, *args, **kwargs):
        if os.path.normcase(os.fspath(path)) == os.path.normcase(os.fspath(permission_dir)):
            raise PermissionError("denied")
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(du_module, "os", _ModuleOsView(stat=guarded_stat))
    calls = []
    monkeypatch.setattr(
        du_module.subprocess,
        "run",
        lambda *args, **kwargs: calls.append((args, kwargs)) or _ok(),
    )

    results = cache.read_mount_usage(
        [
            "alice/containers/c1",
            str(outside),
            str(no_segment),
            str(plain_file),
            str(missing),
            str(permission_dir),
        ]
    )

    assert [item["error"] for item in results] == [
        "invalid_path",
        "invalid_path",
        "invalid_path",
        "invalid_path",
        "not_found",
        "permission_denied",
    ]
    assert all(item["bytes"] is None for item in results)
    assert all(item["measured_at"] is None for item in results)
    assert all(item["pending"] is False for item in results)
    assert calls == []
    assert os.stat is real_stat, "必须只替换 du_module 的 os 视图"


# ---------------------------------------------------------------------------
# 状态投影与真实测量时间
# ---------------------------------------------------------------------------


def test_ttl_hit_reuses_original_measured_at_without_du(base, monkeypatch):
    clock = FakeClock(_utc())
    monkeypatch.setattr(du_module, "_utc_now", clock)
    path = _container_dir(base)
    cache = DiskUsageCache()
    measured_at = _utc_z(clock.now - dt.timedelta(seconds=60))
    _seed_success(cache, path, bytes_=123, measured_at=measured_at)
    calls = []
    monkeypatch.setattr(
        du_module.subprocess,
        "run",
        lambda *args, **kwargs: calls.append((args, kwargs)) or _ok(),
    )

    result = cache.read_mount_usage([str(path)])[0]

    assert result == {
        "path": str(path),
        "bytes": 123,
        "measured_at": measured_at,
        "pending": False,
        "error": None,
    }
    assert calls == []


def test_expired_success_returns_pending_and_never_old_bytes(base, monkeypatch):
    clock = FakeClock(_utc())
    monkeypatch.setattr(du_module, "_utc_now", clock)
    path = _container_dir(base)
    cache = DiskUsageCache()
    old_measured_at = _utc_z(clock.now - dt.timedelta(seconds=BIND_CACHE_TTL_SEC))
    _seed_success(cache, path, bytes_=123, measured_at=old_measured_at)
    release = threading.Event()
    started = threading.Event()

    def fake_run(cmd, **kwargs):
        started.set()
        release.wait(5)
        return _ok("4242\t/path\n")

    monkeypatch.setattr(du_module.subprocess, "run", fake_run)

    first = cache.read_mount_usage([str(path)])[0]
    assert first["pending"] is True
    assert first["bytes"] is None
    assert first["measured_at"] is None

    # 成功样本年龄达到 900 秒：不得把 TTL 内的旧值伪装成当前成功。
    assert _wait_until(started.is_set, message="du did not start")
    release.set()
    settled = _wait_for_settled(cache, str(path))
    assert settled["bytes"] == 4242
    assert settled["measured_at"] == _utc_z(clock.now)
    assert settled["pending"] is False


def test_failure_keeps_last_success_internally_but_never_projects_it(base, monkeypatch):
    clock = FakeClock(_utc())
    monkeypatch.setattr(du_module, "_utc_now", clock)
    path = _container_dir(base)
    cache = DiskUsageCache()
    old_measured_at = _utc_z(clock.now - dt.timedelta(seconds=BIND_CACHE_TTL_SEC + 1))
    key = _seed_success(cache, path, bytes_=100, measured_at=old_measured_at)

    monkeypatch.setattr(
        du_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="123\t/path\n", stderr=""),
    )

    first = cache.read_mount_usage([str(path)])[0]
    assert first["pending"] is True
    settled = _wait_for_settled(cache, str(path))
    assert settled == {
        "path": str(path),
        "bytes": None,
        "measured_at": None,
        "pending": False,
        "error": "non_zero_exit",
    }

    entry = _entry(cache, key)
    assert entry["bytes"] == 100, "失败不得覆盖最后成功字节"
    assert entry["measured_at"] == old_measured_at, "失败不得覆盖最后成功时间"
    assert entry["status"] == "error"
    assert entry["failed_at"] is not None

    repeated = cache.read_mount_usage([str(path)])[0]
    assert repeated["bytes"] is None
    assert repeated["error"] == "non_zero_exit"


def test_measured_at_is_not_refreshed_by_reads(base, monkeypatch):
    clock = FakeClock(_utc())
    monkeypatch.setattr(du_module, "_utc_now", clock)
    path = _container_dir(base)
    cache = DiskUsageCache()
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _ok("55\t/path\n")

    monkeypatch.setattr(du_module.subprocess, "run", fake_run)

    assert cache.read_mount_usage([str(path)])[0]["pending"] is True
    first = _wait_for_settled(cache, str(path))
    assert first["bytes"] == 55
    assert first["measured_at"] == _utc_z(clock.now)

    clock.advance(100)
    second = cache.read_mount_usage([str(path)])[0]
    assert second["bytes"] == 55
    assert second["measured_at"] == first["measured_at"]
    assert len(calls) == 1


def test_real_du_on_local_temp_directory(base):
    """必要 du 只在 pytest 临时目录运行，不访问宿主用户目录。"""

    if shutil.which("du") is None:
        pytest.skip("du unavailable")
    path = _container_dir(base)
    (path / "data.bin").write_bytes(b"x" * 1024)
    cache = DiskUsageCache()

    assert cache.read_mount_usage([str(path)])[0]["pending"] is True
    settled = _wait_for_settled(cache, str(path))

    assert settled["error"] is None
    assert settled["pending"] is False
    assert settled["bytes"] >= 1024
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", settled["measured_at"])


def test_read_returns_pending_immediately_and_uses_six_hundred_second_timeout(base, monkeypatch):
    path = _container_dir(base)
    cache = DiskUsageCache()
    release = threading.Event()
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(kwargs)
        release.wait(5)
        return _ok()

    monkeypatch.setattr(du_module.subprocess, "run", fake_run)

    started = time.monotonic()
    result = cache.read_mount_usage([str(path)])[0]
    elapsed = time.monotonic() - started

    assert elapsed < 1.0, "HTTP 读取不得等待 du"
    assert result == {
        "path": str(path),
        "bytes": None,
        "measured_at": None,
        "pending": True,
        "error": None,
    }
    _wait_until(lambda: len(calls) == 1, message="du did not start")
    assert calls[0]["timeout"] == BIND_DU_TIMEOUT_SEC == 600
    release.set()
    assert _wait_for_settled(cache, str(path))["bytes"] == 7


# ---------------------------------------------------------------------------
# 错误映射与失败冷却
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("non_zero_exit", "non_zero_exit"),
        ("permission_denied", "permission_denied"),
        ("empty_output", "empty_output"),
        ("parse_error", "parse_error"),
        ("negative", "parse_error"),
        ("timeout", "timeout"),
        ("du_unavailable", "du_unavailable"),
        ("du_failed", "du_failed"),
    ],
)
def test_stable_error_mapping(base, monkeypatch, case, expected):
    path = _container_dir(base)
    cache = DiskUsageCache()

    def fake_run(cmd, **kwargs):
        if case == "timeout":
            raise subprocess.TimeoutExpired(cmd, BIND_DU_TIMEOUT_SEC)
        if case == "du_unavailable":
            raise FileNotFoundError("du")
        if case == "du_failed":
            raise RuntimeError("boom")
        if case == "non_zero_exit":
            return SimpleNamespace(returncode=1, stdout="123\t/path\n", stderr="")
        if case == "permission_denied":
            return SimpleNamespace(
                returncode=1,
                stdout="",
                stderr="du: cannot read directory '/x': Permission denied\n",
            )
        if case == "empty_output":
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if case == "parse_error":
            return SimpleNamespace(returncode=0, stdout="not-a-number\n", stderr="")
        if case == "negative":
            return SimpleNamespace(returncode=0, stdout="-1\t/path\n", stderr="")
        raise AssertionError(case)

    monkeypatch.setattr(du_module.subprocess, "run", fake_run)

    assert cache.read_mount_usage([str(path)])[0]["pending"] is True
    settled = _wait_for_settled(cache, str(path))

    assert settled["bytes"] is None
    assert settled["measured_at"] is None
    assert settled["pending"] is False
    assert settled["error"] == expected
    assert settled["error"] != "0"


def test_failure_cooldown_blocks_retry_then_allows_after_sixty_seconds(base, monkeypatch):
    clock = FakeClock(_utc())
    monkeypatch.setattr(du_module, "_utc_now", clock)
    path = _container_dir(base)
    cache = DiskUsageCache()
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=1, stdout="", stderr="")

    monkeypatch.setattr(du_module.subprocess, "run", fake_run)

    assert cache.read_mount_usage([str(path)])[0]["pending"] is True
    first = _wait_for_settled(cache, str(path))
    assert first["error"] == "non_zero_exit"
    assert len(calls) == 1

    clock.advance(MOUNT_USAGE_FAILURE_COOLDOWN_SEC - 1)
    cooling = cache.read_mount_usage([str(path)])[0]
    assert cooling["error"] == "non_zero_exit"
    assert cooling["pending"] is False
    assert cooling["bytes"] is None
    assert len(calls) == 1, "冷却内不得重复起 du"

    clock.advance(2)
    retried = cache.read_mount_usage([str(path)])[0]
    assert retried["pending"] is True
    assert retried["bytes"] is None
    _wait_until(lambda: len(calls) == 2, message="cooldown did not allow retry")
    assert _wait_for_settled(cache, str(path))["error"] == "non_zero_exit"


# ---------------------------------------------------------------------------
# singleflight、并发上限与去重回显
# ---------------------------------------------------------------------------


def test_singleflight_duplicate_aliases_share_one_du_and_keep_all_items(base, monkeypatch):
    path = _container_dir(base)
    cache = DiskUsageCache()
    release = threading.Event()
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        release.wait(5)
        return _ok("88\t/path\n")

    monkeypatch.setattr(du_module.subprocess, "run", fake_run)
    barrier = threading.Barrier(2)
    outputs = []

    def read_once():
        barrier.wait(5)
        outputs.append(cache.read_mount_usage([str(path)])[0])

    first = threading.Thread(target=read_once)
    second = threading.Thread(target=read_once)
    first.start()
    second.start()
    first.join(5)
    second.join(5)
    assert not first.is_alive() and not second.is_alive()
    assert len(outputs) == 2
    assert all(item["pending"] is True for item in outputs)
    _wait_until(lambda: len(calls) == 1, message="du did not start")
    assert len(calls) == 1, "并发同路径只允许一个 du"

    aliases = [str(path), f"{path}/", f"{path}/."]
    repeated = cache.read_mount_usage(aliases)
    assert [item["path"] for item in repeated] == aliases
    assert len(repeated) == 3
    assert all(item["pending"] is True for item in repeated)
    assert len(calls) == 1, "同批重复/别名不得重复启动 du"

    release.set()
    settled = _wait_for_settled(cache, str(path))
    assert settled["bytes"] == 88
    assert settled["measured_at"].endswith("Z")


def test_hundred_paths_run_at_most_four_du_and_http_returns_pending(base, monkeypatch):
    paths = [_container_dir(base, f"c{i}") for i in range(100)]
    cache = DiskUsageCache()
    release = threading.Event()
    lock = threading.Lock()
    active = 0
    max_active = 0
    calls = []

    def fake_run(cmd, **kwargs):
        nonlocal active, max_active
        with lock:
            calls.append(cmd)
            active += 1
            max_active = max(max_active, active)
        release.wait(5)
        with lock:
            active -= 1
        return _ok("10\t/path\n")

    monkeypatch.setattr(du_module.subprocess, "run", fake_run)

    started = time.monotonic()
    results = cache.read_mount_usage([str(path) for path in paths])
    elapsed = time.monotonic() - started

    assert elapsed < 2.0, "100 条批次也必须立即返回 pending"
    assert len(results) == 100
    assert all(item["pending"] is True for item in results)
    _wait_until(lambda: len(calls) >= MOUNT_USAGE_MAX_CONCURRENCY)
    with lock:
        assert max_active == MOUNT_USAGE_MAX_CONCURRENCY == 4
        assert len(calls) == MOUNT_USAGE_MAX_CONCURRENCY

    release.set()
    deadline = time.monotonic() + 10
    snapshot = []
    while time.monotonic() < deadline:
        snapshot = cache.read_mount_usage([str(path) for path in paths])
        if all(item["bytes"] == 10 and item["pending"] is False for item in snapshot):
            break
        time.sleep(0.01)
    assert len(snapshot) == 100
    assert all(item["bytes"] == 10 for item in snapshot)
    assert len(calls) == 100
    assert max_active <= 4


def test_cross_request_batches_share_global_four_worker_limit(base, monkeypatch):
    paths = [_container_dir(base, f"batch{i}") for i in range(16)]
    cache = DiskUsageCache()
    release = threading.Event()
    lock = threading.Lock()
    active = 0
    max_active = 0
    calls = []

    def fake_run(cmd, **kwargs):
        nonlocal active, max_active
        with lock:
            calls.append(cmd)
            active += 1
            max_active = max(max_active, active)
        release.wait(5)
        with lock:
            active -= 1
        return _ok("3\t/path\n")

    monkeypatch.setattr(du_module.subprocess, "run", fake_run)
    barrier = threading.Barrier(2)
    outputs = []

    def read_batch(batch):
        barrier.wait(5)
        outputs.append(cache.read_mount_usage([str(path) for path in batch]))

    first = threading.Thread(target=read_batch, args=(paths[:8],))
    second = threading.Thread(target=read_batch, args=(paths[8:],))
    first.start()
    second.start()
    first.join(5)
    second.join(5)
    assert not first.is_alive() and not second.is_alive()
    assert len(outputs) == 2
    assert all(len(batch) == 8 for batch in outputs)
    assert all(item["pending"] is True for batch in outputs for item in batch)

    _wait_until(lambda: len(calls) >= 4)
    with lock:
        assert max_active == 4
    release.set()
    _wait_until(lambda: len(calls) == 16, timeout=10)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        snapshot = cache.read_mount_usage([str(path) for path in paths])
        if all(item["bytes"] == 3 and item["pending"] is False for item in snapshot):
            break
        time.sleep(0.01)
    assert all(item["bytes"] == 3 for item in snapshot)
    with lock:
        assert max_active <= 4


# ---------------------------------------------------------------------------
# 清理检查与晚到结果
# ---------------------------------------------------------------------------


def test_cached_success_is_dropped_after_directory_removal(base, monkeypatch):
    path = _container_dir(base)
    cache = DiskUsageCache()
    key = _seed_success(cache, path, bytes_=123, measured_at=_utc_z())
    shutil.rmtree(path)
    calls = []

    def fail_run(*args, **kwargs):
        calls.append(args)
        raise AssertionError("not_found must not start du")

    monkeypatch.setattr(du_module.subprocess, "run", fail_run)

    result = cache.read_mount_usage([str(path)])[0]

    assert result["error"] == "not_found"
    assert result["bytes"] is None
    assert result["pending"] is False
    assert key not in cache._bind_cache
    assert calls == []


def _cleanup_harness(monkeypatch, base):
    path = _container_dir(base)
    cache = DiskUsageCache()
    release = threading.Event()
    started = threading.Event()
    completed = []
    original_collect = cache.collect_bind

    def wrapped_collect(*args, **kwargs):
        try:
            return original_collect(*args, **kwargs)
        finally:
            completed.append(args)

    monkeypatch.setattr(cache, "collect_bind", wrapped_collect)

    def fake_run(cmd, **kwargs):
        started.set()
        release.wait(5)
        return _ok("999\t/path\n")

    monkeypatch.setattr(du_module.subprocess, "run", fake_run)
    key = _norm_path(os.path.realpath(str(path)))
    return path, cache, key, release, started, completed


def test_measurement_during_cleanup_with_query_drops_late_success(base, monkeypatch):
    path, cache, key, release, started, completed = _cleanup_harness(monkeypatch, base)

    assert cache.read_mount_usage([str(path)])[0]["pending"] is True
    _wait_until(started.is_set, message="du did not start")

    shutil.rmtree(path)
    assert cache.read_mount_usage([str(path)])[0]["error"] == "not_found"
    assert key not in cache._bind_cache

    release.set()
    _wait_until(lambda: len(completed) >= 1, message="late du result was not consumed")
    entry = cache._bind_cache.get(key) or {}
    assert entry.get("bytes") is None
    assert entry.get("status") != "ok"
    assert cache.read_mount_usage([str(path)])[0]["error"] == "not_found"


def test_late_success_without_intervening_query_is_not_published(base, monkeypatch):
    path, cache, key, release, started, completed = _cleanup_harness(monkeypatch, base)

    assert cache.read_mount_usage([str(path)])[0]["pending"] is True
    _wait_until(started.is_set, message="du did not start")
    shutil.rmtree(path)

    # 清理后没有新查询：发布前复核仍必须丢弃晚到成功值。
    release.set()
    _wait_until(lambda: len(completed) >= 1, message="late du result was not consumed")
    entry = cache._bind_cache.get(key) or {}
    assert entry.get("bytes") is None
    assert entry.get("status") != "ok"

    assert cache.read_mount_usage([str(path)])[0]["error"] == "not_found"


def _queued_cleanup_harness(base, monkeypatch):
    """5 个目录：前 4 个 worker 被 fake du 卡住，第 5 个仍在队列。"""

    paths = [_container_dir(base, f"queued{i}") for i in range(5)]
    cache = DiskUsageCache()
    release = threading.Event()
    calls = []
    lock = threading.Lock()

    def fake_run(cmd, **kwargs):
        with lock:
            calls.append(cmd)
        release.wait(5)
        return _ok("9\t/path\n")

    monkeypatch.setattr(du_module.subprocess, "run", fake_run)
    results = cache.read_mount_usage([str(path) for path in paths])
    assert len(results) == 5
    assert all(item["pending"] is True for item in results)
    _wait_until(lambda: len(calls) == 4, message="four workers did not start")
    return paths, cache, release, calls, lock


def test_queued_deleted_path_is_not_measured(base, monkeypatch):
    paths, cache, release, calls, lock = _queued_cleanup_harness(base, monkeypatch)
    target = paths[-1]
    target_key = _norm_path(os.path.realpath(str(target)))

    shutil.rmtree(target)
    release.set()
    _wait_queue_idle(cache)

    with lock:
        measured = [cmd[-1] for cmd in calls]
    assert len(measured) == 4, "被清理的排队路径不得启动第 5 个 du"
    assert target_key not in measured
    result = cache.read_mount_usage([str(target)])[0]
    assert result["error"] == "not_found"
    assert result["bytes"] is None
    assert result["pending"] is False


def test_queued_symlink_replacement_is_not_measured(base, monkeypatch):
    paths, cache, release, calls, lock = _queued_cleanup_harness(base, monkeypatch)
    target = paths[-1]
    target_key = _norm_path(os.path.realpath(str(target)))
    replacement = _container_dir(base, "replacement")

    shutil.rmtree(target)
    try:
        os.symlink(str(replacement), str(target), target_is_directory=True)
    except (OSError, NotImplementedError):
        release.set()
        _wait_queue_idle(cache)
        pytest.skip("symlink not permitted in this environment")

    release.set()
    _wait_queue_idle(cache)

    with lock:
        measured = [cmd[-1] for cmd in calls]
    assert len(measured) == 4, "排队期间变成 symlink 的路径不得启动 du"
    assert target_key not in measured
    result = cache.read_mount_usage([str(target)])[0]
    assert result["error"] == "invalid_path"
    assert result["bytes"] is None


def test_queued_old_task_does_not_drop_recreated_path_new_task(base, monkeypatch):
    paths, cache, release, calls, lock = _queued_cleanup_harness(base, monkeypatch)
    target = paths[-1]
    target_key = _norm_path(os.path.realpath(str(target)))

    # 旧任务仍在队列：删除 → not_found 清缓存 → 重建 → 新任务入队。
    shutil.rmtree(target)
    assert cache.read_mount_usage([str(target)])[0]["error"] == "not_found"
    target.mkdir(parents=True)
    assert cache.read_mount_usage([str(target)])[0]["pending"] is True

    release.set()
    _wait_queue_idle(cache)

    with lock:
        measured = [cmd[-1] for cmd in calls]
    assert len(measured) == 5, "旧排队任务不得多跑 du，新任务必须测量一次"
    assert measured.count(target_key) == 1, "重建后的路径只允许新任务测量一次"
    settled = _wait_for_settled(cache, str(target))
    assert settled["bytes"] == 9
    assert settled["pending"] is False


def test_old_result_cannot_publish_after_path_recreated(base, monkeypatch):
    path = _container_dir(base)
    cache = DiskUsageCache()
    first_started = threading.Event()
    second_started = threading.Event()
    first_release = threading.Event()
    second_release = threading.Event()
    calls = []
    lock = threading.Lock()
    completed = []
    original_collect = cache.collect_bind

    def wrapped_collect(*args, **kwargs):
        try:
            return original_collect(*args, **kwargs)
        finally:
            completed.append(args)

    monkeypatch.setattr(cache, "collect_bind", wrapped_collect)

    def fake_run(cmd, **kwargs):
        with lock:
            calls.append(cmd)
            index = len(calls)
        if index == 1:
            first_started.set()
            first_release.wait(5)
            return _ok("111\t/path\n")
        second_started.set()
        second_release.wait(5)
        return _ok("222\t/path\n")

    monkeypatch.setattr(du_module.subprocess, "run", fake_run)
    key = _norm_path(os.path.realpath(str(path)))

    assert cache.read_mount_usage([str(path)])[0]["pending"] is True
    _wait_until(first_started.is_set, message="first du did not start")

    shutil.rmtree(path)
    assert cache.read_mount_usage([str(path)])[0]["error"] == "not_found"
    path.mkdir(parents=True)
    assert cache.read_mount_usage([str(path)])[0]["pending"] is True
    _wait_until(second_started.is_set, message="second du did not start")

    first_release.set()
    _wait_until(lambda: len(completed) >= 1, message="old du result was not consumed")
    entry = _entry(cache, key)
    assert entry.get("bytes") is None, "旧 du 结果不得发布到重建后的路径"
    assert entry.get("running") is True

    second_release.set()
    _wait_until(lambda: len(completed) >= 2, message="new du result was not consumed")
    settled = _wait_for_settled(cache, str(path))
    assert settled["bytes"] == 222
    assert settled["error"] is None
    assert len(calls) == 2
