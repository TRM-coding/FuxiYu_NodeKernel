"""Node cache collectors.

These tests exercise the Docker-facing collection code with fake Docker SDK
objects. They are not real-daemon tests; real Docker coverage should be added
under the explicit ``docker`` marker.
"""

import asyncio
import datetime as dt
import json
import subprocess

from FuxiYu_NodeKernel import extensions
from FuxiYu_NodeKernel.constant import ContainerStatus
from FuxiYu_NodeKernel.docker_operates.disk_usage_cache import BIND_DU_TIMEOUT_SEC, DiskUsageCache
from FuxiYu_NodeKernel.docker_operates.status_cache import ContainerStatusCache
from FuxiYu_NodeKernel.docker_operates.sys_cache import SysSnapshotCache
from FuxiYu_NodeKernel.network import wss


class _FakeCtrlLink:
    """Ctrl 拨入侧的最小替身：记录 accept / close / 发出的帧。

    receive 立即返回断开 → 推送循环发完一轮即退出，测试不会空转到下一个周期。
    被测的是真 `handle_ctrl_ws` 与真帧构造，不绕 build_snapshot_batch。
    """

    def __init__(self, uid: str | None):
        scope = {"query_string": f"uid={uid}".encode()} if uid else {"query_string": b""}
        self.scope = scope
        self.accepted = False
        self.close_calls = []
        self.frames = []

    async def accept(self):
        self.accepted = True

    async def close(self, code=None):
        self.close_calls.append(code)

    async def send_text(self, text):
        # 对齐 Starlette WebSocket 的真实 API：send() 收的是 ASGI 消息字典，
        # 字符串帧走 send_text()——替身按真接口命名，用错名字即报错。
        self.frames.append(json.loads(text))

    async def receive(self):
        return {"type": "websocket.disconnect", "code": 1000}


class _Container:
    def __init__(
        self,
        name="c1",
        status="running",
        *,
        size_rw=1024,
        mount_source="/tmp/c1-root",
        exec_exit_code=0,
        stats_payload=None,
        device_requests=None,
    ):
        self.name = name
        self.id = f"id-{name}"
        self.status = status
        self.attrs = {
            "SizeRw": size_rw,
            "State": {"Status": status},
            "Mounts": [{"Type": "bind", "Destination": "/root", "Source": mount_source}],
            "HostConfig": {"DeviceRequests": device_requests or []},
        }
        self._exec_exit_code = exec_exit_code
        self._stats_payload = stats_payload
        self.stats_kwargs = None

    def exec_run(self, *args, **kwargs):
        class _Result:
            exit_code = self._exec_exit_code

            def __getitem__(self, index):
                if index == 0:
                    return self.exit_code
                raise IndexError(index)

        return _Result()

    def stats(self, *args, **kwargs):
        self.stats_kwargs = dict(kwargs)
        if kwargs.get("decode") is True and kwargs.get("stream") is False:
            raise RuntimeError("decode is only available in conjunction with stream=True")
        if self._stats_payload is None:
            raise RuntimeError("stats not available")
        return self._stats_payload


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
    def __init__(self, containers, inspect_size_rw=2048):
        self.containers = _Containers(containers)
        self.api = self
        self.inspect_size_rw = inspect_size_rw
        self.inspect_calls = []
        self.df_called = False

    def _url(self, path, *args):
        return path.format(*args)

    def _get(self, url, params=None):
        self.inspect_calls.append((url, params))
        return {"url": url, "params": params}

    def _result(self, response, json=False):
        return {"SizeRw": self.inspect_size_rw}

    def df(self):
        self.df_called = True
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
    cache._apply_event({"status": "start", "Actor": {"Attributes": {"name": "creating-c"}}})
    assert cache.get_state("creating-c")["status"] == "starting"
    assert cache.get("creating-c")["ready_check"] is True

    cache.mark_ready_check("restarting-c", status=ContainerStatus.RESTARTING.value)
    cache._apply_event({"status": "start", "Actor": {"Attributes": {"name": "restarting-c"}}})
    assert cache.get_state("restarting-c")["status"] == ContainerStatus.RESTARTING.value
    assert cache.get("restarting-c")["ready_check"] is True

    monkeypatch.setattr(cache, "_probe_sshd", lambda name: True)
    for name, entry in list(cache._cache.items()):
        if entry.get("ready_check") and cache._probe_sshd(name):
            cache.update(name, "online")
    assert cache.get_state("creating-c")["status"] == "online"

    cache.begin_action("pending-c", "create", "creating")
    cache.begin_build("building-c")
    cache._cache["live-c"] = {
        "status": "online",
        "updated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
    }
    monkeypatch.setattr(
        "FuxiYu_NodeKernel.docker_operates.status_cache.docker.from_env",
        lambda: _DockerClient([_Container("live-c", status="running")]),
    )
    cache._reconcile_once()
    assert cache.take_deleted() == ["c1", "creating-c", "restarting-c"]
    assert cache.get_state("pending-c")["status"] == "creating"
    assert cache.get_state("building-c")["status"] == "building"


