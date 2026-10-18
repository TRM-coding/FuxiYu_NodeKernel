"""guard-runtime-state-reconciliation 的真实入口回归。

测试走 status_cache / service / FastAPI / WSS 的真实入口，用可编程 Docker
替身与屏障控制交错；不直接伪造状态表结果，也不 sleep 猜时序。
"""
from __future__ import annotations

import json
import threading
import time

import docker
import pytest
from fastapi.testclient import TestClient

from FuxiYu_NodeKernel import create_app, extensions
from FuxiYu_NodeKernel.constant import ContainerStatus
from FuxiYu_NodeKernel.docker_operates.docker_fact import fact_from_container
from FuxiYu_NodeKernel.docker_operates.status_cache import (
    HARD_BLOCK_REASONS,
    ContainerStatusCache,
)
from FuxiYu_NodeKernel.network import api as api_module
from FuxiYu_NodeKernel.network import wss as wss_module
from FuxiYu_NodeKernel.services import container_service

from .runtime_fakes import FakeRuntimeContainer, FakeRuntimeContainers, install_runtime


def wait_for(predicate, timeout: float = 3.0, interval: float = 0.01):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def _publish(cache: ContainerStatusCache, name: str, container, *, source="test", mark_ready=False):
    ticket = cache.issue_observation(name, source)
    return cache.publish_observed(
        name,
        ticket,
        fact_from_container(container),
        mark_ready=mark_ready,
    )


def _seed_online(cache: ContainerStatusCache, name: str, container, *, source="seed"):
    assert _publish(cache, name, container, source=source, mark_ready=True)
    state = cache.get_state(name)
    assert state["status"] == ContainerStatus.ONLINE.value
    return state


def _finish(cache: ContainerStatusCache, name: str, ref: dict, phase: str, reason: str | None = None):
    return cache.finish_action_ref({**ref, "name": name}, phase, reason)


# ---------------------------------------------------------------------------
# 1. 状态表、读面优先级与动作结果分离
# ---------------------------------------------------------------------------


def test_action_failure_does_not_change_runtime_and_last_action_is_separate():
    cache = ContainerStatusCache()
    container = FakeRuntimeContainer("c1", status="running")
    _seed_online(cache, "c1", container)

    ref = cache.accept_action("c1", "pause", "pausing")
    _finish(cache, "c1", ref, "failed", "docker_api_error")

    state = cache.get_state("c1")
    assert state["status"] == ContainerStatus.ONLINE.value
    assert state["last_action"]["phase"] == "failed"
    assert state["last_action"]["action"] == "pause"
    assert state["last_action"]["ref"] == ref


def test_read_priority_hard_block_gate_transition_unknown():
    cache = ContainerStatusCache()

    # 硬阻塞 > 就绪门禁 > 受理过渡 > 运行态
    container = FakeRuntimeContainer("c-hard", status="running")
    _seed_online(cache, "c-hard", container)
    cache.mark_ready_check("c-hard")
    cache.set_hard_block("c-hard", "docker_dead", "dead")
    assert cache.get_state("c-hard")["status"] == ContainerStatus.FAILED.value

    container2 = FakeRuntimeContainer("c-gate", status="running")
    _seed_online(cache, "c-gate", container2)
    cache.mark_ready_check("c-gate", ContainerStatus.STARTING.value)
    cache.accept_action("c-gate", "pause", "pausing")
    st = cache.get_state("c-gate")
    assert st["status"] == ContainerStatus.STARTING.value
    assert st["ready_check"] is True

    container3 = FakeRuntimeContainer("c-trans", status="running")
    _seed_online(cache, "c-trans", container3)
    ref3 = cache.accept_action("c-trans", "pause", "pausing")
    assert cache.get_state("c-trans")["status"] == "pausing"
    _finish(cache, "c-trans", ref3, "failed", "docker_api_error")

    # unknown 保留最后已知，但对外不是 online/failed
    ticket = cache.issue_observation("c-trans", "collect_error")
    cache.publish_unknown("c-trans", ticket, reason="inspect_failed")
    st = cache.get_state("c-trans")
    assert st["status"] == ContainerStatus.UNKNOWN.value
    assert st["status_source"] == "inspect_failed"
    assert st["unknown_since"]
    assert st["last_known_status"] == "online"


def test_hard_block_reasons_are_bounded_and_action_soft_failure_not_failed():
    cache = ContainerStatusCache()
    container = FakeRuntimeContainer("c1", status="exited")
    _publish(cache, "c1", container)
    assert cache.get_state("c1")["status"] == ContainerStatus.OFFLINE.value

    cache.set_hard_block("c1", "sshd_not_installed", "no sshd")
    assert "sshd_not_installed" in HARD_BLOCK_REASONS
    assert cache.get_state("c1")["status"] == ContainerStatus.FAILED.value

    ref = cache.accept_action("c1", "unpause", "unpausing")
    _finish(cache, "c1", ref, "failed", "docker_api_error")
    assert cache.get_state("c1")["status"] == ContainerStatus.FAILED.value


def test_ready_identity_must_match_docker_id_and_started_at():
    cache = ContainerStatusCache()
    container = FakeRuntimeContainer("c1", status="running", started_at="2026-10-17T19:00:00Z")
    _publish(cache, "c1", container, mark_ready=True)
    assert cache.get_state("c1")["status"] == ContainerStatus.ONLINE.value

    # 同 Docker ID 外部重启：StartedAt 变化 → 重新门禁
    restarted = FakeRuntimeContainer(
        "c1", status="running", docker_id=container.id, started_at="2026-10-17T19:30:00Z"
    )
    _publish(cache, "c1", restarted)
    st = cache.get_state("c1")
    assert st["status"] == ContainerStatus.STARTING.value
    assert st["ready_check"] is True
    assert cache.get("c1")["ready_verified"] is False

    # 无 StartedAt 不得复用 ready
    no_started = FakeRuntimeContainer("c1", status="running", docker_id=container.id, started_at="")
    no_started.attrs["State"]["StartedAt"] = ""
    _publish(cache, "c1", no_started, mark_ready=True)
    assert cache.get("c1")["ready_verified"] is False


# ---------------------------------------------------------------------------
# 2. 共享代际、观察票与同名 Docker ID 更换
# ---------------------------------------------------------------------------


def test_valid_current_observation_drives_identity_change_and_supersedes_old_action():
    cache = ContainerStatusCache()
    old = FakeRuntimeContainer("c1", status="running", docker_id="A")
    _seed_online(cache, "c1", old)
    gen_before = cache._meta_for("c1")["generation"]
    ref = cache.accept_action("c1", "start", "starting")

    new = FakeRuntimeContainer("c1", status="running", docker_id="B")
    ticket = cache.issue_observation("c1", "reconcile", action_seq=ref["seq"])
    assert cache.publish_observed("c1", ticket, fact_from_container(new)) is True

    meta = cache._meta_for("c1")
    assert meta["generation"] == gen_before + 1
    assert cache.get("c1")["docker_id"] == "B"
    assert cache.get_state("c1")["last_action"]["phase"] == "superseded"
    assert cache.get_state("c1")["last_action"]["ref"] == ref
    assert cache.get_state("c1")["status"] == ContainerStatus.STARTING.value


def test_old_generation_late_observation_cannot_replace_again_or_cancel_new_pending():
    cache = ContainerStatusCache()
    old = FakeRuntimeContainer("c1", status="running", docker_id="A")
    _seed_online(cache, "c1", old)
    old_ticket = cache.issue_observation("c1", "reconcile")
    current = FakeRuntimeContainer("c1", status="running", docker_id="B")
    ticket = cache.issue_observation("c1", "reconcile")
    assert cache.publish_observed("c1", ticket, fact_from_container(current)) is True
    generation_after_change = cache._meta_for("c1")["generation"]

    # 旧代观察晚到看到 C：generation 必须先失败，不得再次换代。
    late = FakeRuntimeContainer("c1", status="running", docker_id="C")
    assert cache.publish_observed("c1", old_ticket, fact_from_container(late)) is False
    assert cache._meta_for("c1")["generation"] == generation_after_change
    assert cache.get("c1")["docker_id"] == "B"

    # 新代 create pending 不被旧观察取消。
    create_ref = cache.accept_action("c1", "create", "creating", create=True)
    assert cache._meta_for("c1")["create_pending"] is True
    assert cache.publish_observed("c1", old_ticket, fact_from_container(late)) is False
    assert cache._meta_for("c1")["create_pending"] is True
    assert cache._meta_for("c1")["generation"] == create_ref["generation"]


