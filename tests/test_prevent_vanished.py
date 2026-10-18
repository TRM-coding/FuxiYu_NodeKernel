"""prevent-false-container-vanished 的受控交错回归。

真实入口：status_cache._reconcile_once / take_confirmed_deleted / WSS 推送循环。
Docker 只替换为可编程客户端，测试不依赖真实 daemon。
"""
from __future__ import annotations

import json
import asyncio

from FuxiYu_NodeKernel import extensions
from FuxiYu_NodeKernel.docker_operates.docker_fact import fact_from_container
from FuxiYu_NodeKernel.docker_operates.status_cache import ContainerStatusCache
from FuxiYu_NodeKernel.network import wss

from .runtime_fakes import (
    FakeRuntimeContainer,
    FakeRuntimeContainers,
    install_runtime,
    not_found,
)


def _seed(cache, container):
    ticket = cache.issue_observation(container.name, "seed")
    assert cache.publish_observed(container.name, ticket, fact_from_container(container), mark_ready=True)


def _reconcile(monkeypatch, cache, client):
    monkeypatch.setattr(
        "FuxiYu_NodeKernel.docker_operates.status_cache.docker.from_env", lambda: client
    )
    cache._reconcile_once()


def test_create_during_enumeration_is_not_vanished(monkeypatch):
    cache = ContainerStatusCache()
    old = FakeRuntimeContainer("old", status="running")
    _seed(cache, old)
    client = install_runtime(monkeypatch, [old])

    new = FakeRuntimeContainer("new", status="running")

    def _during_get(container):
        # 枚举开始后才受理/创建的新容器：不在本轮较早的 live 列表中。
        if not hasattr(client, "_created_during"):
            client._created_during = True
            cache.accept_action("new", "create", "creating", create=True)
            client.containers._containers.append(new)

    client.containers.after_get = _during_get
    _reconcile(monkeypatch, cache, client)

    assert cache.get_state("new")["status"] == "creating"
    assert cache.take_deleted() == []


def test_in_flight_create_is_not_cleared_by_empty_list(monkeypatch):
    cache = ContainerStatusCache()
    ref = cache.accept_action("new", "create", "building", create=True)
    client = install_runtime(monkeypatch, [])
    _reconcile(monkeypatch, cache, client)

    state = cache.get_state("new")
    assert state["status"] == "building"
    assert state["last_action"]["ref"] == ref
    assert cache.take_deleted() == []


def test_same_name_create_during_enumeration_invalidates_old_delete_candidate(monkeypatch):
    cache = ContainerStatusCache()
    old = FakeRuntimeContainer("c1", status="running")
    _seed(cache, old)
    client = install_runtime(monkeypatch, [old])

    def _replace(container):
        cache.accept_action("c1", "create", "creating", create=True)
        client.containers._containers = []  # 旧对象在本轮枚举后消失

    client.containers.after_get = _replace
    _reconcile(monkeypatch, cache, client)

    assert cache.get_state("c1")["status"] == "creating"
    assert cache._deleted == []


def test_create_acceptance_cancels_queued_delete_candidate():
    cache = ContainerStatusCache()
    cache._deleted = [{"name": "c1", "generation": cache._meta_for("c1")["generation"]}]
    ref = cache.accept_action("c1", "create", "creating", create=True)
    assert cache._deleted == []
    assert cache.get_state("c1")["last_action"]["ref"] == ref


def test_docker_still_exists_keeps_cache_and_does_not_queue(monkeypatch):
    cache = ContainerStatusCache()
    known = FakeRuntimeContainer("c1", status="running")
    _seed(cache, known)
    client = install_runtime(monkeypatch, [known])
    # 列表漏报，但单容器确认仍找到对象。
    client.containers.list = lambda *a, **k: []
    _reconcile(monkeypatch, cache, client)
    assert cache.get("c1") is not None
    assert cache.take_deleted() == []


def test_confirmed_delete_clears_action_diagnostic_and_rejects_late_finish(monkeypatch):
    cache = ContainerStatusCache()
    known = FakeRuntimeContainer("c1", status="running")
    _seed(cache, known)
    ref = cache.accept_action("c1", "pause", "pausing")
    assert cache.finish_action_ref({**ref, "name": "c1"}, "failed", "state_mismatch")
    assert cache.get_state("c1")["last_action"]["ref"] == ref

    client = install_runtime(monkeypatch, [])
    client.containers.get = lambda name: (_ for _ in ()).throw(not_found(str(name)))
    _reconcile(monkeypatch, cache, client)
    assert cache.take_confirmed_deleted() == ["c1"]

    state = cache.get_state("c1")
    assert state["source"] == "miss"
    assert state.get("last_action") is None
    assert cache.finish_action_ref({**ref, "name": "c1"}, "confirmed") is False
    assert cache.get_state("c1").get("last_action") is None


def test_external_delete_queues_once_and_wss_sends_delete_before_snapshot(monkeypatch):
    cache = ContainerStatusCache()
    gone = FakeRuntimeContainer("c1", status="running")
    _seed(cache, gone)
    client = install_runtime(monkeypatch, [])
    client.containers.get = lambda name: (_ for _ in ()).throw(not_found(str(name)))
    _reconcile(monkeypatch, cache, client)

    assert cache.take_confirmed_deleted() == ["c1"]
    assert cache.take_confirmed_deleted() == []  # 只发送一次

    # 再制造一个候选，走真实 WSS 推送循环验证帧顺序。
    cache2 = ContainerStatusCache()
    gone2 = FakeRuntimeContainer("old", status="running")
    _seed(cache2, gone2)
    client2 = install_runtime(monkeypatch, [])
    client2.containers.get = lambda name: (_ for _ in ()).throw(not_found(str(name)))
    _reconcile(monkeypatch, cache2, client2)
    monkeypatch.setattr(extensions, "status_cache", cache2)
    monkeypatch.setattr(extensions.status_cache, "take_confirmed_deleted", lambda: ["old"])
    monkeypatch.setattr(wss, "load_node_identity", lambda: wss.NodeIdentity(uid="u"))
    monkeypatch.setattr(wss, "list_container_status", lambda: {})
    monkeypatch.setattr(wss, "list_last_ssh", lambda: {})
    monkeypatch.setattr(wss, "list_disk_usage", lambda: {"containers": {}})
    monkeypatch.setattr(wss, "list_sys_snapshot", lambda: {})

    class _WS:
        def __init__(self):
            self.scope = {"query_string": b"uid=u"}
            self.frames = []
            self.accepted = False

        async def accept(self):
            self.accepted = True

        async def close(self, code=None):
            pass

        async def send_text(self, text):
            self.frames.append(json.loads(text))

        async def receive(self):
            return {"type": "websocket.disconnect", "code": 1000}

    ws = _WS()
    asyncio.run(wss.handle_ctrl_ws(ws))
    assert ws.frames[0] == {"type": "delete", "container_name": "old"}
    assert ws.frames[1]["type"] == "snapshot_batch"


def test_failed_confirmation_keeps_candidate_and_collect_error(monkeypatch):
    cache = ContainerStatusCache()
    gone = FakeRuntimeContainer("c1", status="running")
    _seed(cache, gone)
    client = install_runtime(monkeypatch, [])
    client.containers.get = lambda name: (_ for _ in ()).throw(RuntimeError("docker down"))
    _reconcile(monkeypatch, cache, client)
    assert cache.get("c1") is not None
    assert cache.get_collect_error() == "collect_failed"
    assert cache.take_deleted() == []