def test_status_cache_forgets_deleted_generation_on_sync_delete_or_new_create():
    """同步删除闭环/同名新建会作废旧 delete，避免误删新同名 DB 行。"""
    cache = ContainerStatusCache()
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    cache._cache["c1"] = {"status": "online", "updated_at": now}
    cache._pending["c1"] = {"status": "failed", "started_at": dt.datetime.utcnow()}
    cache._build_pending["c1"] = {"status": "building", "started_at": dt.datetime.utcnow()}
    cache._deleted = ["old", "c1", "c1"]

    cache.forget_container_generation("c1")

    assert cache.get_state("c1")["source"] == "miss"
    assert cache.take_deleted() == ["old"]

    cache._deleted = ["c2"]
    cache.begin_build("c2")
    assert cache.take_deleted() == []

    cache._deleted = ["c3"]
    cache.begin_action("c3", "create", "creating")
    assert cache.take_deleted() == []


def test_status_cache_snapshot_includes_runtime_metrics(monkeypatch):
    cache = ContainerStatusCache()
    stats_payload = {
        "cpu_stats": {
            "cpu_usage": {"total_usage": 300, "percpu_usage": [1, 1]},
            "system_cpu_usage": 3000,
            "online_cpus": 2,
        },
        "precpu_stats": {
            "cpu_usage": {"total_usage": 100},
            "system_cpu_usage": 1000,
        },
        "memory_stats": {
            "usage": 300 * 1024 * 1024,
            "limit": 1024 * 1024 * 1024,
            "stats": {"cache": 44 * 1024 * 1024},
        },
        "networks": {
            "eth0": {"rx_bytes": 2 * 1024 * 1024, "tx_bytes": 3 * 1024 * 1024},
        },
        "blkio_stats": {
            "io_service_bytes_recursive": [
                {"op": "Read", "value": 4 * 1024 * 1024},
                {"op": "Write", "value": 5 * 1024 * 1024},
            ],
        },
    }
    container = _Container(
        "metrics-c",
        status="running",
        stats_payload=stats_payload,
        device_requests=[{"DeviceIDs": ["0", "2"], "Capabilities": [["gpu"]]}],
    )
    monkeypatch.setattr(
        "FuxiYu_NodeKernel.docker_operates.status_cache.docker.from_env",
        lambda: _DockerClient([container]),
    )
    monkeypatch.setattr(
        "FuxiYu_NodeKernel.docker_operates.status_cache.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            0,
            stdout="0, RTX 4090, 33, 1024, 24576\n1, RTX 4090, 0, 0, 24576\n2, RTX 4090, 66, 2048, 24576\n",
            stderr="",
        ),
    )

    cache._reconcile_once()
    state = cache.list_states()["metrics-c"]

    assert container.stats_kwargs == {"stream": False}
    # 冷启动契约（2026-09）：docker running 但 cache 无记录 → ready_check(cold_verify)
    # 先推 unknown + cold_start_verify，probe 通过后才转 online——不再直接暴露 starting
    assert state["status"] == ContainerStatus.UNKNOWN.value
    assert state["status_source"] == "cold_start_verify"
    assert state["runtime_metrics"]["cpu_usage_percent"] == 20.0
    assert state["runtime_metrics"]["memory_usage_mb"] == 256.0
    assert state["runtime_metrics"]["memory_usage_percent"] == 25.0
    assert state["runtime_metrics"]["network_rx_mb"] == 2.0
    assert state["runtime_metrics"]["network_tx_mb"] == 3.0
    assert state["runtime_metrics"]["block_read_mb"] == 4.0
    assert state["runtime_metrics"]["block_write_mb"] == 5.0
    assert state["runtime_metrics"]["gpu"]["device_ids"] == ["0", "2"]
    assert state["runtime_metrics"]["gpu"]["devices"] == [
        {
            "vendor": "nvidia",
            "index": 0,
            "name": "RTX 4090",
            "utilization_gpu_percent": 33.0,
            "memory_used_mb": 1024.0,
            "memory_total_mb": 24576.0,
            "memory_usage_percent": 4.2,
        },
        {
            "vendor": "nvidia",
            "index": 2,
            "name": "RTX 4090",
            "utilization_gpu_percent": 66.0,
            "memory_used_mb": 2048.0,
            "memory_total_mb": 24576.0,
            "memory_usage_percent": 8.3,
        },
    ]