def test_create_first_bind_and_different_id_deferred():
    cache = ContainerStatusCache()
    ref = cache.accept_action("c1", "create", "creating", create=True)
    assert cache.get_state("c1")["status"] == ContainerStatus.CREATING.value
    gen = cache._meta_for("c1")["generation"]

    bind = FakeRuntimeContainer("c1", status="running", docker_id="B")
    ticket = cache.issue_observation("c1", "create", action_seq=ref["seq"], from_create_confirmation=True)
    assert cache.publish_observed("c1", ticket, fact_from_container(bind)) is True
    assert cache.get("c1")["docker_id"] == "B"
    assert cache._meta_for("c1")["generation"] == gen
    assert cache._meta_for("c1")["create_pending"] is True

    other = FakeRuntimeContainer("c1", status="running", docker_id="C")
    normal = cache.issue_observation("c1", "reconcile", action_seq=ref["seq"])
    assert cache.publish_observed("c1", normal, fact_from_container(other)) is False
    assert cache.get("c1")["docker_id"] == "B"
    assert cache._meta_for("c1")["generation"] == gen
    assert cache._meta_for("c1")["create_pending"] is True


def test_read_seq_cas_rejects_late_old_read_and_metrics_do_not_raise_sequences():
    cache = ContainerStatusCache()
    container = FakeRuntimeContainer("c1", status="running")
    _seed_online(cache, "c1", container)
    paused = FakeRuntimeContainer("c1", status="paused")

    t1 = cache.issue_observation("c1", "slow")
    t2 = cache.issue_observation("c1", "fast")
    assert cache.publish_observed("c1", t2, fact_from_container(paused)) is True
    assert cache.get_state("c1")["status"] == ContainerStatus.PAUSED.value
    # 早发起、晚返回的旧票（完成时间更晚）仍必须被 read_seq 拒绝。
    online = FakeRuntimeContainer("c1", status="running")
    assert cache.publish_observed("c1", t1, fact_from_container(online)) is False
    assert cache.get_state("c1")["status"] == ContainerStatus.PAUSED.value

    meta_before = dict(cache._meta_for("c1"))
    metrics_ticket = cache.issue_observation("c1", "stats", metrics=True)
    assert cache.publish_metrics("c1", metrics_ticket, {"cpu_usage_percent": 1.0}) is True
    meta_after = cache._meta_for("c1")
    assert meta_after["generation"] == meta_before["generation"]
    assert meta_after["action_seq"] == meta_before["action_seq"]
    assert meta_after["last_applied_read_seq"] == meta_before["last_applied_read_seq"]
    assert cache.get_state("c1")["runtime_metrics"]["cpu_usage_percent"] == 1.0


def test_stale_node_epoch_ticket_cannot_publish_after_restart():
    old = ContainerStatusCache()
    old_container = FakeRuntimeContainer("c1", status="running", docker_id="A")
    _seed_online(old, "c1", old_container)
    old_ticket = old.issue_observation("c1", "old-process")

    new = ContainerStatusCache()
    new_container = FakeRuntimeContainer("c1", status="exited", docker_id="A")
    _publish(new, "c1", new_container)
    before = new.get_state("c1")
    assert before["status"] == ContainerStatus.OFFLINE.value

    assert new.publish_observed("c1", old_ticket, fact_from_container(old_container)) is False

    after = new.get_state("c1")
    assert after["status"] == ContainerStatus.OFFLINE.value
    assert after["last_action"] is None


def test_metrics_ticket_is_invalidated_by_action_or_generation_change():
    cache = ContainerStatusCache()
    _seed_online(cache, "c1", FakeRuntimeContainer("c1", status="running"))
    metrics_ticket = cache.issue_observation("c1", "metrics", metrics=True)
    cache.accept_action("c1", "pause", "pausing")
    assert cache.publish_metrics("c1", metrics_ticket, {"cpu_usage_percent": 99.0}) is False
    assert cache.get("c1").get("runtime_metrics") is None
    assert cache._meta_for("c1")["last_applied_metrics_read_seq"] == 0

    cache2 = ContainerStatusCache()
    _seed_online(cache2, "c2", FakeRuntimeContainer("c2", status="running"))
    metrics_ticket2 = cache2.issue_observation("c2", "metrics", metrics=True)
    cache2.accept_action("c2", "create", "creating", create=True)
    assert cache2.publish_metrics("c2", metrics_ticket2, {"cpu_usage_percent": 99.0}) is False
    assert cache2.get("c2").get("runtime_metrics") is None
    assert cache2._meta_for("c2")["last_applied_metrics_read_seq"] == 0


def test_stale_unknown_ticket_cannot_overwrite_newer_runtime():
    cache = ContainerStatusCache()
    _seed_online(cache, "c1", FakeRuntimeContainer("c1", status="running"))
    stale = cache.issue_observation("c1", "stale-inspect")
    newer = cache.issue_observation("c1", "newer-inspect")
    offline = FakeRuntimeContainer("c1", status="exited")
    assert cache.publish_observed("c1", newer, fact_from_container(offline)) is True

    assert cache.publish_unknown("c1", stale, reason="late_collect_error") is False

    state = cache.get_state("c1")
    assert state["status"] == ContainerStatus.OFFLINE.value
    assert state.get("status_source") is None
    assert cache.get("c1")["status"] == ContainerStatus.OFFLINE.value


def test_finish_old_ref_is_superseded_and_never_overwrites_new_ref():
    cache = ContainerStatusCache()
    container = FakeRuntimeContainer("c1", status="running")
    _seed_online(cache, "c1", container)
    ref1 = cache.accept_action("c1", "pause", "pausing")
    ref2 = cache.accept_action("c1", "unpause", "unpausing")
    assert cache.finish_action_ref({**ref1, "name": "c1"}, "confirmed") is False
    assert cache.get_state("c1")["last_action"]["ref"] == ref2
    assert cache.get_state("c1")["status"] == "unpausing"
    assert cache.finish_action_ref({**ref2, "name": "c1"}, "idempotent_confirmed") is True
    assert cache.get_state("c1")["status"] == ContainerStatus.ONLINE.value
    assert cache.get_state("c1")["last_action"]["phase"] == "idempotent_confirmed"


# ---------------------------------------------------------------------------
# 3. 动作队列、后台线程失败与冷启动
# ---------------------------------------------------------------------------


def test_per_name_action_queue_is_serial_and_other_containers_are_independent():
    cache = ContainerStatusCache()
    order = []
    gate = threading.Event()

    def runner(ref, name, index):
        order.append(f"{name}-{index}-start")
        if name == "c1" and index == 0:
            gate.wait(2)
        order.append(f"{name}-{index}-end")
        return type("O", (), {"phase": "confirmed", "error_reason": None})()

    ref1 = cache.submit_action("c1", "pause", "pausing", lambda ref: runner(ref, "c1", 0))
    ref2 = cache.submit_action("c1", "unpause", "unpausing", lambda ref: runner(ref, "c1", 1))
    ref3 = cache.submit_action("c2", "start", "starting", lambda ref: runner(ref, "c2", 0))
    gate.set()

    assert wait_for(
        lambda: cache.get_state("c1")["last_action"]["ref"] == ref2
        and cache.get_state("c1")["last_action"]["phase"] == "confirmed"
    )
    assert wait_for(
        lambda: cache.get_state("c2")["last_action"]["ref"] == ref3
        and cache.get_state("c2")["last_action"]["phase"] == "confirmed"
    )
    assert order.index("c1-0-end") < order.index("c1-1-start")
    assert order.index("c2-0-end") >= 0


def test_background_thread_start_failure_marks_action_failed_not_runtime_failed():
    cache = ContainerStatusCache()
    container = FakeRuntimeContainer("c1", status="running")
    _seed_online(cache, "c1", container)

    class _BadThread:
        def __init__(self, *a, **k):
            pass

        def start(self):
            raise RuntimeError("thread start failed")

    import FuxiYu_NodeKernel.docker_operates.status_cache as status_module

    original = status_module.threading.Thread
    status_module.threading.Thread = _BadThread
    try:
        with pytest.raises(RuntimeError, match="thread start failed"):
            cache.submit_action("c1", "pause", "pausing", lambda ref: None)
    finally:
        status_module.threading.Thread = original

    state = cache.get_state("c1")
    assert state["status"] == ContainerStatus.ONLINE.value
    assert state["last_action"]["phase"] == "failed"
    assert state["last_action"]["error_reason"] == "background_thread_failed"


