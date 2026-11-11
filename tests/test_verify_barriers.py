"""verify-bind 4.1：路径/du/WSS/消费方交错的确定性轨迹。

用 Event 在 du 的实际 subprocess 边界阻塞，不靠 sleep 猜时序；用 Trace 记录
Docker inspect、actual 读取、候选枚举、路径发布、缓存回填、WSS 读取和本地
消费方处理。目标不是模拟 Ctrl，而是证明旧路径在途 du 不会污染新路径事实。
"""
from __future__ import annotations

import os
import subprocess
import threading

from FuxiYu_NodeKernel import extensions
from FuxiYu_NodeKernel.docker_operates.disk_usage_cache import DiskUsageCache, _norm_path
from FuxiYu_NodeKernel.network import wss

from .runtime_fakes import FakeRuntimeContainer, Trace, install_runtime


def _mount(path):
    return [{"Type": "bind", "Destination": "/root", "Source": str(path)}]


def _seed_bind(cache, path, size, trace):
    with cache._lock:
        entry = cache._bind_entry_locked(_norm_path(str(path)))
        entry["bytes"] = size
        entry["status"] = "ok"
        entry["reason"] = None
        entry["measured_at"] = "2026-10-18T00:00:00Z"
        entry["running"] = False
        entry["updated_at"] = None
        entry["request_id"] = 1
    trace.add("seed:bind")


def test_disk_barrier_trace_keeps_old_du_out_of_new_path(tmp_path, monkeypatch):
    base = tmp_path / "home"
    containers = base / "admin" / "containers"
    path_a = containers / "a"
    path_b = containers / "b"
    missing = containers / "missing"
    for path in (path_a, path_b):
        path.mkdir(parents=True)
    monkeypatch.setenv("NODE_CONTAINERS_BASE", str(base))
    trace = Trace()
    cache = DiskUsageCache()
    current = {"actual": path_a}

    def _identity(path):
        if path.startswith("/proc/"):
            trace.add("actual:read")
            actual = current["actual"]
            st = os.stat(actual)
            return st.st_dev, st.st_ino
        trace.add("candidate/source:stat")
        st = os.stat(path)
        return st.st_dev, st.st_ino

    cache._dir_identity = _identity
    original_bounded = cache._bounded_matches

    def _bounded(*args, **kwargs):
        trace.add("candidate:enum:start")
        result = original_bounded(*args, **kwargs)
        trace.add("candidate:enum:end")
        return result

    cache._bounded_matches = _bounded

    entered = threading.Event()
    release = threading.Event()

    def _run(args, **kwargs):
        if os.path.basename(args[-1]) == "a":
            trace.add("du:a:start")
            entered.set()
            assert release.wait(3)
            trace.add("du:a:return")
            return subprocess.CompletedProcess(args, 0, stdout="111\tpath\n", stderr="")
        trace.add("du:other:start")
        return subprocess.CompletedProcess(args, 0, stdout="222\tpath\n", stderr="")

    monkeypatch.setattr(
        "FuxiYu_NodeKernel.docker_operates.disk_usage_cache.subprocess.run",
        _run,
    )
    with cache._lock:
        entry_a = cache._bind_entry_locked(_norm_path(str(path_a)))
        entry_a["running"] = True
        entry_a["status"] = "measuring"
        entry_a["request_id"] = 1
    old_du = threading.Thread(target=cache.collect_bind, args=(str(path_a), "c1", 1))
    old_du.start()
    assert entered.wait(2)

    # 路径 A→B 的轻量核对：Source 已消失，靠 actual 在有界父目录唯一定位 B。
    current["actual"] = path_b
    _seed_bind(cache, path_b, 222, trace)
    container_b = FakeRuntimeContainer("c1", mounts=_mount(missing), size_rw=10)
    client = install_runtime(monkeypatch, [container_b])
    original_get = client.containers.get

    def _get(name):
        trace.add("docker:get")
        return original_get(name)

    client.containers.get = _get
    container_b.on_reload = lambda c: trace.add("docker:reload")
    original_verify = cache.verify_mount_path

    def _verify(*args, **kwargs):
        trace.add("path:verify:start")
        result = original_verify(*args, **kwargs)
        trace.add("path:verify:end")
        return result

    cache.verify_mount_path = _verify
    cache.collect_container("c1")
    trace.add("cache:fill")

    monkeypatch.setattr(extensions, "disk_usage_cache", cache)
    first = wss.build_disk_usage_snapshot()["payload"]["containers"]["c1"]
    trace.add("wss:read")

    # 本地独立消费方：只读当前业务路径/控制状态/真实测量时间。
    consumed = {
        "bind_mount_path": first["bind_mount_path"],
        "mount_path_status": first["mount_path_status"],
        "measured_at": first["measured_at"],
        "total_bytes": first["total_bytes"],
    }
    trace.add("consumer:apply")

    release.set()
    old_du.join(3)
    trace.add("old-du:joined")

    labels = trace.labels()
    for left, right in (
        ("du:a:start", "docker:get"),
        ("docker:get", "path:verify:start"),
        ("path:verify:start", "actual:read"),
        ("actual:read", "candidate:enum:start"),
        ("candidate:enum:start", "path:verify:end"),
        ("path:verify:end", "cache:fill"),
        ("cache:fill", "wss:read"),
        ("wss:read", "consumer:apply"),
        ("consumer:apply", "du:a:return"),
    ):
        assert labels.index(left) < labels.index(right), trace.labels()
    assert labels[labels.index("path:verify:start"):].count("docker:get") >= 1

    assert consumed["bind_mount_path"] == str(path_b)
    assert consumed["mount_path_status"] == "resolved"
    assert consumed["total_bytes"] == 232
    after = wss.build_disk_usage_snapshot()["payload"]["containers"]["c1"]
    assert after["bind_mount_path"] == str(path_b)
    assert after["bind_mount_bytes"] == 222
    assert after["total_bytes"] == 232
    assert cache._bind_cache[_norm_path(str(path_a))]["bytes"] == 111