def test_status_cache_noise_events_never_touch_cache():
    # 数据通路对账契约 C2：噪声事件（attach/top/exec_*/resize/...）绝不落缓存
    cache = ContainerStatusCache()
    cache.update("c1", "online")
    for ev in ["attach", "top", "exec_start", "exec_detach", "resize", "copy", "health_status", "update"]:
        cache._apply_event({"status": ev, "Actor": {"Attributes": {"name": "c1"}}})
    assert cache.get_state("c1")["status"] == "online"


def test_status_cache_unrecognized_event_ignored_without_pollution():
    # 数据通路对账契约 C2：不可识别事件 → 忽略（unknown 不再回填缓存）
    cache = ContainerStatusCache()
    cache.update("c1", "online")
    cache._apply_event({"status": "some_future_event", "Actor": {"Attributes": {"name": "c1"}}})
    assert cache.get_state("c1")["status"] == "online"


class _ExecResult:
    def __init__(self, exit_code, output=b""):
        self.exit_code = exit_code
        self.output = output


def _fake_docker_client(container):
    class _Containers:
        def get(self, name):
            return container

    class _Client:
        containers = _Containers()

    return _Client()


def test_ensure_sshd_started_detects_not_installed(monkeypatch):
    # 保障：拉起失败且 exit=127/not found → not_installed（终态 FAILED 依据）
    cache = ContainerStatusCache()
    calls = []

    class _Container:
        def exec_run(self, *a, **k):
            calls.append(a)
            return _ExecResult(127, b"sh: 1: /usr/sbin/sshd: not found")

    monkeypatch.setattr(extensions, "docker_client", _fake_docker_client(_Container()))
    assert cache._ensure_sshd_started("c1") == "not_installed"
    assert calls


def test_ensure_sshd_started_started_and_transient(monkeypatch):
    cache = ContainerStatusCache()

    class _OkContainer:
        def exec_run(self, *a, **k):
            return _ExecResult(0, b"")

    monkeypatch.setattr(extensions, "docker_client", _fake_docker_client(_OkContainer()))
    assert cache._ensure_sshd_started("c1") == "started"

    class _ErrContainer:
        def exec_run(self, *a, **k):
            return _ExecResult(255, b"some transient error")

    monkeypatch.setattr(extensions, "docker_client", _fake_docker_client(_ErrContainer()))
    assert cache._ensure_sshd_started("c1") == "transient"

    class _BoomContainer:
        def exec_run(self, *a, **k):
            raise RuntimeError("exec failed")

    monkeypatch.setattr(extensions, "docker_client", _fake_docker_client(_BoomContainer()))
    assert cache._ensure_sshd_started("c1") == "transient"


def test_probe_marks_failed_when_sshd_missing(monkeypatch):
    # 探测失败 + 拉起发现 sshd 未装 → 终态 FAILED（等人工处置），清 ready_check
    cache = ContainerStatusCache()
    cache.mark_ready_check("c1")
    monkeypatch.setattr(cache, "_probe_sshd", lambda name: False)
    monkeypatch.setattr(cache, "_ensure_sshd_started", lambda name: "not_installed")

    cache._probe_ready_checks_once()

    state = cache.get_state("c1")
    assert state["status"] == "failed"
    assert state["failed_reason"] == "sshd_not_installed"
    assert cache.get("c1").get("ready_check") is not True