def test_failed_submission_not_reexecuted_after_next_submission_starts_worker():
    """启动失败项的副作用不能被下一请求重新执行；有效请求仍按序执行。"""
    cache = ContainerStatusCache()
    container = FakeRuntimeContainer("c1", status="running")
    _seed_online(cache, "c1", container)
    executed = []

    def first_runner(ref):
        executed.append("failed_submission")
        return type("O", (), {"phase": "confirmed", "error_reason": None, "detail": None})()

    import FuxiYu_NodeKernel.docker_operates.status_cache as status_module

    original_thread = status_module.threading.Thread

    class _BadThread:
        def __init__(self, *a, **k):
            pass

        def start(self):
            raise RuntimeError("thread start failed")

    status_module.threading.Thread = _BadThread
    try:
        with pytest.raises(RuntimeError, match="thread start failed"):
            cache.submit_action("c1", "pause", "pausing", first_runner)
    finally:
        status_module.threading.Thread = original_thread

    meta = cache._meta_for("c1")
    first_record = meta["last_action"]
    first_ref = dict(first_record.ref)
    assert first_record.phase == "failed"
    assert first_record.error_reason == "background_thread_failed"
    assert "c1" not in cache._action_queues

    def second_runner(ref):
        executed.append("next_submission")
        return type("O", (), {"phase": "confirmed", "error_reason": None, "detail": None})()

    second_ref = cache.submit_action("c1", "start", "starting", second_runner)
    assert wait_for(lambda: cache.get_state("c1")["last_action"]["ref"] == second_ref)
    assert wait_for(lambda: cache.get_state("c1")["last_action"]["phase"] == "confirmed")

    assert executed == ["next_submission"]
    assert first_record.phase == "failed"
    assert cache._meta_for("c1")["actions"][cache._action_key(first_ref)].phase == "failed"
    assert cache.get_state("c1")["status"] != ContainerStatus.FAILED.value


def test_cold_start_rebuilds_running_created_exited_dead_and_last_action_null(monkeypatch):
    cache = ContainerStatusCache()
    running = FakeRuntimeContainer("run", status="running")
    created = FakeRuntimeContainer("created", status="created")
    exited = FakeRuntimeContainer("exited", status="exited")
    dead = FakeRuntimeContainer("dead", status="dead")
    monkeypatch.setattr(
        "FuxiYu_NodeKernel.docker_operates.status_cache.docker.from_env",
        lambda: type(
            "C",
            (),
            {"containers": FakeRuntimeContainers([running, created, exited, dead])},
        )(),
    )
    cache._reconcile_once()
    assert cache.get_state("run")["status"] == ContainerStatus.STARTING.value
    assert cache.get("run")["ready_verified"] is not True
    assert cache.get_state("created")["status"] == ContainerStatus.FAILED.value
    assert cache.get_state("exited")["status"] == ContainerStatus.OFFLINE.value
    assert cache.get_state("dead")["status"] == ContainerStatus.FAILED.value
    for name in ("run", "created", "exited", "dead"):
        assert cache.get_state(name)["last_action"] is None


# ---------------------------------------------------------------------------
# 4. 事件、对账与删除候选
# ---------------------------------------------------------------------------


def test_event_action_field_only_triggers_fresh_inspect(monkeypatch):
    cache = ContainerStatusCache()
    container = FakeRuntimeContainer("c1", status="running", docker_id="A")
    client = install_runtime(monkeypatch, [container])
    cache._apply_event({"Action": "start", "Actor": {"Attributes": {"name": "c1"}}})
    assert cache.get("c1")["docker_id"] == "A"
    assert cache.get_state("c1")["status"] == ContainerStatus.STARTING.value

    container.set_status("exited")
    cache._apply_event({"status": "die", "Actor": {"Attributes": {"name": "c1"}}})
    assert cache.get_state("c1")["status"] == ContainerStatus.OFFLINE.value
    assert client.containers.get_calls


def test_event_exec_colon_is_noise_and_unknown_not_delete(monkeypatch):
    cache = ContainerStatusCache()
    container = FakeRuntimeContainer("c1", status="running")
    install_runtime(monkeypatch, [container])
    _seed_online(cache, "c1", container)
    before = cache.get_state("c1")

    calls = []
    monkeypatch.setattr(extensions.event_log, "record", lambda *a, **k: calls.append((a, k)))
    cache._apply_event({"Action": "exec_start: /bin/sh", "Actor": {"Attributes": {"name": "c1"}}})
    cache._apply_event({"Action": "exec_create: /bin/sh", "Actor": {"Attributes": {"name": "c1"}}})
    cache._apply_event({"Action": "future_action", "Actor": {"Attributes": {"name": "c1"}}})
    assert cache.get_state("c1")["status"] == before["status"]
    assert calls == []


def test_event_inspect_failure_keeps_last_known(monkeypatch):
    cache = ContainerStatusCache()
    container = FakeRuntimeContainer("c1", status="running")
    install_runtime(monkeypatch, [container])
    _seed_online(cache, "c1", container)
    container.reload = lambda: (_ for _ in ()).throw(RuntimeError("inspect down"))
    cache._apply_event({"Action": "pause", "Actor": {"Attributes": {"name": "c1"}}})
    assert cache.get_state("c1")["status"] == ContainerStatus.ONLINE.value


def test_reconcile_uses_fresh_name_resolution_not_stale_list_object(monkeypatch):
    cache = ContainerStatusCache()
    fresh = FakeRuntimeContainer("c1", status="running", docker_id="B")
    _seed_online(cache, "c1", fresh)
    stale = FakeRuntimeContainer("c1", status="paused", docker_id="A")
    client = install_runtime(monkeypatch, [fresh])
    monkeypatch.setattr(
        "FuxiYu_NodeKernel.docker_operates.status_cache.docker.from_env", lambda: client
    )
    # list 返回旧对象，按名称 get 返回当前对象。
    monkeypatch.setattr(client.containers, "list", lambda *a, **k: [stale])
    client.containers._containers = [fresh]

    cache._reconcile_once()
    state = cache.get_state("c1")
    assert state["status"] == ContainerStatus.ONLINE.value
    assert cache.get("c1")["docker_id"] == "B"
    assert cache.take_deleted() == []


def test_reconcile_per_container_inspect_failure_marks_unknown_and_keeps_last_known(monkeypatch):
    cache = ContainerStatusCache()
    container = FakeRuntimeContainer("c1", status="running")
    _seed_online(cache, "c1", container)
    client = install_runtime(monkeypatch, [container])
    monkeypatch.setattr(
        "FuxiYu_NodeKernel.docker_operates.status_cache.docker.from_env", lambda: client
    )

    def _boom(name):
        raise RuntimeError("inspect failed")

    client.containers.get = _boom
    cache._reconcile_once()
    state = cache.get_state("c1")
    assert state["status"] == ContainerStatus.UNKNOWN.value
    assert state["status_source"] == "collect_error"
    assert state["last_known_status"] == ContainerStatus.ONLINE.value
    assert cache.get_collect_error() is None


def test_reconcile_vanished_candidate_requires_notfound_and_generation_check(monkeypatch):
    cache = ContainerStatusCache()
    gone = FakeRuntimeContainer("gone", status="running")
    _seed_online(cache, "gone", gone)
    client = install_runtime(monkeypatch, [])
    monkeypatch.setattr(
        "FuxiYu_NodeKernel.docker_operates.status_cache.docker.from_env", lambda: client
    )
    client.containers.get = lambda name: (_ for _ in ()).throw(RuntimeError("docker query failed"))
    cache._reconcile_once()
    assert cache.get("gone") is not None
    assert cache.get_collect_error() == "collect_failed"
    assert cache.take_deleted() == []

    from .runtime_fakes import not_found

    client.containers.get = lambda name: (_ for _ in ()).throw(not_found(str(name)))
    cache._reconcile_once()
    assert cache.get("gone") is None
    assert cache.take_deleted() == ["gone"]


def test_delete_candidate_dropped_when_same_name_reappears_before_send(monkeypatch):
    cache = ContainerStatusCache()
    gone = FakeRuntimeContainer("c1", status="running")
    _seed_online(cache, "c1", gone)
    client = install_runtime(monkeypatch, [])
    monkeypatch.setattr(
        "FuxiYu_NodeKernel.docker_operates.status_cache.docker.from_env", lambda: client
    )
    from .runtime_fakes import not_found

    client.containers.get = lambda name: (_ for _ in ()).throw(not_found(str(name)))
    cache._reconcile_once()
    assert cache._deleted  # candidate 已排队（内部保留代际）

    # 放回同名对象；发送前确认必须丢弃候选。
    client.containers._containers = [FakeRuntimeContainer("c1", status="running")]
    client.containers.get = FakeRuntimeContainers.get.__get__(client.containers, FakeRuntimeContainers)
    assert cache.take_confirmed_deleted() == []
    assert cache.take_deleted() == []


