"""guard 6.6/6.7：Node 帧/ref 契约的独立消费方夹具。

这里不修改、也不声称联调 Ctrl。消费方是测试内的最小本地夹具，只验证
Node 真实 HTTP/WSS 字段与 exact ref/方向/终结相位契约；缺字段、旧 ref、
未知 phase 的降级由消费方自身 timeout 承担。
"""
from __future__ import annotations

import json
import threading
import time

from fastapi.testclient import TestClient

from FuxiYu_NodeKernel import create_app, extensions
from FuxiYu_NodeKernel.constant import ContainerStatus
from FuxiYu_NodeKernel.docker_operates.docker_fact import fact_from_container
from FuxiYu_NodeKernel.docker_operates.status_cache import ContainerStatusCache
from FuxiYu_NodeKernel.network import api as api_module
from FuxiYu_NodeKernel.network import wss
from FuxiYu_NodeKernel.schemas import (
    ContainerOperationAcceptedResponse,
    ContainerStatusResponse,
    CreateContainerResponse,
)
from FuxiYu_NodeKernel.services.container_service import ActionExecutionResult

from .runtime_fakes import FakeRuntimeContainer

TERMINAL_PHASES = {"confirmed", "idempotent_confirmed", "failed", "superseded"}


def wait_for(predicate, timeout: float = 3.0, interval: float = 0.01):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def _seed_online(cache: ContainerStatusCache, name: str = "c1"):
    container = FakeRuntimeContainer(name, status="running")
    ticket = cache.issue_observation(name, "seed")
    assert cache.publish_observed(name, ticket, fact_from_container(container), mark_ready=True)
    return container


class LocalConsumer:
    """独立消费方夹具：精确 ref + action 方向 + 终结 phase 才结束自身过渡。"""

    def __init__(self):
        self.pending = {}
        self.early = {}
        self.ended = []
        self.timeouts = 0

    @staticmethod
    def key(ref: dict) -> tuple:
        return (ref["node_epoch"], ref["generation"], ref["seq"])

    def ack(self, ref: dict, action: str):
        key = self.key(ref)
        self.pending[key] = action
        early = self.early.get(key)
        if early is not None:
            self._apply_early(key, early)

    def wss(self, entry: dict):
        last = entry.get("last_action")
        if not last:
            return
        key = self.key(last["ref"])
        if key not in self.pending:
            # 终结帧可能早于 ACK；按 ref 有界暂存。
            if last.get("phase") in TERMINAL_PHASES:
                self.early[key] = last
            return
        self._apply(key, last)

    def _apply_early(self, key, last):
        if self.pending.get(key) == last.get("action") and last.get("phase") in TERMINAL_PHASES:
            self.pending.pop(key, None)
            self.ended.append(key)

    def _apply(self, key, last):
        action = self.pending.get(key)
        if action is None:
            return
        if last.get("action") != action or last.get("phase") not in TERMINAL_PHASES:
            return
        self.pending.pop(key, None)
        self.ended.append(key)

    def timeout(self):
        self.timeouts += 1
        self.pending.clear()


def _entry(cache: ContainerStatusCache, name: str = "c1") -> dict:
    return cache.list_states()[name]


def test_ack_first_and_wss_first_close_exact_ref_without_ack_forced_failure(monkeypatch):
    cache = ContainerStatusCache()
    monkeypatch.setattr(extensions, "status_cache", cache)
    _seed_online(cache)
    consumer = LocalConsumer()

    started = threading.Event()
    release = threading.Event()

    def blocked_runner(name, action, ref):
        started.set()
        assert release.wait(3)
        return ActionExecutionResult("confirmed")

    monkeypatch.setattr(api_module, "execute_container_action", blocked_runner)
    client = TestClient(create_app())

    # 真实 HTTP 受理：ACK 先到，动作尚未完成；WSS 先发 accepted，随后同 ref 终结。
    response = client.post(
        "/api/pause_container",
        json={"config": {"container_name": "c1", "action": "pause"}},
    )
    assert response.status_code == 200
    body = response.json()
    ref = body["action_ref"]
    assert ref["node_epoch"] == cache.node_epoch
    assert started.wait(2)
    assert body["container_status"] == "pausing"
    consumer.ack(ref, "pause")
    assert _entry(cache)["last_action"]["phase"] == "accepted"
    consumer.wss(_entry(cache))
    assert not consumer.ended
    assert cache.get_state("c1")["last_action"]["phase"] != "failed"
    release.set()
    assert wait_for(
        lambda: (cache.get_state("c1").get("last_action") or {}).get("phase") == "confirmed"
    )
    consumer.wss(_entry(cache))
    assert consumer.ended == [consumer.key(ref)]
    assert not consumer.pending
    assert "last_action" in json.loads(json.dumps(_entry(cache)))

    # WSS 终结先到：按 ref 暂存，ACK 到达后才结束过渡。
    ref2 = cache.accept_action("c1", "pause", "pausing")
    assert cache.finish_action_ref({**ref2, "name": "c1"}, "confirmed")
    consumer.wss(_entry(cache))
    assert not consumer.ended[1:]
    assert consumer.key(ref2) in consumer.early
    consumer.ack(ref2, "pause")
    assert consumer.ended[-1] == consumer.key(ref2)
    assert not consumer.pending