def test_probe_transient_keeps_starting(monkeypatch):
    cache = ContainerStatusCache()
    cache.mark_ready_check("c1")
    monkeypatch.setattr(cache, "_probe_sshd", lambda name: False)
    monkeypatch.setattr(cache, "_ensure_sshd_started", lambda name: "transient")

    cache._probe_ready_checks_once()

    assert cache.get_state("c1")["status"] == "starting"


def test_cold_start_created_container_marks_failed():
    # 冷启动 docker "created"（从未运行）= 陈旧半成品（create 中途炸/从未启动）→ FAILED
    cache = ContainerStatusCache()
    cache._apply_container(_Container("stale_c", status="created"))
    assert cache.get_state("stale_c")["status"] == "failed"


def test_failed_terminal_guard_not_resurrected_by_reconcile():
    # FAILED 终态守卫：对账不从 docker running 复活（恢复路径 = 平台操作 restart/删除重建）
    cache = ContainerStatusCache()
    cache.update("c1", "failed")
    cache._apply_container(_Container("c1", status="running"))
    assert cache.get_state("c1")["status"] == "failed"


def test_probe_self_heals_sshd_then_online(monkeypatch):
    # 保障：ready_check 容器 probe 未就绪 → 尝试拉起 sshd；下一轮就绪 → online
    cache = ContainerStatusCache()
    cache.mark_ready_check("c1")
    calls = []

    def _flaky_probe(name):
        calls.append("probe")
        return len(calls) >= 2  # 首轮失败，之后成功

    monkeypatch.setattr(cache, "_probe_sshd", _flaky_probe)
    monkeypatch.setattr(cache, "_ensure_sshd_started", lambda name: calls.append("fix"))

    cache._probe_ready_checks_once()
    assert calls == ["probe", "fix"]  # 未就绪 → 拉起被调用，仍 starting
    assert cache.get_state("c1")["status"] == "starting"

    cache._probe_ready_checks_once()
    assert cache.get_state("c1")["status"] == "online"  # 拉起后就绪 → online


def test_probe_ready_refreshes_runtime_metrics(monkeypatch):
    # probe 将 ready_check 升 online 时同步补一份 docker stats，避免首个 online 快照只有 GPU 壳。
    cache = ContainerStatusCache()
    stats_payload = {
        "cpu_stats": {
            "cpu_usage": {"total_usage": 300, "percpu_usage": [1, 1]},
            "system_cpu_usage": 3000,
            "online_cpus": 2,
        },
        "precpu_stats": {
            "cpu_usage": {"total_usage": 100},
            "system_cpu_usage": 1000,
        },
        "memory_stats": {
            "usage": 300 * 1024 * 1024,
            "limit": 1024 * 1024 * 1024,
            "stats": {"cache": 44 * 1024 * 1024},
        },
    }
    container = _Container("c1", status="running", stats_payload=stats_payload)
    cache.mark_ready_check("c1")
    monkeypatch.setattr(cache, "_probe_sshd", lambda name: True)
    monkeypatch.setattr(extensions, "docker_client", _fake_docker_client(container))
    monkeypatch.setattr(
        "FuxiYu_NodeKernel.docker_operates.status_cache._nvidia_gpu_runtime_by_index",
        lambda: {},
    )

    cache._probe_ready_checks_once()

    state = cache.get_state("c1")
    assert state["status"] == "online"
    assert state["runtime_metrics"]["cpu_usage_percent"] == 20.0
    assert state["runtime_metrics"]["memory_usage_mb"] == 256.0
    assert state["runtime_metrics"]["memory_usage_percent"] == 25.0


def test_status_cache_state_events_still_update_cache():
    cache = ContainerStatusCache()
    cache.update("c1", "online")
    cache._apply_event({"status": "die", "Actor": {"Attributes": {"name": "c1"}}})
    assert cache.get_state("c1")["status"] == "offline"


