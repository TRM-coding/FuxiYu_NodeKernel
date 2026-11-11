"""POST /api/check_mount_usage 的契约、只读边界与兼容测试。"""
import os
import re
import shutil
import subprocess
import threading
import time

import pytest
from fastapi.testclient import TestClient

from FuxiYu_NodeKernel import create_app, extensions
from FuxiYu_NodeKernel.docker_operates import disk_usage_cache as du_module
from FuxiYu_NodeKernel.docker_operates.disk_usage_cache import DiskUsageCache
from FuxiYu_NodeKernel.network import api as api_module
from FuxiYu_NodeKernel.network import wss
from FuxiYu_NodeKernel.services import container_service as cs

from .conftest import FakeDockerClient


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(extensions, "docker_client", FakeDockerClient())
    return TestClient(create_app())


def _patched_service(monkeypatch, name, fn):
    monkeypatch.setattr(api_module, name, fn)


def _container_dir(base, name="c1"):
    path = base / "alice" / "containers" / name
    path.mkdir(parents=True)
    return path


def _wait_until(predicate, timeout=5.0, message="condition not reached"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    raise AssertionError(message)


@pytest.fixture()
def base(tmp_path, monkeypatch):
    containers_base = tmp_path / "fuxi-base"
    containers_base.mkdir()
    monkeypatch.setenv("NODE_CONTAINERS_BASE", str(containers_base))
    return containers_base


def test_openapi_registers_real_api_path(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/check_mount_usage" in paths
    assert "post" in paths["/api/check_mount_usage"]
    assert "/check_mount_usage" not in paths


def test_valid_batch_preserves_order_duplicates_and_mixed_states(client, monkeypatch):
    paths = [
        "/home/alice/containers/c1",
        "/home/alice/containers/c2",
        "/home/alice/containers/c1",
        "/home/alice/containers/c3",
    ]
    mounts = [
        {
            "path": paths[0],
            "bytes": 123,
            "measured_at": "2026-10-20T08:00:00Z",
            "pending": False,
            "error": None,
        },
        {
            "path": paths[1],
            "bytes": None,
            "measured_at": None,
            "pending": True,
            "error": None,
        },
        {
            "path": paths[2],
            "bytes": 123,
            "measured_at": "2026-10-20T08:00:00Z",
            "pending": False,
            "error": None,
        },
        {
            "path": paths[3],
            "bytes": None,
            "measured_at": None,
            "pending": False,
            "error": "permission_denied",
        },
    ]
    calls = []

    def _stub(mount_paths):
        calls.append(list(mount_paths))
        return mounts

    _patched_service(monkeypatch, "check_mount_usage", _stub)
    resp = client.post("/api/check_mount_usage", json={"config": {"mount_paths": paths}})

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] == 1
    assert body["mounts"] == mounts
    assert calls == [paths]
    for item in body["mounts"]:
        assert set(item) == {"path", "bytes", "measured_at", "pending", "error"}


@pytest.mark.parametrize(
    "payload",
    [
        {"config": {"mount_paths": []}},
        {"config": {"mount_paths": [f"/home/a/containers/c{i}" for i in range(101)]}},
        {"config": {}},
        {},
        {"config": {"mount_paths": "not-a-list"}},
        {"config": {"mount_paths": [1]}},
        {"config": {"mount_paths": ["/home/a/containers/c1", 2]}},
    ],
)
def test_shape_errors_return_422_before_any_measurement(client, monkeypatch, payload):
    calls = []
    _patched_service(monkeypatch, "check_mount_usage", lambda paths: calls.append(paths) or [])

    resp = client.post("/api/check_mount_usage", json=payload)

    assert resp.status_code == 422
    assert calls == []
    assert "mounts" not in resp.json()


def test_internal_error_returns_500_without_partial_result(client, monkeypatch):
    def _boom(paths):
        raise RuntimeError("secret internal detail")

    _patched_service(monkeypatch, "check_mount_usage", _boom)
    resp = client.post(
        "/api/check_mount_usage",
        json={"config": {"mount_paths": ["/home/alice/containers/c1"]}},
    )

    assert resp.status_code == 500
    body = resp.json()
    assert body["success"] == 0
    assert body["error_reason"] == "internal_error"
    assert "mounts" not in body
    assert "secret internal detail" not in resp.text


@pytest.mark.parametrize(
    "payload",
    [
        {
            "config": {
                "mount_paths": ["/home/alice/containers/c1"],
                "deleted_id": 7,
            }
        },
        {
            "config": {
                "mount_paths": ["/home/alice/containers/c1"],
                "machine_id": "machine-1",
            }
        },
        {
            "config": {
                "mount_paths": ["/home/alice/containers/c1"],
                "container_name": "c1",
            }
        },
        {
            "config": {
                "mount_paths": ["/home/alice/containers/c1"],
                "role": "admin",
            }
        },
        {
            "config": {"mount_paths": ["/home/alice/containers/c1"]},
            "deleted_id": 7,
        },
        {
            "config": {"mount_paths": ["/home/alice/containers/c1"]},
            "machine_id": "machine-1",
        },
        {
            "config": {"mount_paths": ["/home/alice/containers/c1"]},
            "container_name": "c1",
        },
        {
            "config": {"mount_paths": ["/home/alice/containers/c1"]},
            "role": "admin",
        },
    ],
)
def test_identity_fields_inside_or_outside_config_are_422_and_not_measured(
    client, monkeypatch, payload
):
    calls = []
    _patched_service(monkeypatch, "check_mount_usage", lambda paths: calls.append(paths) or [])

    resp = client.post("/api/check_mount_usage", json=payload)

    assert resp.status_code == 422
    assert calls == []
    assert "mounts" not in resp.json()


def test_endpoint_uses_cache_bridge_for_pending_to_success(client, base, monkeypatch):
    path = _container_dir(base)
    outside = base.parent / "outside" / "containers" / "c1"
    outside.mkdir(parents=True)
    cache = DiskUsageCache()
    monkeypatch.setattr(extensions, "disk_usage_cache", cache)

    release = threading.Event()
    started = threading.Event()
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        started.set()
        release.wait(5)
        return type("R", (), {"returncode": 0, "stdout": "42\t/path\n", "stderr": ""})()

    monkeypatch.setattr(du_module.subprocess, "run", fake_run)
    paths = [str(path), str(outside), str(path)]

    first = client.post("/api/check_mount_usage", json={"config": {"mount_paths": paths}})
    assert first.status_code == 200
    first_mounts = first.json()["mounts"]
    assert [item["path"] for item in first_mounts] == paths
    assert first_mounts[0]["pending"] is True
    assert first_mounts[1]["error"] == "invalid_path"
    assert first_mounts[2]["path"] == str(path)

    _wait_until(started.is_set, message="du did not start")
    release.set()

    deadline = time.monotonic() + 5
    body = None
    while time.monotonic() < deadline:
        resp = client.post("/api/check_mount_usage", json={"config": {"mount_paths": paths}})
        body = resp.json()
        if body["mounts"][0]["pending"] is False:
            break
        time.sleep(0.01)

    assert body["success"] == 1
    assert body["mounts"][0]["path"] == str(path)
    assert body["mounts"][2]["path"] == str(path)
    assert body["mounts"][0]["bytes"] == 42
    assert body["mounts"][2]["bytes"] == 42
    assert body["mounts"][0]["measured_at"] == body["mounts"][2]["measured_at"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", body["mounts"][0]["measured_at"])
    assert body["mounts"][0]["pending"] is False
    assert body["mounts"][0]["error"] is None
    assert body["mounts"][1]["error"] == "invalid_path"
    assert len(calls) == 1


def test_real_http_du_pending_success_cache_hit_then_not_found(client, base, monkeypatch):
    """真实 HTTP + 本地 tmp 目录真实 du，全程不触碰 Docker/SSH。

    TestClient 未作为 context manager 使用，不触发 lifespan；缓存由测试直接注入。
    """

    if shutil.which("du") is None:
        pytest.skip("du unavailable")
    path = _container_dir(base)
    (path / "data.bin").write_bytes(b"y" * 2048)
    cache = DiskUsageCache()
    monkeypatch.setattr(extensions, "disk_usage_cache", cache)
    monkeypatch.setattr(extensions, "docker_client", None)
    docker_init = []
    monkeypatch.setattr(extensions, "init_docker", lambda: docker_init.append(1))

    cleanup_calls = []
    monkeypatch.setattr(cs, "clean_mount", lambda mount_path: cleanup_calls.append(mount_path) or True)
    monkeypatch.setattr(
        api_module,
        "clean_mount",
        lambda mount_path: cleanup_calls.append(mount_path) or True,
    )

    real_run = subprocess.run
    du_calls = []

    def counting_run(cmd, **kwargs):
        du_calls.append(list(cmd))
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(du_module.subprocess, "run", counting_run)
    payload = {"config": {"mount_paths": [str(path)]}}

    first = client.post("/api/check_mount_usage", json=payload)
    assert first.status_code == 200
    first_item = first.json()["mounts"][0]
    assert first_item["pending"] is True
    assert first_item["bytes"] is None
    assert first_item["measured_at"] is None

    deadline = time.monotonic() + 10
    item = None
    while time.monotonic() < deadline:
        resp = client.post("/api/check_mount_usage", json=payload)
        assert resp.status_code == 200
        item = resp.json()["mounts"][0]
        if item["pending"] is False:
            break
        time.sleep(0.01)

    assert item is not None
    assert item["pending"] is False
    assert item["error"] is None
    assert item["bytes"] >= 2048
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", item["measured_at"])
    assert len(du_calls) == 1

    hit = client.post("/api/check_mount_usage", json=payload).json()["mounts"][0]
    assert hit["bytes"] == item["bytes"]
    assert hit["measured_at"] == item["measured_at"]
    assert hit["pending"] is False
    assert hit["error"] is None
    assert len(du_calls) == 1, "TTL 内命中不得重复 du"

    shutil.rmtree(path)
    gone = client.post("/api/check_mount_usage", json=payload).json()["mounts"][0]
    assert gone["error"] == "not_found"
    assert gone["bytes"] is None
    assert gone["measured_at"] is None
    assert gone["pending"] is False
    assert len(du_calls) == 1, "已清理目录不得再启动 du"

    assert docker_init == []
    assert cleanup_calls == []
    assert cache._container_cache == {}
    assert cache._path_state == {}


def test_query_has_no_cleanup_docker_or_wss_side_effects(client, base, monkeypatch):
    path = _container_dir(base)
    cache = DiskUsageCache()
    monkeypatch.setattr(extensions, "disk_usage_cache", cache)
    monkeypatch.setattr(extensions, "docker_client", None)

    counters = {
        "clean_mount": 0,
        "api_clean_mount": 0,
        "verify_mount_path": 0,
        "collect_container": 0,
        "wss_disk": 0,
        "wss_batch": 0,
        "docker_init": 0,
        "du": 0,
        "rm": 0,
    }

    def count(name, result=None):
        def _record(*args, **kwargs):
            counters[name] += 1
            return result

        return _record

    monkeypatch.setattr(cs, "clean_mount", count("clean_mount", True))
    monkeypatch.setattr(api_module, "clean_mount", count("api_clean_mount", True))
    monkeypatch.setattr(cache, "verify_mount_path", count("verify_mount_path"))
    monkeypatch.setattr(cache, "collect_container", count("collect_container"))
    monkeypatch.setattr(wss, "build_disk_usage_snapshot", count("wss_disk", {}))
    monkeypatch.setattr(wss, "build_snapshot_batch", count("wss_batch", {}))
    monkeypatch.setattr(extensions, "init_docker", count("docker_init", None))

    def fake_run(cmd, **kwargs):
        if cmd and cmd[0] == "du":
            counters["du"] += 1
        if cmd and cmd[0] == "rm":
            counters["rm"] += 1
        return type("R", (), {"returncode": 0, "stdout": "5\t/path\n", "stderr": ""})()

    monkeypatch.setattr(du_module.subprocess, "run", fake_run)

    resp = client.post(
        "/api/check_mount_usage",
        json={"config": {"mount_paths": [str(path)]}},
    )
    assert resp.status_code == 200
    _wait_until(lambda: counters["du"] == 1, message="du did not run")
    _wait_until(
        lambda: client.post(
            "/api/check_mount_usage",
            json={"config": {"mount_paths": [str(path)]}},
        ).json()["mounts"][0]["pending"]
        is False,
        message="measurement did not settle",
    )

    assert counters["clean_mount"] == 0
    assert counters["api_clean_mount"] == 0
    assert counters["verify_mount_path"] == 0
    assert counters["collect_container"] == 0
    assert counters["wss_disk"] == 0
    assert counters["wss_batch"] == 0
    assert counters["rm"] == 0
    assert cache._container_cache == {}
    assert cache._path_state == {}


def test_cache_hit_then_cleanup_returns_not_found_without_du(client, base, monkeypatch):
    path = _container_dir(base)
    cache = DiskUsageCache()
    monkeypatch.setattr(extensions, "disk_usage_cache", cache)
    key = du_module._norm_path(os.path.realpath(str(path)))
    with cache._lock:
        entry = cache._bind_entry_locked(key)
        entry.update(
            {
                "bytes": 321,
                "status": "ok",
                "reason": None,
                "measured_at": du_module._utc_z(),
                "running": False,
                "request_id": 0,
                "failed_at": None,
            }
        )
    shutil.rmtree(path)
    calls = []
    monkeypatch.setattr(
        du_module.subprocess,
        "run",
        lambda *args, **kwargs: calls.append(args) or type(
            "R", (), {"returncode": 0, "stdout": "0\t/path\n", "stderr": ""}
        )(),
    )

    resp = client.post(
        "/api/check_mount_usage",
        json={"config": {"mount_paths": [str(path)]}},
    )

    assert resp.status_code == 200
    item = resp.json()["mounts"][0]
    assert item["error"] == "not_found"
    assert item["bytes"] is None
    assert item["pending"] is False
    assert calls == []
    assert key not in cache._bind_cache


def test_old_node_fallback_shapes_are_404_or_405(client):
    assert client.get("/api/check_mount_usage").status_code == 405
    assert client.post("/api/check_mount_usage_unknown").status_code == 404


def test_existing_check_disk_usage_contract_unchanged(client, monkeypatch):
    _patched_service(
        monkeypatch,
        "list_disk_usage",
        lambda: {
            "machine_disk": {"total_gb": 100, "used_gb": 20, "free_gb": 80, "percent": 20},
            "containers": {"c1": {"container_name": "c1", "total_bytes": 123}},
        },
    )
    resp = client.post("/api/check_disk_usage", json={"config": {"container_name": "c1"}})

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] == 1
    assert body["container"]["total_bytes"] == 123
    assert "mounts" not in body