def test_wss_status_entry_explicit_last_action_null_and_failed_plus_online(monkeypatch):
    cache = ContainerStatusCache()
    monkeypatch.setattr(extensions, "status_cache", cache)
    container = FakeRuntimeContainer("c1", status="running")
    _seed_online(cache, "c1", container)
    monkeypatch.setattr(wss_module, "list_container_status", cache.list_states)
    frame = wss_module.build_status_snapshot()
    assert frame["payload"]["c1"]["last_action"] is None
    assert json.loads(json.dumps(frame))["payload"]["c1"]["last_action"] is None

    ref = cache.accept_action("c1", "pause", "pausing")
    _finish(cache, "c1", ref, "failed", "docker_api_error")
    frame = wss_module.build_status_snapshot()
    entry = frame["payload"]["c1"]
    assert entry["status"] == ContainerStatus.ONLINE.value
    assert entry["last_action"]["phase"] == "failed"
    assert entry["last_action"]["ref"] == ref
    assert "failed" != entry["status"]


# ---------------------------------------------------------------------------
# 5. API 真实入口与事故时间线
# ---------------------------------------------------------------------------


@pytest.fixture()
def api_client(monkeypatch):
    app = create_app()
    return TestClient(app)


def _payload(name="c1", **extra):
    cfg = {
        "gpu_list": [],
        "cpu_number": 2,
        "memory": 4,
        "shared_memory": 0,
        "name": name,
        "port": 2233,
        "image": "ubuntu:22.04",
    }
    cfg.update(extra)
    return {"config": {"container_name": name}}


def test_api_repeated_unpause_is_idempotent_with_new_ref(api_client, monkeypatch):
    cache = ContainerStatusCache()
    monkeypatch.setattr(extensions, "status_cache", cache)
    container = FakeRuntimeContainer("c1", status="running")
    install_runtime(monkeypatch, [container])
    _seed_online(cache, "c1", container)

    payload = {"config": {"container_name": "c1", "action": "unpause"}}
    first = api_client.post("/api/pause_container", json=payload)
    assert first.status_code == 200
    body = first.json()
    assert body["container_status"] == "unpausing"
    assert body["action_ref"]["node_epoch"] == cache.node_epoch
    assert body["action_ref"]["seq"] >= 1
    assert wait_for(lambda: cache.get_state("c1")["last_action"]["phase"] == "idempotent_confirmed")

    second = api_client.post("/api/pause_container", json=payload)
    second_body = second.json()
    assert second_body["action_ref"] != body["action_ref"]
    assert wait_for(lambda: cache.get_state("c1")["last_action"]["ref"] == second_body["action_ref"])
    state = cache.get_state("c1")
    assert state["status"] == ContainerStatus.ONLINE.value
    assert state["last_action"]["phase"] == "idempotent_confirmed"
    assert container.unpause_calls == 0


def test_api_pause_soft_failure_keeps_online_and_exposes_last_action_failed(api_client, monkeypatch):
    cache = ContainerStatusCache()
    monkeypatch.setattr(extensions, "status_cache", cache)
    container = FakeRuntimeContainer("c1", status="running")
    container.raise_on_pause = docker.errors.APIError("daemon refused")
    install_runtime(monkeypatch, [container])
    _seed_online(cache, "c1", container)

    resp = api_client.post("/api/pause_container", json={"config": {"container_name": "c1", "action": "pause"}})
    assert resp.status_code == 200
    assert wait_for(lambda: cache.get_state("c1")["last_action"]["phase"] == "failed")
    state = cache.get_state("c1")
    assert state["status"] == ContainerStatus.ONLINE.value
    assert state["last_action"]["action"] == "pause"

    status = api_client.post("/api/container_status", json={"config": {"container_name": "c1"}})
    body = status.json()
    assert body["success"] == 1
    assert body["container_status"] == "online"
    assert body["last_action"]["phase"] == "failed"


def test_api_restart_clears_ready_until_sshd_probe(api_client, monkeypatch):
    cache = ContainerStatusCache()
    monkeypatch.setattr(extensions, "status_cache", cache)
    container = FakeRuntimeContainer("c1", status="running", started_at="2026-10-17T19:00:00Z")
    install_runtime(monkeypatch, [container])
    _seed_online(cache, "c1", container)

    resp = api_client.post("/api/restart_container", json={"config": {"container_name": "c1"}})
    assert resp.status_code == 200
    assert "action_ref" in resp.json()
    assert wait_for(lambda: cache.get_state("c1")["last_action"]["phase"] == "confirmed")
    state = cache.get_state("c1")
    assert state["status"] == ContainerStatus.STARTING.value
    assert state["ready_check"] is True
    assert cache.get("c1")["ready_verified"] is False

    monkeypatch.setattr(cache, "_probe_sshd_container", lambda container: True)
    cache._probe_ready_checks_once()
    assert cache.get_state("c1")["status"] == ContainerStatus.ONLINE.value


def test_start_same_ready_process_is_idempotent(monkeypatch):
    cache = ContainerStatusCache()
    monkeypatch.setattr(extensions, "status_cache", cache)
    container = FakeRuntimeContainer("c1", status="running")
    install_runtime(monkeypatch, [container])
    _seed_online(cache, "c1", container)
    ref = cache.accept_action("c1", "start", "starting")
    result = container_service.execute_start_action("c1", {**ref, "name": "c1"})
    _finish(cache, "c1", ref, result.phase, result.error_reason)
    assert result.phase == "idempotent_confirmed"
    assert cache.get_state("c1")["status"] == ContainerStatus.ONLINE.value
    assert container.start_calls == 0


def test_api_status_unknown_explicit_last_action_null(api_client, monkeypatch):
    cache = ContainerStatusCache()
    monkeypatch.setattr(extensions, "status_cache", cache)
    cache.forget_container_generation("ghost")
    resp = api_client.post("/api/container_status", json={"config": {"container_name": "ghost"}})
    body = resp.json()
    assert body["container_status"] == "unknown"
    assert "last_action" in body
    assert body["last_action"] is None


def test_api_start_running_without_ready_does_not_bypass_gate(api_client, monkeypatch):
    cache = ContainerStatusCache()
    monkeypatch.setattr(extensions, "status_cache", cache)
    container = FakeRuntimeContainer("c1", status="running", started_at="2026-10-17T19:00:00Z")
    install_runtime(monkeypatch, [container])
    _publish(cache, "c1", container)  # 未验证 ready

    resp = api_client.post("/api/start_container", json=_payload("c1"))
    assert resp.status_code == 200
    assert wait_for(lambda: cache.get_state("c1")["last_action"]["phase"] in {"confirmed", "idempotent_confirmed"})
    assert container.start_calls == 0
    state = cache.get_state("c1")
    assert state["status"] == ContainerStatus.STARTING.value
    assert state["ready_check"] is True