def test_status_cache_warm_up_reconcile_populates_cache(monkeypatch):
    # 数据通路对账契约 C1：启动 warm-up 对账回填缓存 → 首帧快照非空。
    # running 容器走冷启动复合确认（starting + ready_check），probe 验 :22 后才 online
    cache = ContainerStatusCache()
    monkeypatch.setattr(
        "FuxiYu_NodeKernel.docker_operates.status_cache.docker.from_env",
        lambda: _DockerClient([
            _Container("warm_c1", status="running"),
            _Container("warm_c2", status="exited"),
        ]),
    )
    cache._reconcile_once()
    assert cache.get_state("warm_c1")["status"] == "starting"
    assert cache.get("warm_c1")["ready_check"] is True
    assert cache.get_state("warm_c2")["status"] == "offline"
    assert cache.get_collect_error() is None

    # probe 就绪 → online（复合确认完成）
    monkeypatch.setattr(cache, "_probe_sshd", lambda name: True)
    cache._probe_ready_checks_once()
    assert cache.get_state("warm_c1")["status"] == "online"


def test_cold_start_running_container_waits_for_sshd_probe(monkeypatch):
    # 崩溃恢复复合确认：冷启动 running 容器不直接 online，probe 验 :22 后才 online；
    # 已有条目不再重挂 ready_check（无 15s 对账振荡）
    cache = ContainerStatusCache()
    cache._apply_container(_Container("cold_c1", status="running"))
    assert cache.get_state("cold_c1")["status"] == "starting"
    assert cache.get("cold_c1")["ready_check"] is True

    monkeypatch.setattr(cache, "_probe_sshd", lambda name: True)
    cache._probe_ready_checks_once()
    assert cache.get_state("cold_c1")["status"] == "online"

    # 对账再跑：已有 online 条目 → 不重挂 ready_check（振荡防护）
    cache._apply_container(_Container("cold_c1", status="running"))
    assert cache.get_state("cold_c1")["status"] == "online"
    assert cache.get("cold_c1").get("ready_check") is not True


def test_status_cache_reconcile_failure_sets_collect_error(monkeypatch):
    # 数据通路对账契约 C1：docker 卡死 → collect_error 置位（快照发显式形状，非空 dict）
    cache = ContainerStatusCache()
    monkeypatch.setattr(
        "FuxiYu_NodeKernel.docker_operates.status_cache.docker.from_env",
        lambda: (_ for _ in ()).throw(RuntimeError("docker daemon down")),
    )
    cache._reconcile_once()
    assert cache.get_collect_error() == "collect_failed"


def test_status_cache_reconcile_recovers_clears_collect_error(monkeypatch):
    cache = ContainerStatusCache()
    monkeypatch.setattr(
        "FuxiYu_NodeKernel.docker_operates.status_cache.docker.from_env",
        lambda: (_ for _ in ()).throw(RuntimeError("down")),
    )
    cache._reconcile_once()
    assert cache.get_collect_error() == "collect_failed"

    monkeypatch.setattr(
        "FuxiYu_NodeKernel.docker_operates.status_cache.docker.from_env",
        lambda: _DockerClient([_Container("recover_c1", status="running")]),
    )
    cache._reconcile_once()
    assert cache.get_collect_error() is None
    # 冷启动复合确认：running 容器落 starting + ready_check（probe 通过后才 online）
    assert cache.get_state("recover_c1")["status"] == "starting"
    assert cache.get("recover_c1")["ready_check"] is True


def test_wss_status_snapshot_sends_collect_error_shape(monkeypatch):
    # 数据通路对账契约 C1：collect_error 置位时快照发显式形状（Ctrl 置 FAILED）
    monkeypatch.setattr(extensions.status_cache, "get_collect_error", lambda: "collect_failed")
    frame = wss.build_status_snapshot()
    assert frame["payload"] == {"collect_error": "collect_failed"}


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
    assert usage["overlay_rw_source"] == "attrs"
    assert usage["bind_mount_bytes"] == 8192
    assert usage["bind_mount_source"] == "fresh"
    assert usage["total_bytes"] == 12288
    assert snap["machine_disk"]["total_gb"] == 100


def test_disk_usage_cache_collects_overlay_from_single_container_inspect_when_attrs_missing(monkeypatch):
    container = _Container("c1", status="running", size_rw=4096)
    del container.attrs["SizeRw"]
    client = _DockerClient([container], inspect_size_rw=2048)
    monkeypatch.setattr(extensions, "docker_client", client)

    cache = DiskUsageCache()
    result = cache.collect_overlay_rw("c1")

    assert result == {"overlay_rw_bytes": 2048, "overlay_rw_source": "inspect_size"}
    assert client.inspect_calls == [(f"/containers/{container.id}/json", {"size": 1})]
    assert client.df_called is False


