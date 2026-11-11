"""guard 6.1/6.2：真实入口的确定屏障、时序日志与 Sylvan 慢 list/stats 回放。

屏障由测试包装注入，生产代码不埋测试钩子；不使用 sleep 猜测时序。
"""
from __future__ import annotations

import threading
import time

from fastapi.testclient import TestClient

from FuxiYu_NodeKernel import create_app, extensions
from FuxiYu_NodeKernel.constant import ContainerStatus
from FuxiYu_NodeKernel.docker_operates import status_cache as status_module
from FuxiYu_NodeKernel.docker_operates.docker_fact import fact_from_container
from FuxiYu_NodeKernel.docker_operates.status_cache import ContainerStatusCache
from FuxiYu_NodeKernel.network import api as api_module
from FuxiYu_NodeKernel.network import wss
from FuxiYu_NodeKernel.services import container_service

from .runtime_fakes import (
    FakeRuntimeClient,
    FakeRuntimeContainer,
    install_runtime,
    Trace,
)


def wait_for(predicate, timeout: float = 3.0, interval: float = 0.01):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def _seed_online(cache: ContainerStatusCache, container: FakeRuntimeContainer):
    ticket = cache.issue_observation(container.name, "seed")
    assert cache.publish_observed(container.name, ticket, fact_from_container(container), mark_ready=True)


def _start_payload(name: str) -> dict:
    return {"config": {"container_name": name}}


def _unpause_payload(name: str) -> dict:
    return {"config": {"container_name": name, "action": "unpause"}}


def test_injected_barriers_cover_accept_ref_ticket_queue_docker_http_wss_delete_event(monkeypatch):
    trace = Trace()
    cache = ContainerStatusCache()
    monkeypatch.setattr(extensions, "status_cache", cache)
    container = FakeRuntimeContainer("c1", status="exited", docker_id="A")
    container.on_reload = lambda c: trace.add("docker:reload")
    install_runtime(monkeypatch, [container])

    original_build = cache._build_action_locked
    original_issue = cache.issue_observation
    original_start = container.start

    def traced_build(*args, **kwargs):
        trace.add("accept:enter")
        record = original_build(*args, **kwargs)
        trace.add(f"accept:ref:{record.ref['seq']}")
        return record

    def traced_issue(*args, **kwargs):
        trace.add("ticket:issue")
        return original_issue(*args, **kwargs)

    monkeypatch.setattr(cache, "_build_action_locked", traced_build)
    monkeypatch.setattr(cache, "issue_observation", traced_issue)

    docker_entered = threading.Event()
    docker_release = threading.Event()

    def traced_start(*args, **kwargs):
        trace.add("docker:start:enter")
        docker_entered.set()
        assert docker_release.wait(3)
        result = original_start(*args, **kwargs)
        trace.add("docker:start:exit")
        return result

    container.start = traced_start

    def traced_execute(name, action, ref):
        trace.add("queue:take")
        return container_service.execute_container_action(name, action, ref)

    monkeypatch.setattr(api_module, "execute_container_action", traced_execute)

    status_entered = threading.Event()
    status_release = threading.Event()

    def slow_status():
        trace.add("http:status:enter")
        status_entered.set()
        assert status_release.wait(3)
        trace.add("http:status:exit")
        return cache.list_states()

    monkeypatch.setattr(api_module, "list_container_status", slow_status)
    original_wss_status = wss.build_status_snapshot

    def traced_wss_status():
        trace.add("wss:snapshot")
        return original_wss_status()

    monkeypatch.setattr(wss, "build_status_snapshot", traced_wss_status)
    monkeypatch.setattr(cache, "take_confirmed_deleted", lambda: trace.add("delete:take") or [])

    client = TestClient(create_app())
    start_resp = client.post("/api/start_container", json=_start_payload("c1"))
    trace.add("http:start:ack")
    assert start_resp.status_code == 200
    assert docker_entered.wait(2)

    status_result = {}

    def _status_call():
        status_result["resp"] = client.post(
            "/api/container_status", json={"config": {"container_name": "c1"}}
        )

    status_thread = threading.Thread(target=_status_call)
    status_thread.start()
    assert status_entered.wait(2)
    status_release.set()
    status_thread.join(3)
    trace.add("http:status:ack")
    assert status_result["resp"].status_code == 200

    wss.build_status_snapshot()
    cache.take_confirmed_deleted()
    trace.add("event:deliver")
    cache._apply_event({"Action": "pause", "Actor": {"Attributes": {"name": "c1"}}})
    trace.add("event:delivered")

    docker_release.set()
    assert wait_for(
        lambda: cache.get_state("c1")["last_action"]["phase"] == "confirmed"
    )
    trace.add("http:start:done")

    labels = trace.labels()
    for expected in (
        "accept:enter",
        "accept:ref:1",
        "ticket:issue",
        "queue:take",
        "docker:start:enter",
        "http:start:ack",
        "http:status:enter",
        "http:status:exit",
        "http:status:ack",
        "wss:snapshot",
        "delete:take",
        "event:deliver",
        "docker:start:exit",
        "http:start:done",
    ):
        assert expected in labels, (expected, labels)
    assert labels.index("accept:enter") < labels.index("queue:take")
    assert labels.index("queue:take") < labels.index("docker:start:enter")
    # 工作线程可能先进入阻塞的 Docker 调用，HTTP ACK 随后返回；两者都必须在
    # Docker 调用返回前发生，不以调度顺序猜测 ACK 一定先于线程启动。
    assert labels.index("http:start:ack") < labels.index("docker:start:exit")
    assert labels.index("http:status:enter") < labels.index("http:status:exit")
    assert labels.index("docker:start:enter") < labels.index("docker:start:exit")