def test_consumer_rejects_old_ref_wrong_direction_and_unknown_phase_without_failed():
    cache = ContainerStatusCache()
    _seed_online(cache)
    consumer = LocalConsumer()

    ref = cache.accept_action("c1", "pause", "pausing")
    other_ref = {**ref, "seq": ref["seq"] + 1}
    consumer.ack(other_ref, "pause")
    assert cache.finish_action_ref({**ref, "name": "c1"}, "confirmed")
    consumer.wss(_entry(cache))
    assert not consumer.ended
    assert consumer.pending  # 旧/未知 ref 只能由自身 timeout 降级，Node 不伪造 failed

    consumer = LocalConsumer()
    ref = cache.accept_action("c1", "pause", "pausing")
    consumer.ack(ref, "start")
    assert cache.finish_action_ref({**ref, "name": "c1"}, "confirmed")
    consumer.wss(_entry(cache))
    assert not consumer.ended
    assert consumer.pending

    consumer.wss({"status": "online"})
    consumer.wss({"status": "online", "last_action": {"ref": ref, "action": "pause", "phase": "unknown"}})
    assert not consumer.ended
    consumer.timeout()
    assert consumer.timeouts == 1
    assert cache.get_state("c1")["last_action"]["phase"] in {"confirmed", "accepted", "superseded"}


def test_mixed_version_missing_optional_fields_and_restart_epoch():
    old_node_frame = {"status": "online", "source": "cache"}
    consumer = LocalConsumer()
    consumer.wss(old_node_frame)
    consumer.timeout()
    assert consumer.timeouts == 1

    old = ContainerStatusCache()
    _seed_online(old, "c1")
    old_ref = old.accept_action("c1", "pause", "pausing")

    new = ContainerStatusCache()
    assert new.node_epoch != old.node_epoch
    assert new.get_state("c1").get("last_action") is None
    assert new.finish_action_ref({**old_ref, "name": "c1"}, "confirmed") is False
    assert new.get_state("c1").get("last_action") is None

    old_ctrl_visible = {
        "success": 1,
        "container_status": "online",
        "container_name": "c1",
    }
    old_ctrl = ContainerStatusResponse(**old_ctrl_visible, last_action=None)
    assert old_ctrl.model_dump()["last_action"] is None
    assert old_ctrl.model_dump()["container_status"] == ContainerStatus.ONLINE.value

    accepted = ContainerOperationAcceptedResponse(
        success=1,
        container_status="pausing",
        container_name="c1",
        action_ref={"node_epoch": new.node_epoch, "generation": 0, "seq": 1},
    )
    assert accepted.model_dump()["action_ref"]["seq"] == 1
    created = CreateContainerResponse(
        success=1,
        container_status="creating",
        container_name="c1",
        action_ref={"node_epoch": new.node_epoch, "generation": 1, "seq": 1},
    )
    assert created.model_dump()["action_ref"]["generation"] == 1


def test_soft_failure_wire_keeps_online_and_failed_only_in_last_action(monkeypatch):
    cache = ContainerStatusCache()
    monkeypatch.setattr(extensions, "status_cache", cache)
    _seed_online(cache)
    ref = cache.accept_action("c1", "pause", "pausing")
    assert cache.finish_action_ref({**ref, "name": "c1"}, "failed", "state_mismatch")

    entry = _entry(cache)
    assert entry["status"] == ContainerStatus.ONLINE.value
    assert entry["last_action"]["phase"] == "failed"
    assert entry["last_action"]["error_reason"] == "state_mismatch"
    wire = json.loads(json.dumps(_entry(cache)))
    assert wire["status"] == "online"
    assert wire["last_action"]["ref"] == ref
    assert wss.build_status_snapshot()["payload"]["c1"]["last_action"]["phase"] == "failed"