def test_disk_usage_cache_overlay_failure_keeps_total_pending(monkeypatch):
    container = _Container("c1", status="running", size_rw=4096)
    monkeypatch.setattr(extensions, "docker_client", _DockerClient([container]))

    cache = DiskUsageCache()
    monkeypatch.setattr(cache, "collect_overlay_rw", lambda name: {
        "overlay_rw_bytes": None,
        "overlay_rw_source": "error",
        "overlay_rw_error": "inspect_size_failed",
    })
    monkeypatch.setattr(cache, "get_bind", lambda path: {
        "bind_mount_bytes": 8192,
        "bind_mount_source": "fresh",
        "bind_mount_path": path,
    })

    cache.collect_container("c1")
    usage = cache.snapshot()["containers"]["c1"]

    assert usage["overlay_rw_bytes"] is None
    assert usage["overlay_rw_source"] == "error"
    assert usage["overlay_rw_error"] == "inspect_size_failed"
    assert usage["bind_mount_bytes"] == 8192
    assert usage["total_bytes"] is None


def test_disk_usage_cache_bind_cache_sources(tmp_path):
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


def test_disk_usage_cache_collect_bind_uses_extended_du_timeout(monkeypatch, tmp_path):
    bind_dir = tmp_path / "bind"
    bind_dir.mkdir()
    calls = []

    def _run(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return subprocess.CompletedProcess(args[0], 0, stdout="5\t/path\n", stderr="")

    monkeypatch.setattr(
        "FuxiYu_NodeKernel.docker_operates.disk_usage_cache.subprocess.run",
        _run,
    )

    cache = DiskUsageCache()
    cache.collect_bind(str(bind_dir))

    assert calls[0]["kwargs"]["timeout"] == BIND_DU_TIMEOUT_SEC == 600


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
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout="0, RTX 4090, 1024, 24576, 33\n", stderr=""),
    )
    monkeypatch.setattr(cache, "_collect_disk", lambda: {"bind_mount": {"path": "/home", "total_gb": 200, "used_gb": 50, "percent": 25}, "docker_data": {"path": "/var/lib/docker", "total_gb": 100, "used_gb": 20, "percent": 20}})

    snap = cache.collect()
    static = cache.collect_static()

    assert snap["cpu"]["cores"] == 16
    assert snap["cpu"]["physical_cores"] == 8
    assert snap["memory"]["total_gb"] == 32
    assert snap["gpu"] == [{
        "vendor": "nvidia",
        "index": 0,
        "name": "RTX 4090",
        "memory_used_gb": 1.0,
        "memory_gb": 24.0,
        "utilization_gpu_percent": 33.0,
        "memory_usage_percent": 4.2,
    }]
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


def test_ctrl_link_accepts_matching_uid_and_pushes_snapshot(monkeypatch):
    """Ctrl 拨入且 uid 匹配 → 接受连接，首帧即全量 snapshot_batch（4 topics）。

    契约 C1/C7 承诺：真推送循环首帧非空、非错误形状，不绕 build_snapshot_batch。
    """
    ws = _FakeCtrlLink(uid="link-uid-ok")
    monkeypatch.setattr(wss, "load_node_identity", lambda: wss.NodeIdentity(uid="link-uid-ok"))
    monkeypatch.setattr(wss, "list_container_status", lambda: {"c1": {"source": "cache", "status": "online"}})
    monkeypatch.setattr(wss, "list_last_ssh", lambda: {"c1": {"last_ssh_connect_time": "2026-08-21T10:00:00"}})
    monkeypatch.setattr(wss, "list_disk_usage", lambda: {"machine_disk": {"total_gb": 100}, "containers": {}})
    monkeypatch.setattr(wss, "list_sys_snapshot", lambda: {"hostname": "node-it-01"})
    monkeypatch.setattr(extensions.status_cache, "take_deleted", lambda: [])

    asyncio.run(wss.handle_ctrl_ws(ws))

    assert ws.accepted is True
    assert ws.close_calls == []
    first = ws.frames[0]
    assert first["type"] == "snapshot_batch"
    assert first["node_uid"] == "link-uid-ok"
    topics = [f["topic"] for f in first["payload"]]
    assert topics == ["container_status", "last_ssh", "disk_usage", "sys_snapshot"]
    # 首帧快照非空（warm-up 保证；契约 C1 承诺）
    assert first["payload"][0]["payload"] != {}