def test_api_create_visible_before_background_thread_finishes(api_client, monkeypatch):
    cache = ContainerStatusCache()
    monkeypatch.setattr(extensions, "status_cache", cache)
    started = threading.Event()
    release = threading.Event()

    def _slow_create(owner_name, cfg, public_key=None, restore_mount_path=None):
        started.set()
        assert release.wait(3)
        return container_service.CreateContainerReturn("cid", cfg.name)

    monkeypatch.setattr(api_module, "container_exists", lambda name: False)
    monkeypatch.setattr(api_module, "create_container", _slow_create)
    resp = api_client.post(
        "/api/create_container",
        json={
            "owner_name": "admin",
            "config": {
                "gpu_list": [],
                "cpu_number": 2,
                "memory": 4,
                "shared_memory": 0,
                "name": "newc",
                "port": 2233,
                "image": "ubuntu:22.04",
            },
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["action_ref"]["node_epoch"] == cache.node_epoch
    assert started.wait(2)
    # 后台线程尚未完成，但快照必须已可见 building/creating，且不是 vanished。
    assert cache.get_state("newc")["status"] == "creating"
    release.set()
    assert wait_for(lambda: cache.get_state("newc")["last_action"]["phase"] == "confirmed")


def test_api_create_leaves_created_object_as_hard_block(api_client, monkeypatch):
    cache = ContainerStatusCache()
    monkeypatch.setattr(extensions, "status_cache", cache)
    created = FakeRuntimeContainer("half", status="created")
    install_runtime(monkeypatch, [created])
    monkeypatch.setattr(api_module, "container_exists", lambda name: False)
    monkeypatch.setattr(
        api_module,
        "create_container",
        lambda *a, **k: container_service.CreateContainerReturn("cid", "half"),
    )
    resp = api_client.post(
        "/api/create_container",
        json={
            "owner_name": "admin",
            "config": {
                "gpu_list": [],
                "cpu_number": 2,
                "memory": 4,
                "shared_memory": 0,
                "name": "half",
                "port": 2233,
                "image": "ubuntu:22.04",
            },
        },
    )
    assert resp.status_code == 200
    assert wait_for(lambda: cache.get_state("half")["last_action"]["phase"] == "confirmed")
    state = cache.get_state("half")
    assert state["status"] == ContainerStatus.FAILED.value
    assert state["failed_reason"] == "created_half_built"


def test_api_create_failure_without_object_is_unknown_not_failed(api_client, monkeypatch):
    cache = ContainerStatusCache()
    monkeypatch.setattr(extensions, "status_cache", cache)
    monkeypatch.setattr(api_module, "container_exists", lambda name: False)
    monkeypatch.setattr(
        api_module,
        "create_container",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("docker create failed")),
    )
    resp = api_client.post(
        "/api/create_container",
        json={
            "owner_name": "admin",
            "config": {
                "gpu_list": [],
                "cpu_number": 2,
                "memory": 4,
                "shared_memory": 0,
                "name": "failc",
                "port": 2233,
                "image": "ubuntu:22.04",
            },
        },
    )
    assert resp.status_code == 200
    assert wait_for(lambda: cache.get_state("failc")["last_action"]["phase"] == "failed")
    state = cache.get_state("failc")
    assert state["status"] == ContainerStatus.UNKNOWN.value
    assert state["status"] != ContainerStatus.FAILED.value
    assert state["last_action"]["error_reason"] == "create_failed"


def test_sylvan_timeline_old_reconcile_cannot_rollback_after_unpause(api_client, monkeypatch):
    """19:33:16 online → 慢速对账旧 paused 快照 → 19:33:48 第二次 unpause → online。"""
    cache = ContainerStatusCache()
    monkeypatch.setattr(extensions, "status_cache", cache)
    container = FakeRuntimeContainer("Sylvan", status="running")
    install_runtime(monkeypatch, [container])
    _seed_online(cache, "Sylvan", container)

    # 慢速对账：旧对象 paused，且 stats 期间动作已完成。
    stale = FakeRuntimeContainer("Sylvan", status="paused", docker_id=container.id)
    ticket = cache.issue_observation("Sylvan", "slow-reconcile")
    time.sleep(0.01)
    _seed_online(cache, "Sylvan", container, source="unpause-confirm")
    assert cache.publish_observed("Sylvan", ticket, fact_from_container(stale)) is False
    assert cache.get_state("Sylvan")["status"] == ContainerStatus.ONLINE.value

    # 第二次 unpause 遇 is not paused：新鲜实态 running/not paused → 幂等确认。
    def _raise_not_paused(self):
        raise docker.errors.APIError("Container Sylvan is not paused")

    container.raise_on_unpause = docker.errors.APIError("Container Sylvan is not paused")
    resp = api_client.post(
        "/api/pause_container", json={"config": {"container_name": "Sylvan", "action": "unpause"}}
    )
    assert resp.status_code == 200
    assert wait_for(lambda: cache.get_state("Sylvan")["last_action"]["phase"] == "idempotent_confirmed")
    state = cache.get_state("Sylvan")
    assert state["status"] == ContainerStatus.ONLINE.value
    assert state["last_action"]["error_reason"] in (None, "Container Sylvan is not paused")
    assert "unpause_failed" != state.get("failed_reason")


def test_pause_preserves_ready_identity_and_unpause_reuses_it(monkeypatch):
    cache = ContainerStatusCache()
    monkeypatch.setattr(extensions, "status_cache", cache)
    container = FakeRuntimeContainer("c1", status="running", docker_id="A")
    install_runtime(monkeypatch, [container])
    _seed_online(cache, "c1", container)
    ready_before = dict(cache.get("c1")["ready_identity"])

    ref = cache.accept_action("c1", "pause", "pausing")
    result = container_service.execute_pause_action("c1", "pause", {**ref, "name": "c1"})
    _finish(cache, "c1", ref, result.phase, result.error_reason)
    assert result.phase == "confirmed"
    assert cache.get_state("c1")["status"] == ContainerStatus.PAUSED.value
    assert cache.get("c1")["ready_verified"] is True
    assert cache.get("c1")["ready_identity"] == ready_before

    ref2 = cache.accept_action("c1", "unpause", "unpausing")
    result2 = container_service.execute_pause_action("c1", "unpause", {**ref2, "name": "c1"})
    _finish(cache, "c1", ref2, result2.phase, result2.error_reason)
    assert result2.phase == "confirmed"
    assert cache.get_state("c1")["status"] == ContainerStatus.ONLINE.value
    assert cache.get("c1")["ready_identity"] == ready_before


def test_pause_unpause_offline_dead_never_report_success(monkeypatch):
    cache = ContainerStatusCache()
    monkeypatch.setattr(extensions, "status_cache", cache)
    offline = FakeRuntimeContainer("offline", status="exited")
    dead = FakeRuntimeContainer("dead", status="dead")
    install_runtime(monkeypatch, [offline, dead])

    for action in ("pause", "unpause"):
        ref = cache.accept_action("offline", action, "pausing" if action == "pause" else "unpausing")
        result = container_service.execute_pause_action("offline", action, {**ref, "name": "offline"})
        _finish(cache, "offline", ref, result.phase, result.error_reason)
        assert result.phase == "failed"
        assert result.error_reason == "not_running"
        assert cache.get_state("offline")["status"] == ContainerStatus.OFFLINE.value

        ref = cache.accept_action("dead", action, "pausing" if action == "pause" else "unpausing")
        result = container_service.execute_pause_action("dead", action, {**ref, "name": "dead"})
        _finish(cache, "dead", ref, result.phase, result.error_reason)
        assert result.phase == "failed"
        assert result.error_reason == "docker_dead"
        assert cache.get_state("dead")["status"] == ContainerStatus.FAILED.value
        assert cache.get_state("dead")["failed_reason"] == "docker_dead"


def test_stop_offline_is_idempotent_and_dead_not_success(monkeypatch):
    cache = ContainerStatusCache()
    monkeypatch.setattr(extensions, "status_cache", cache)
    offline = FakeRuntimeContainer("offline", status="exited")
    dead = FakeRuntimeContainer("dead", status="dead")
    install_runtime(monkeypatch, [offline, dead])

    ref = cache.accept_action("offline", "stop", "stopping")
    result = container_service.execute_stop_action("offline", {**ref, "name": "offline"})
    _finish(cache, "offline", ref, result.phase, result.error_reason)
    assert result.phase == "idempotent_confirmed"
    assert cache.get_state("offline")["status"] == ContainerStatus.OFFLINE.value

    ref = cache.accept_action("dead", "stop", "stopping")
    result = container_service.execute_stop_action("dead", {**ref, "name": "dead"})
    _finish(cache, "dead", ref, result.phase, result.error_reason)
    assert result.phase == "failed"
    assert result.error_reason == "docker_dead"


def test_unpause_is_not_paused_error_after_fresh_state_resolves_idempotent(monkeypatch):
    cache = ContainerStatusCache()
    monkeypatch.setattr(extensions, "status_cache", cache)
    container = FakeRuntimeContainer("c1", status="paused", docker_id="A")
    install_runtime(monkeypatch, [container])

    def _unpause_then_raise():
        container.set_status("running")
        raise docker.errors.APIError("Container c1 is not paused")

    container.on_unpause = lambda c: _unpause_then_raise()
    container.raise_on_unpause = docker.errors.APIError("Container c1 is not paused")
    ticket = cache.issue_observation("c1", "seed")
    cache.publish_observed("c1", ticket, fact_from_container(container), mark_ready=True)
    assert cache.get_state("c1")["status"] == ContainerStatus.PAUSED.value

    ref = cache.accept_action("c1", "unpause", "unpausing")
    result = container_service.execute_pause_action("c1", "unpause", {**ref, "name": "c1"})
    _finish(cache, "c1", ref, result.phase, result.error_reason)

    assert result.phase == "idempotent_confirmed"
    assert cache.get_state("c1")["status"] == ContainerStatus.ONLINE.value
    assert cache.get_state("c1")["last_action"]["phase"] == "idempotent_confirmed"
    assert "unpause_failed" not in str(cache.get_state("c1"))


def test_action_ttl_hides_transition_but_does_not_write_failed(monkeypatch):
    cache = ContainerStatusCache()
    container = FakeRuntimeContainer("c1", status="running")
    _seed_online(cache, "c1", container)
    ref = cache.accept_action("c1", "pause", "pausing")
    record = cache._meta_for("c1")["current_action"]
    record.accepted_at = record.accepted_at - __import__("datetime").timedelta(
        seconds=record.ttl + 1
    )

    state = cache.get_state("c1")
    assert state["status"] == ContainerStatus.ONLINE.value
    assert state["last_action"]["phase"] == "timed_out"
    assert state["last_action"]["ref"] == ref
    assert cache._cache["c1"].get("failed_reason") is None
    assert record.phase == "timed_out"


def test_unconfirmed_and_timed_out_are_non_terminal_and_can_finish_later(monkeypatch):
    cache = ContainerStatusCache()
    container = FakeRuntimeContainer("c1", status="running")
    _seed_online(cache, "c1", container)
    ref = cache.accept_action("c1", "start", "starting")
    assert _finish(cache, "c1", ref, "unconfirmed", "inspect_failed") is True
    state = cache.get_state("c1")
    assert state["source"] == "pending"
    assert state["status"] == "starting"
    assert state["last_action"]["phase"] == "unconfirmed"
    assert _finish(cache, "c1", ref, "confirmed") is True
    assert cache.get_state("c1")["last_action"]["phase"] == "confirmed"


def test_same_ref_terminal_phase_not_regressed(monkeypatch):
    cache = ContainerStatusCache()
    container = FakeRuntimeContainer("c1", status="running")
    _seed_online(cache, "c1", container)
    ref = cache.accept_action("c1", "pause", "pausing")
    assert _finish(cache, "c1", ref, "failed", "docker_api_error") is True
    assert _finish(cache, "c1", ref, "accepted") is False
    assert cache.get_state("c1")["last_action"]["phase"] == "failed"


def test_hard_block_classification_is_bounded(monkeypatch):
    cache = ContainerStatusCache()
    client = install_runtime(monkeypatch, [])
    cases = {
        "exited": ("exited", ContainerStatus.OFFLINE.value, False),
        "restarting": ("restarting", ContainerStatus.RESTARTING.value, False),
        "created": ("created", ContainerStatus.FAILED.value, True),
        "dead": ("dead", ContainerStatus.FAILED.value, True),
    }
    for name, (status, expected, hard) in cases.items():
        container = FakeRuntimeContainer(name, status=status)
        client.containers.add(container)
        ticket = cache.issue_observation(name, "classify")
        fact = fact_from_container(container)
        assert cache.publish_observed(name, ticket, fact) is True
        state = cache.get_state(name)
        assert state["status"] == expected
        if hard:
            assert cache.get(name)["hard_block"] is True

    # 历史 OOM 在已恢复 running 后不得 sticky failed。
    oom = FakeRuntimeContainer("oom", status="running")
    oom.attrs["State"]["OOMKilled"] = True
    ticket = cache.issue_observation("oom", "classify")
    cache.publish_observed("oom", ticket, fact_from_container(oom))
    assert cache.get_state("oom")["status"] == ContainerStatus.STARTING.value

    # sshd 硬阻塞只有 probe 通过（ready identity 记录）才解除。
    cache.set_hard_block("sshd", "sshd_not_installed", "missing")
    sshd = FakeRuntimeContainer("sshd", status="running")
    ticket = cache.issue_observation("sshd", "classify")
    cache.publish_observed("sshd", ticket, fact_from_container(sshd))
    assert cache.get_state("sshd")["status"] == ContainerStatus.FAILED.value
    ready_ticket = cache.issue_observation("sshd", "manual-probe")
    assert cache.mark_ready_verified("sshd", fact_from_container(sshd), ticket=ready_ticket) is True
    assert cache.get_state("sshd")["status"] == ContainerStatus.ONLINE.value


def test_hard_block_invalidates_ready_and_pause_does_not_clear_it():
    """硬阻塞成立后，旧 ready 不能放行 running；暂停也不证明故障消失。"""
    cache = ContainerStatusCache()
    container = FakeRuntimeContainer("c1", status="running", docker_id="A")
    _seed_online(cache, "c1", container)
    assert cache.get("c1")["ready_verified"] is True

    cache.set_hard_block("c1", "sshd_not_installed", "missing")
    entry = cache.get("c1")
    assert entry["ready_verified"] is False
    assert "ready_identity" not in entry

    # 同一进程的 running 事实不能凭旧 ready 清除硬阻塞。
    _publish(cache, "c1", container)
    state = cache.get_state("c1")
    assert state["status"] == ContainerStatus.FAILED.value
    assert state["failed_reason"] == "sshd_not_installed"

    # paused 是真实事实，但不是 sshd 已修复的证据；硬阻塞必须保留。
    paused = FakeRuntimeContainer("c1", status="paused", docker_id="A")
    _publish(cache, "c1", paused)
    state = cache.get_state("c1")
    assert state["status"] == ContainerStatus.FAILED.value
    assert state["failed_reason"] == "sshd_not_installed"
    assert cache.get("c1")["hard_block"] is True

    # unpause 后 running 仍须通过 probe，而非直接 online。
    _publish(cache, "c1", container)
    assert cache.get_state("c1")["status"] == ContainerStatus.FAILED.value


def test_create_pending_created_fact_is_not_hard_blocked_until_create_finishes():
    cache = ContainerStatusCache()
    ref = cache.accept_action("c1", "create", "creating", create=True)
    created = FakeRuntimeContainer("c1", status="created")
    ticket = cache.issue_observation(
        "c1",
        "create",
        generation=ref["generation"],
        action_seq=ref["seq"],
        from_create_confirmation=True,
    )
    assert cache.publish_observed("c1", ticket, fact_from_container(created)) is True

    during = cache.get_state("c1")
    assert during["status"] == ContainerStatus.CREATING.value
    assert during.get("failed_reason") is None
    assert cache.get("c1").get("hard_block") is not True
    assert cache.get("c1")["docker_id"] == created.id

    # create 结束后对象仍停在 created，才形成半成品硬阻塞。
    assert cache.finish_action_ref({**ref, "name": "c1"}, "confirmed") is True
    after = cache.get_state("c1")
    assert after["status"] == ContainerStatus.FAILED.value
    assert after["failed_reason"] == "created_half_built"
    assert cache.get("c1")["hard_block"] is True


def test_create_superseded_by_non_create_releases_pending_when_create_finishes():
    cache = ContainerStatusCache()
    create_ref = cache.accept_action("c1", "create", "creating", create=True)
    start_ref = cache.accept_action("c1", "start", "starting")
    assert cache._meta_for("c1")["create_pending"] is True
    assert cache.get_state("c1")["last_action"]["ref"] == start_ref

    # 原 create 后台意图晚到：phase 保持 superseded，但名称所有权必须释放。
    assert cache.finish_action_ref({**create_ref, "name": "c1"}, "confirmed") is False

    meta = cache._meta_for("c1")
    assert meta["create_pending"] is False
    assert meta["last_action"].ref == start_ref
    assert cache._meta_for("c1")["actions"][cache._action_key(create_ref)].phase == "superseded"


def test_old_create_finish_does_not_release_new_create_pending():
    cache = ContainerStatusCache()
    old_ref = cache.accept_action("c1", "create", "creating", create=True)
    new_ref = cache.accept_action("c1", "create", "building", create=True)
    assert cache._meta_for("c1")["create_pending"] is True

    # 旧代 create 晚到时，新代 create 仍拥有名称，不能被旧终结释放。
    assert cache.finish_action_ref({**old_ref, "name": "c1"}, "failed", "old_generation") is False

    meta = cache._meta_for("c1")
    assert meta["create_pending"] is True
    assert meta["current_action"].ref == new_ref
    assert meta["last_action"].ref == new_ref
    assert cache.get_state("c1")["last_action"]["ref"] == new_ref


def test_legacy_finish_action_without_current_action_cannot_write_runtime():
    cache = ContainerStatusCache()
    container = FakeRuntimeContainer("c1", status="running")
    _seed_online(cache, "c1", container)
    ref = cache.accept_action("c1", "pause", "pausing")
    assert _finish(cache, "c1", ref, "failed", "docker_api_error")

    cache.finish_action("c1", "offline")

    state = cache.get_state("c1")
    assert state["status"] == ContainerStatus.ONLINE.value
    assert state["last_action"]["phase"] == "failed"
    assert cache.get("c1")["status"] == ContainerStatus.ONLINE.value


def test_legacy_finish_action_with_current_action_does_not_write_runtime():
    cache = ContainerStatusCache()
    container = FakeRuntimeContainer("c1", status="running")
    _seed_online(cache, "c1", container)
    cache.begin_action("c1", "pause", "pausing")

    cache.finish_action("c1", "offline")

    state = cache.get_state("c1")
    assert state["status"] == ContainerStatus.ONLINE.value
    assert state["last_action"]["phase"] == "confirmed"
    assert cache.get("c1")["status"] == ContainerStatus.ONLINE.value


def test_inconsistent_failed_without_allowed_reason_is_unknown_without_reason_as_last_known():
    cache = ContainerStatusCache()
    # 模拟旧采集落下的非法 failed 条目；读面不得把原因当状态值。
    with cache._lock:
        cache._cache["c1"] = {
            "status": ContainerStatus.FAILED.value,
            "hard_block": True,
            "failed_reason": "legacy_failed",
        }

    state = cache.get_state("c1")
    assert state["status"] == ContainerStatus.UNKNOWN.value
    assert state["status_source"] == "inconsistent_failed"
    assert state.get("last_known_status") is None
    assert state["failed_reason"] is None
    assert state["error_reason"] is None


def test_probe_success_clears_sshd_hard_block_only_after_same_process_confirmation(monkeypatch):
    cache = ContainerStatusCache()
    container = FakeRuntimeContainer("c1", status="running", docker_id="A")
    install_runtime(monkeypatch, [container])
    _publish(cache, "c1", container)  # running 未 ready
    cache.set_hard_block("c1", "sshd_not_installed", "missing")
    monkeypatch.setattr(cache, "_probe_sshd_container", lambda c: True)

    cache._probe_ready_checks_once()

    state = cache.get_state("c1")
    assert state["status"] == ContainerStatus.ONLINE.value
    assert cache.get("c1")["ready_verified"] is True
    assert cache.get("c1")["ready_identity"]["docker_id"] == "A"


def test_probe_on_old_process_cannot_mark_new_process_ready(monkeypatch):
    cache = ContainerStatusCache()
    old = FakeRuntimeContainer("c1", status="running", docker_id="A", started_at="2026-10-17T19:00:00Z")
    new = FakeRuntimeContainer("c1", status="running", docker_id="A", started_at="2026-10-17T19:30:00Z")
    cache.mark_ready_check("c1")
    calls = {"get": 0}

    class _Client:
        def __init__(self):
            self.containers = self

        def get(self, name):
            calls["get"] += 1
            return old if calls["get"] == 1 else new

    monkeypatch.setattr(extensions, "docker_client", _Client())
    monkeypatch.setattr(cache, "_probe_sshd_container", lambda c: True)
    monkeypatch.setattr(
        "FuxiYu_NodeKernel.docker_operates.status_cache._nvidia_gpu_runtime_by_index", lambda: {}
    )

    cache._probe_ready_once("c1")

    state = cache.get_state("c1")
    assert state["status"] != ContainerStatus.ONLINE.value
    assert cache.get("c1").get("ready_verified") is not True
    assert cache.get("c1").get("ready_identity") is None


def test_probe_not_installed_on_old_process_cannot_block_new_process(monkeypatch):
    cache = ContainerStatusCache()
    old = FakeRuntimeContainer("c1", status="running", docker_id="A", started_at="2026-10-17T19:00:00Z")
    new = FakeRuntimeContainer("c1", status="running", docker_id="A", started_at="2026-10-17T19:30:00Z")
    cache.mark_ready_check("c1")
    calls = {"get": 0}

    class _Client:
        def __init__(self):
            self.containers = self

        def get(self, name):
            calls["get"] += 1
            return old if calls["get"] == 1 else new

    monkeypatch.setattr(extensions, "docker_client", _Client())
    monkeypatch.setattr(cache, "_probe_sshd_container", lambda c: False)
    monkeypatch.setattr(cache, "_ensure_sshd_started_container", lambda c, n: "not_installed")

    cache._probe_ready_once("c1")

    state = cache.get_state("c1")
    assert state["status"] != ContainerStatus.FAILED.value
    assert cache.get("c1").get("hard_block") is not True


def test_probe_success_late_after_new_action_does_not_publish_ready(monkeypatch):
    cache = ContainerStatusCache()
    container = FakeRuntimeContainer("c1", status="running", docker_id="A")
    install_runtime(monkeypatch, [container])
    cache.mark_ready_check("c1")

    def _probe(c):
        cache.accept_action("c1", "pause", "pausing")
        return True

    monkeypatch.setattr(cache, "_probe_sshd_container", _probe)
    cache._probe_ready_once("c1")

    assert cache.get_state("c1")["status"] != ContainerStatus.ONLINE.value
    assert cache.get("c1").get("ready_verified") is not True
    assert cache.get_state("c1")["last_action"]["action"] == "pause"


def test_action_observation_uses_acceptance_generation_not_current(monkeypatch):
    cache = ContainerStatusCache()
    new = FakeRuntimeContainer("c1", status="running", docker_id="B")
    install_runtime(monkeypatch, [new])
    ref = cache.accept_action("c1", "start", "starting")
    cache.accept_action("c1", "create", "creating", create=True)  # 新代际，seq 重新计数

    ticket = cache.issue_observation(
        "c1", "old-action", generation=ref["generation"], action_seq=ref["seq"]
    )
    assert cache.publish_observed("c1", ticket, fact_from_container(new)) is False
    assert (cache.get("c1") or {}).get("docker_id") != "B"
    assert cache._meta_for("c1")["generation"] == ref["generation"] + 1


def test_old_action_ref_is_rejected_before_new_generation_side_effect(monkeypatch):
    cache = ContainerStatusCache()
    monkeypatch.setattr(extensions, "status_cache", cache)
    container = FakeRuntimeContainer("c1", status="exited")
    install_runtime(monkeypatch, [container])
    ref = cache.accept_action("c1", "start", "starting")
    cache.accept_action("c1", "create", "creating", create=True)

    result = container_service.execute_start_action("c1", {**ref, "name": "c1"})
    assert result.phase == "superseded"
    assert container.start_calls == 0


def test_old_create_refresh_and_port_write_cannot_bind_new_generation(monkeypatch):
    cache = ContainerStatusCache()
    new = FakeRuntimeContainer("c1", status="running", docker_id="B")
    install_runtime(monkeypatch, [new])
    old_ref = cache.accept_action("c1", "create", "creating", create=True)
    new_ref = cache.accept_action("c1", "create", "creating", create=True)
    gen = cache._meta_for("c1")["generation"]

    assert cache.set_port_info("c1", 2222, [], ref=old_ref) is False
    cache.refresh_from_docker("c1", source="old-create", action_ref=old_ref, from_create_confirmation=True)
    assert cache._meta_for("c1")["generation"] == gen
    assert (cache.get("c1") or {}).get("docker_id") != "B"
    assert (cache.get("c1") or {}).get("port") is None
    assert cache.get_state("c1")["last_action"]["ref"] == new_ref


def test_blocked_old_action_side_effect_cannot_write_new_generation(monkeypatch):
    cache = ContainerStatusCache()
    monkeypatch.setattr(extensions, "status_cache", cache)
    container = FakeRuntimeContainer("c1", status="exited", docker_id="A")
    install_runtime(monkeypatch, [container])
    ref = cache.accept_action("c1", "start", "starting")

    entered = threading.Event()
    release = threading.Event()

    def _start():
        entered.set()
        assert release.wait(3)
        container.set_status("running", started_at="2026-10-17T20:00:00Z")

    container.on_start = lambda c: _start()
    result_holder = {}

    def _run():
        result_holder["result"] = container_service.execute_start_action("c1", {**ref, "name": "c1"})

    worker = threading.Thread(target=_run)
    worker.start()
    assert entered.wait(2)
    # Docker 调用阻塞期间同名 create 换代 + 新请求。
    new_ref = cache.accept_action("c1", "create", "creating", create=True)
    release.set()
    worker.join(3)

    # 旧动作后置观察票固定旧代际，必须被拒绝；读面保持新 create 的 creating。
    state = cache.get_state("c1")
    assert state["status"] == ContainerStatus.CREATING.value
    assert state["last_action"]["ref"] == new_ref
    _finish(cache, "c1", ref, result_holder["result"].phase, result_holder["result"].error_reason)
    assert cache.get_state("c1")["status"] == ContainerStatus.CREATING.value
    # 旧 create 晚到的端口写入也不得落到新代。
    assert cache.set_port_info("c1", 1234, [{"container_port": 22, "host_port": 1234}], ref=ref) is False
    assert cache.get("c1").get("port") is None


def test_generation_change_skips_unexecuted_queue_items(monkeypatch):
    cache = ContainerStatusCache()
    entered = threading.Event()
    release = threading.Event()
    called = []

    def first(ref):
        entered.set()
        release.wait(2)
        called.append("first")
        return type("O", (), {"phase": "confirmed", "error_reason": None})()

    def second(ref):
        called.append("second")
        return type("O", (), {"phase": "confirmed", "error_reason": None})()

    cache.submit_action("c2", "start", "starting", first)
    assert entered.wait(2)
    cache.submit_action("c2", "restart", "restarting", second)
    # 第二个动作仍在队列；换代后必须被跳过，不执行其 Docker 意图。
    cache.accept_action("c2", "create", "creating", create=True)
    release.set()
    assert wait_for(lambda: not cache._action_workers or "c2" not in cache._action_workers)
    assert "second" not in called


def test_barrier_fixture_can_hold_inspect_while_generation_changes(monkeypatch):
    from .runtime_fakes import Barrier

    cache = ContainerStatusCache()
    container = FakeRuntimeContainer("c1", status="running", docker_id="A")
    client = install_runtime(monkeypatch, [container])
    barrier = Barrier()
    client.containers.get_barrier = barrier
    result = {}

    def _observe():
        result["fact"] = cache.refresh_from_docker("c1", source="barrier-inspect")

    worker = threading.Thread(target=_observe)
    worker.start()
    barrier.wait_entered()
    # 观察票已签发、Docker get 仍阻塞；此时同名 create 换代。
    cache.accept_action("c1", "create", "creating", create=True)
    barrier.release()
    worker.join(3)

    assert cache.get_state("c1")["status"] == ContainerStatus.CREATING.value
    assert cache.get_state("c1")["last_action"]["action"] == "create"


def test_randomized_interleavings_hold_sequence_and_runtime_invariants(monkeypatch):
    """固定种子随机交错：只断言规格不变量，不依赖线程完成顺序。"""
    import random

    rng = random.Random(20261017)
    cache = ContainerStatusCache()
    names = ["a", "b", "c"]
    clients = {}
    for index, name in enumerate(names):
        container = FakeRuntimeContainer(name, status="running", docker_id=f"id-{name}")
        clients[name] = container
        _seed_online(cache, name, container)
    install_runtime(monkeypatch, list(clients.values()))

    last_gen = {name: cache._meta_for(name)["generation"] for name in names}
    last_action_seq = {name: cache._meta_for(name)["action_seq"] for name in names}
    last_read = {name: 0 for name in names}
    active_actions = []

    for _ in range(400):
        name = rng.choice(names)
        op = rng.choice(["accept", "finish", "publish", "stale_publish", "metrics"])
        if op == "accept":
            action = rng.choice(["start", "stop", "restart", "pause", "unpause", "create"])
            transition = {
                "start": "starting", "stop": "stopping", "restart": "restarting",
                "pause": "pausing", "unpause": "unpausing", "create": "creating",
            }[action]
            ref = cache.accept_action(name, action, transition, create=(action == "create"))
            active_actions.append((name, ref))
            if action == "create":
                assert ref["generation"] >= last_gen[name]
                last_gen[name] = ref["generation"]
                last_action_seq[name] = ref["seq"]
            else:
                assert ref["generation"] == last_gen[name]
                assert ref["seq"] > last_action_seq[name]
                last_action_seq[name] = ref["seq"]
        elif op == "finish" and active_actions:
            idx = rng.randrange(len(active_actions))
            finish_name, ref = active_actions.pop(idx)
            phase = rng.choice(["confirmed", "idempotent_confirmed", "failed", "unconfirmed", "superseded"])
            cache.finish_action_ref({**ref, "name": finish_name}, phase, "random")
        elif op == "publish":
            container = clients[name]
            if rng.random() < 0.25:
                container.set_status("paused")
            elif rng.random() < 0.25:
                container.set_status("exited")
            else:
                container.set_status("running")
            ticket = cache.issue_observation(name, "random")
            assert ticket.read_seq > last_read[name]
            last_read[name] = ticket.read_seq
            cache.publish_observed(name, ticket, fact_from_container(container))
        elif op == "stale_publish":
            # 旧票（read_seq 已落后）永远不能抬高 last_applied_read_seq。
            meta = cache._meta_for(name)
            stale = cache.issue_observation(name, "stale")
            newer = cache.issue_observation(name, "newer")
            assert newer.read_seq > stale.read_seq
            cache.publish_observed(name, newer, fact_from_container(clients[name]))
            before_applied = meta["last_applied_read_seq"]
            cache.publish_observed(name, stale, fact_from_container(clients[name]))
            assert meta["last_applied_read_seq"] == before_applied
        else:
            ticket = cache.issue_observation(name, "metrics", metrics=True)
            cache.publish_metrics(name, ticket, {"cpu_usage_percent": 1.0})

        for n in names:
            meta = cache._meta_for(n)
            runtime = cache.get(n) or {}
            assert meta["generation"] >= last_gen[n]
            assert meta["read_seq"] >= meta["last_applied_read_seq"] >= 0
            assert meta["action_seq"] >= 0
            if runtime.get("status") == ContainerStatus.FAILED.value:
                assert runtime.get("hard_block") is True
                assert runtime.get("failed_reason") in HARD_BLOCK_REASONS
            last = meta.get("last_action")
            if last is not None:
                assert last.phase in {
                    "accepted", "confirmed", "idempotent_confirmed", "failed",
                    "unconfirmed", "superseded", "timed_out",
                }
            for record in (meta.get("actions") or {}).values():
                assert record.phase in {
                    "accepted", "confirmed", "idempotent_confirmed", "failed",
                    "unconfirmed", "superseded", "timed_out",
                }


def test_old_ctrl_mapping_ignores_action_fields_and_recovers_status():
    """旧 Ctrl 只读 status/source/status_source 时仍可收敛。"""
    cache = ContainerStatusCache()
    container = FakeRuntimeContainer("c1", status="running")
    _seed_online(cache, "c1", container)
    ref = cache.accept_action("c1", "pause", "pausing")
    _finish(cache, "c1", ref, "failed", "docker_api_error")
    payload = cache.list_states()

    class OldCtrlMapper:
        def apply(self, entry):
            # 旧消费方只理解既有状态与来源字段。
            return {
                "status": entry.get("status"),
                "source": entry.get("source"),
                "status_source": entry.get("status_source"),
            }

    mapped = OldCtrlMapper().apply(payload["c1"])
    assert mapped["status"] == "online"
    assert "last_action" not in mapped
    assert json.loads(json.dumps(payload))["c1"]["last_action"]["phase"] == "failed"


def test_verify_bind_fields_are_independent_of_runtime_actions():
    """运行态动作/对象代际不得改写磁盘路径/测量诊断。"""
    from FuxiYu_NodeKernel.docker_operates.disk_usage_cache import DiskUsageCache, _utc_z

    disk = DiskUsageCache()
    disk._path_state["c1"] = {
        "bind_mount_path": "/biz/c1",
        "mount_path_status": "unresolved",
    }
    disk._container_cache["c1"] = {
        "usage": {
            "container_name": "c1",
            "overlay_rw_bytes": 100,
            "bind_mount_bytes": 200,
            "bind_mount_path": "/biz/c1",
            "mount_path_status": "unresolved",
            "bind_mount_source": "fresh",
            "total_bytes": 300,
            "error": None,
            "measured_at": _utc_z(),
        },
        "updated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    }
    before = disk.snapshot()["containers"]["c1"]

    cache = ContainerStatusCache()
    container = FakeRuntimeContainer("c1", status="running")
    _seed_online(cache, "c1", container)
    ref = cache.accept_action("c1", "start", "starting")
    _finish(cache, "c1", ref, "confirmed")
    ref = cache.accept_action("c1", "pause", "pausing")
    _finish(cache, "c1", ref, "failed", "docker_api_error")

    after = disk.snapshot()["containers"]["c1"]
    for key in (
        "bind_mount_path",
        "mount_path_status",
        "overlay_rw_bytes",
        "bind_mount_bytes",
        "total_bytes",
        "measured_at",
        "bind_mount_source",
        "error",
    ):
        assert after[key] == before[key]
    assert not {
        "configured_mount_path",
        "mount_path_observed_at",
        "measurement_status",
        "measurement_mount_path",
        "measurement_reason",
        "disk_protocol_version",
        "collector_epoch",
        "observation_seq",
    } & set(after)


def test_wipe_old_epoch_and_last_action_after_restart(monkeypatch):
    old = ContainerStatusCache()
    container = FakeRuntimeContainer("c1", status="running")
    _seed_online(old, "c1", container)
    old_ref = old.accept_action("c1", "pause", "pausing")

    new = ContainerStatusCache()
    assert new.node_epoch != old.node_epoch
    assert new.get_state("c1").get("last_action") is None
    assert new.finish_action_ref({**old_ref, "name": "c1"}, "confirmed") is False
