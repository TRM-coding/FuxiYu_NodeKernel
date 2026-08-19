"""Node cache collectors.

These tests exercise the Docker-facing collection code with fake Docker SDK
objects. They are not real-daemon tests; real Docker coverage should be added
under the explicit ``docker`` marker.
"""

import datetime as dt
import subprocess

from FuxiYu_NodeKernel import extensions
from FuxiYu_NodeKernel.docker_operates.disk_usage_cache import DiskUsageCache
from FuxiYu_NodeKernel.docker_operates.status_cache import ContainerStatusCache
from FuxiYu_NodeKernel.docker_operates.sys_cache import SysSnapshotCache
from FuxiYu_NodeKernel.network import wss


class _Container:
    def __init__(self, name="c1", status="running", *, size_rw=1024, mount_source="/tmp/c1-root", exec_exit_code=0):
        self.name = name
        self.id = f"id-{name}"
        self.status = status
        self.attrs = {
            "SizeRw": size_rw,
            "State": {"Status": status},
            "Mounts": [{"Type": "bind", "Destination": "/root", "Source": mount_source}],
        }
        self._exec_exit_code = exec_exit_code

    def exec_run(self, *args, **kwargs):
        class _Result:
            exit_code = self._exec_exit_code

            def __getitem__(self, index):
                if index == 0:
                    return self.exit_code
                raise IndexError(index)

        return _Result()


class _Containers:
    def __init__(self, containers):
        self._containers = list(containers)

    def get(self, name_or_id):
        for container in self._containers:
            if container.name == name_or_id or container.id == name_or_id:
                return container
        import docker

        raise docker.errors.NotFound("missing")

    def list(self, *args, **kwargs):
        return list(self._containers)


class _DockerClient:
    def __init__(self, containers):
        self.containers = _Containers(containers)

    def df(self):
        return {"Containers": [{"Names": ["/c1"], "SizeRw": 2048}]}


def test_status_cache_applies_events_pending_ready_and_deleted(monkeypatch):
    cache = ContainerStatusCache()
    cache._apply_event({"status": "start", "Actor": {"Attributes": {"name": "c1"}}})
    assert cache.get_state("c1")["status"] == "online"

    cache.begin_action("c1", "restart", "stopping")
    assert cache.get_state("c1")["source"] == "pending"
    assert cache.get_state("c1")["status"] == "stopping"

    cache.finish_action("c1", "online")
    assert cache.get_state("c1")["source"] == "cache"
    assert cache.get_state("c1")["status"] == "online"

    cache.mark_ready_check("creating-c")
    monkeypatch.setattr(cache, "_probe_sshd", lambda name: True)
    for name, entry in list(cache._cache.items()):
        if entry.get("ready_check") and cache._probe_sshd(name):
            cache.update(name, "online")
    assert cache.get_state("creating-c")["status"] == "online"

    cache.begin_action("vanished-c", "stop", "stopping")
    cache._cache["live-c"] = {
        "status": "online",
        "updated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
    }
    cache._apply_container(_Container("live-c", status="running"))
    live = {"live-c"}
    known = set(cache._cache) | set(cache._pending)
    for name in sorted(known - live):
        cache._cache.pop(name, None)
        cache._pending.pop(name, None)
        cache._deleted.append(name)
    assert cache.take_deleted() == ["c1", "creating-c", "vanished-c"]


def test_disk_usage_cache_collects_overlay_bind_and_snapshot(monkeypatch, tmp_path):
    bind_dir = tmp_path / "root"
    bind_dir.mkdir()
    container = _Container("c1", status="running", size_rw=4096, mount_source=str(bind_dir))
    monkeypatch.setattr(extensions, "docker_client", _DockerClient([container]))

    cache = DiskUsageCache()
    monkeypatch.setattr(cache, "get_bind", lambda path: {
        "bind_mount_bytes": 8192,
        "bind_mount_source": "fresh",
        "bind_mount_path": path,
    })
    monkeypatch.setattr(cache, "collect_machine_disk", lambda: {
        "total_gb": 100,
        "used_gb": 20,
        "free_gb": 80,
        "percent": 20,
    })

    cache.collect_container("c1")
    snap = cache.snapshot()

    usage = snap["containers"]["c1"]
    assert usage["overlay_rw_bytes"] == 4096
    assert usage["bind_mount_bytes"] == 8192
    assert usage["bind_mount_source"] == "fresh"
    assert usage["total_bytes"] == 12288
    assert snap["machine_disk"]["total_gb"] == 100


def test_disk_usage_cache_bind_cache_sources(monkeypatch, tmp_path):
    bind_dir = tmp_path / "bind"
    bind_dir.mkdir()
    (bind_dir / "data.txt").write_text("hello", encoding="utf-8")

    cache = DiskUsageCache()
    first = cache.get_bind(str(bind_dir))
    assert first["bind_mount_source"] == "measuring"

    cache.collect_bind(str(bind_dir))
    fresh = cache.get_bind(str(bind_dir))
    assert fresh["bind_mount_source"] == "fresh"
    assert fresh["bind_mount_bytes"] > 0


def test_sys_snapshot_cache_collects_vendor_aware_gpu(monkeypatch):
    cache = SysSnapshotCache()

    monkeypatch.setattr("FuxiYu_NodeKernel.docker_operates.sys_cache.psutil.cpu_count", lambda logical=True: 16 if logical else 8)
    monkeypatch.setattr("FuxiYu_NodeKernel.docker_operates.sys_cache.psutil.cpu_percent", lambda interval=0.1: 12.3)

    class _Memory:
        total = 32 * 1024**3
        used = 8 * 1024**3
        available = 24 * 1024**3
        percent = 25.0

    monkeypatch.setattr("FuxiYu_NodeKernel.docker_operates.sys_cache.psutil.virtual_memory", lambda: _Memory())
    monkeypatch.setattr(
        "FuxiYu_NodeKernel.docker_operates.sys_cache.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout="0, RTX 4090, 24576\n", stderr=""),
    )
    monkeypatch.setattr(cache, "_collect_disk", lambda: {"total_gb": 200, "used_gb": 50, "percent": 25})

    snap = cache.collect()
    static = cache.collect_static()

    assert snap["cpu"]["cores"] == 16
    assert snap["cpu"]["physical_cores"] == 8
    assert snap["memory"]["total_gb"] == 32
    assert snap["gpu"] == [{"vendor": "nvidia", "index": 0, "name": "RTX 4090", "memory_gb": 24.0}]
    assert static["cpu"] == {"cores": 16}
    assert static["gpu"][0]["vendor"] == "nvidia"


def test_wss_snapshot_batch_reads_all_cache_views(monkeypatch):
    identity = wss.NodeIdentity(uid="node-cache-test")
    monkeypatch.setattr(wss, "list_container_status", lambda: {"c1": {"source": "cache", "status": "online"}})
    monkeypatch.setattr(wss, "list_last_ssh", lambda: {"c1": {"last_ssh_connect_time": "2026-08-21T10:00:00"}})
    monkeypatch.setattr(wss, "list_disk_usage", lambda: {"machine_disk": {"total_gb": 100}, "containers": {}})
    monkeypatch.setattr(wss, "list_sys_snapshot", lambda: {"hostname": "node-it-01"})

    batch = wss.build_snapshot_batch(identity)

    assert batch["type"] == "snapshot_batch"
    assert batch["node_uid"] == "node-cache-test"
    topics = [frame["topic"] for frame in batch["payload"]]
    assert topics == ["container_status", "last_ssh", "disk_usage", "sys_snapshot"]