def test_ctrl_link_sends_deleted_frames_before_snapshot(monkeypatch):
    """幽灵容器感知：本轮推送前先发 delete 帧，再发快照。"""
    ws = _FakeCtrlLink(uid="link-uid-del")
    monkeypatch.setattr(wss, "load_node_identity", lambda: wss.NodeIdentity(uid="link-uid-del"))
    monkeypatch.setattr(wss, "list_container_status", lambda: {})
    monkeypatch.setattr(wss, "list_last_ssh", lambda: {})
    monkeypatch.setattr(wss, "list_disk_usage", lambda: {"containers": {}})
    monkeypatch.setattr(wss, "list_sys_snapshot", lambda: {})
    monkeypatch.setattr(extensions.status_cache, "take_deleted", lambda: ["ghost-1"])

    asyncio.run(wss.handle_ctrl_ws(ws))

    assert ws.frames[0] == {"type": "delete", "container_name": "ghost-1"}
    assert ws.frames[1]["type"] == "snapshot_batch"


def test_ctrl_link_rejects_uid_mismatch(monkeypatch):
    """uid 与本机身份牌不一致 → 拒绝连接，不推任何帧。"""
    ws = _FakeCtrlLink(uid="wrong-uid")
    monkeypatch.setattr(wss, "load_node_identity", lambda: wss.NodeIdentity(uid="link-uid-real"))

    asyncio.run(wss.handle_ctrl_ws(ws))

    assert ws.accepted is False
    assert ws.close_calls == [4403]
    assert ws.frames == []


def test_ctrl_link_rejects_missing_uid(monkeypatch):
    """连接未携带 uid → 拒绝连接。"""
    ws = _FakeCtrlLink(uid=None)
    monkeypatch.setattr(wss, "load_node_identity", lambda: wss.NodeIdentity(uid="link-uid-real"))

    asyncio.run(wss.handle_ctrl_ws(ws))

    assert ws.accepted is False
    assert ws.close_calls == [4403]
    assert ws.frames == []


def test_ctrl_link_rejects_when_identity_not_initialized(monkeypatch):
    """身份牌未就绪 → 不开推送循环，等待 Ctrl 注册后重拨。"""
    ws = _FakeCtrlLink(uid="any-uid")
    monkeypatch.setattr(wss, "load_node_identity", lambda: None)

    asyncio.run(wss.handle_ctrl_ws(ws))

    assert ws.accepted is False
    assert ws.close_calls == [4404]
    assert ws.frames == []


def test_lifespan_starts_caches_without_outbound_pusher(monkeypatch):
    """换向后 Node 不再出站：lifespan 只启停采集缓存，不建立到 Ctrl 的连接。"""
    from FuxiYu_NodeKernel import lifespan as _lifespan

    calls = []
    monkeypatch.setattr(extensions.status_cache, "start", lambda: calls.append("warm"))
    monkeypatch.setattr(extensions.last_ssh_cache, "start", lambda: None)
    monkeypatch.setattr(extensions.disk_usage_cache, "start", lambda: None)
    monkeypatch.setattr(extensions.sys_cache, "start", lambda: None)
    monkeypatch.setattr(extensions.sys_cache, "stop", lambda: calls.append("stop"))

    class _App:
        state = type("_State", (), {})()

    async def _run():
        async with _lifespan(_App()):
            pass

    asyncio.run(_run())
    assert calls == ["warm", "stop"]


def test_ctrl_ca_trust_file_bootstraps_public_ca(monkeypatch, tmp_path):
    node_root = tmp_path / "FuxiYu_NodeKernel"
    source = tmp_path / "FuxiYu_CtrKernel" / "certs" / "ctrl_ca.pem"
    source.parent.mkdir(parents=True)
    source.write_text("public ctrl ca", encoding="utf-8")

    monkeypatch.setattr(wss, "_NODE_ROOT", node_root)
    monkeypatch.setattr(wss, "_candidate_local_ctrl_ca_files", lambda: [source])

    target = wss.ensure_ctrl_ca_trust_file()

    assert target == node_root / "certs" / "ctrl_ca.pem"
    assert target.read_text(encoding="utf-8") == "public ctrl ca"