def test_sylvan_timeline_real_slow_list_and_stats_does_not_rollback(monkeypatch):
    trace = Trace()
    cache = ContainerStatusCache()
    monkeypatch.setattr(extensions, "status_cache", cache)
    fresh = FakeRuntimeContainer("Sylvan", status="running", docker_id="A")
    listed = FakeRuntimeContainer("Sylvan", status="paused", docker_id="A")
    stats_done = {"value": False}
    fresh.on_reload = lambda c: trace.add(
        "reload:fresh:post_stats" if stats_done["value"] else "reload:fresh:pre_stats"
    )
    listed.on_reload = lambda c: trace.add("reload:listed")
    client = FakeRuntimeClient([fresh])
    monkeypatch.setattr(extensions, "docker_client", client)
    monkeypatch.setattr(
        "FuxiYu_NodeKernel.docker_operates.status_cache.docker.from_env", lambda: client
    )
    _seed_online(cache, fresh)

    list_entered = threading.Event()
    list_release = threading.Event()
    stats_entered = threading.Event()
    stats_release = threading.Event()

    def slow_list(*args, **kwargs):
        trace.add("list:enter")
        list_entered.set()
        assert list_release.wait(3)
        trace.add("list:exit")
        return [listed]

    client.containers.list = slow_list
    original_metrics = status_module._container_runtime_metrics

    def slow_metrics(container, gpu_runtime_by_index=None):
        trace.add("stats:enter")
        stats_entered.set()
        assert stats_release.wait(3)
        result = original_metrics(container, gpu_runtime_by_index)
        stats_done["value"] = True
        trace.add("stats:exit")
        return result

    monkeypatch.setattr(status_module, "_container_runtime_metrics", slow_metrics)
    original_publish = cache.publish_observed

    def traced_publish(name, ticket, fact, **kwargs):
        ok = original_publish(name, ticket, fact, **kwargs)
        trace.add(f"publish:{name}:{ok}")
        return ok

    monkeypatch.setattr(cache, "publish_observed", traced_publish)

    reconcile_result = {}

    def _reconcile():
        cache._reconcile_once()
        reconcile_result["done"] = True

    reconcile_thread = threading.Thread(target=_reconcile, name="reconcile")
    reconcile_thread.start()
    assert list_entered.wait(2)

    api = TestClient(create_app())
    first = api.post("/api/pause_container", json=_unpause_payload("Sylvan"))
    assert first.status_code == 200
    assert wait_for(
        lambda: cache.get_state("Sylvan")["last_action"]["phase"] == "idempotent_confirmed"
    )
    trace.add("api:first_unpause:done")

    list_release.set()
    assert stats_entered.wait(2)
    second = api.post("/api/pause_container", json=_unpause_payload("Sylvan"))
    assert second.status_code == 200
    assert wait_for(
        lambda: cache.get_state("Sylvan")["last_action"]["phase"] == "idempotent_confirmed"
        and cache.get_state("Sylvan")["last_action"]["ref"] == second.json()["action_ref"]
    )
    trace.add("api:second_unpause:done")

    stats_release.set()
    reconcile_thread.join(3)
    assert reconcile_result.get("done") is True

    state = cache.get_state("Sylvan")
    assert state["status"] == ContainerStatus.ONLINE.value
    assert state["status"] != ContainerStatus.FAILED.value
    assert state["last_action"]["phase"] == "idempotent_confirmed"
    assert "unpause_failed" not in str(state)
    assert fresh.unpause_calls == 0

    labels = trace.labels()
    assert "list:enter" in labels
    assert "stats:enter" in labels
    assert "api:first_unpause:done" in labels
    assert "api:second_unpause:done" in labels
    assert "reload:fresh:post_stats" in labels
    assert labels.index("list:enter") < labels.index("api:first_unpause:done") < labels.index("list:exit")
    assert labels.index("stats:enter") < labels.index("api:second_unpause:done") < labels.index("stats:exit")
    assert labels.index("stats:exit") < labels.index("reload:fresh:post_stats")
    assert "publish:Sylvan:True" in labels
