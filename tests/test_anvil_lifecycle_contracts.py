"""container lifecycle 测试映射缺口回归。

只替换 Docker/事件日志等外部边界；状态机、HTTP/WSS、服务动作入口都走真实实现。
所有异步路径使用确定性状态/屏障断言，不 sleep 猜结束。
"""
from __future__ import annotations

import datetime
import logging
import time

import docker
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from FuxiYu_NodeKernel import create_app, extensions
from FuxiYu_NodeKernel.constant import ContainerStatus as InternalContainerStatus
from FuxiYu_NodeKernel.constant import MachineStatus, MachineTypes
from FuxiYu_NodeKernel.docker_operates.docker_fact import fact_from_container
from FuxiYu_NodeKernel.docker_operates.status_cache import ContainerStatusCache
from FuxiYu_NodeKernel.network import wss
from FuxiYu_NodeKernel.network.api import _container_name
from FuxiYu_NodeKernel.schemas.common import EmptyConfig
from FuxiYu_NodeKernel.schemas.container import (
    ContainerLastSshTimeMessage,
    ContainerLastSshTimeResponse,
    ContainerNameConfig,
    ContainerNameMessage,
    ContainerOperationAcceptedResponse,
    ContainerStatusMessage,
    ContainerStatusResponse,
    LastSshTimeResponse,
    MachineStatusMessage,
    MachineStatusResponse,
    PauseContainerConfig,
    PauseContainerMessage,
    PauseContainerResponse,
    RemoveContainerMessage,
    RemoveContainerResponse,
    RestartContainerMessage,
    RestartContainerResponse,
    StartContainerMessage,
    StartContainerResponse,
    StopContainerMessage,
    StopContainerResponse,
)
from FuxiYu_NodeKernel.services.container_service import (
    RemoveContinaerReturn,
    execute_pause_action,
    remove_container,
)

from .runtime_fakes import FakeRuntimeContainer, install_runtime, not_found


@pytest.fixture(autouse=True)
def _isolate_globals(monkeypatch):
    """每个测试从干净 cache/docker 入口开始；patch 结束后自动还原。"""
    monkeypatch.setattr(extensions, "status_cache", ContainerStatusCache())
    monkeypatch.setattr(extensions, "docker_client", None)
    yield


def _seed(cache: ContainerStatusCache, name: str, container, *, mark_ready: bool = False) -> None:
    ticket = cache.issue_observation(name, "seed")
    assert cache.publish_observed(
        name,
        ticket,
        fact_from_container(container),
        mark_ready=mark_ready,
    )


def _finish(cache: ContainerStatusCache, name: str, ref: dict, phase: str, reason: str | None = None) -> bool:
    return cache.finish_action_ref({**ref, "name": name}, phase, reason)


def _install(monkeypatch, containers):
    client = install_runtime(monkeypatch, containers)
    monkeypatch.setattr(
        "FuxiYu_NodeKernel.docker_operates.status_cache.docker.from_env",
        lambda: client,
    )
    return client


def test_name_config_alias_and_field_validation():
    empty = ContainerNameConfig()
    assert empty.container_name is None
    assert empty.name is None
    alias = ContainerNameConfig(name="legacy")
    assert alias.container_name is None
    assert alias.name == "legacy"
    both = ContainerNameConfig(container_name="primary", name="legacy")
    assert _container_name(both) == "primary"
    assert _container_name(alias) == "legacy"
    assert _container_name(empty) is None
    with pytest.raises(ValidationError):
        ContainerNameConfig(container_name=123)


def test_container_message_models_require_config():
    for model in (
        ContainerStatusMessage,
        ContainerLastSshTimeMessage,
        RemoveContainerMessage,
        StartContainerMessage,
        StopContainerMessage,
        RestartContainerMessage,
        PauseContainerMessage,
    ):
        instance = model(config={"container_name": "c1"})
        assert instance.config.container_name == "c1"
        with pytest.raises(ValidationError):
            model()

    machine = MachineStatusMessage()
    assert isinstance(machine.config, EmptyConfig)
    assert machine.model_dump() == {"config": {}}
    assert MachineStatusMessage(config={}).model_dump() == {"config": {}}


def test_container_response_models_default_success_and_optional_fields():
    accepted = ContainerOperationAcceptedResponse(container_status="online", container_name="c1")
    assert accepted.success == 1
    assert accepted.action_ref is None
    assert accepted.model_dump()["action_ref"] is None

    for model, status in (
        (StartContainerResponse, "starting"),
        (StopContainerResponse, "stopping"),
        (RestartContainerResponse, "restarting"),
        (PauseContainerResponse, "pausing"),
    ):
        instance = model(container_status=status, container_name="c1")
        assert instance.success == 1
        assert instance.action_ref is None

    status_response = ContainerStatusResponse(container_status="online", container_name="c1")
    assert status_response.success == 1
    assert status_response.last_action is None
    for field in (
        "cache_updated_at",
        "error",
        "error_reason",
        "failed_reason",
        "failed_detail",
        "runtime_metrics",
        "status_source",
        "unknown_since",
    ):
        assert getattr(status_response, field) is None
    with pytest.raises(ValidationError):
        ContainerStatusResponse(container_status="sleeping", container_name="c1")
    with pytest.raises(ValidationError):
        ContainerOperationAcceptedResponse(container_status="online")

    ssh_response = ContainerLastSshTimeResponse(
        container_name="c1",
        last_ssh_connect_time="2026-10-28T00:00:00",
    )
    assert ssh_response.success == 1
    with pytest.raises(ValidationError):
        ContainerLastSshTimeResponse(container_name="c1")

    machine_response = MachineStatusResponse(machine_status="online")
    assert machine_response.success == 1
    with pytest.raises(ValidationError):
        MachineStatusResponse(machine_status="sleeping")

    assert RemoveContainerResponse().success == 1


def test_pause_config_default_and_literal_rejection():
    default = PauseContainerConfig(container_name="c1")
    assert default.action == "pause"
    assert PauseContainerConfig(container_name="c1", action="unpause").action == "unpause"
    with pytest.raises(ValidationError):
        PauseContainerConfig(container_name="c1", action="resume")


def test_container_status_literal_domain():
    values = (
        "building",
        "creating",
        "starting",
        "stopping",
        "restarting",
        "pausing",
        "unpausing",
        "ready_check",
        "online",
        "offline",
        "paused",
        "failed",
        "unknown",
    )
    for value in values:
        response = ContainerStatusResponse(container_status=value, container_name="c1")
        assert response.container_status == value
    with pytest.raises(ValidationError):
        ContainerStatusResponse(container_status="sleeping", container_name="c1")


def test_wire_alias_models_preserve_shapes():
    alias = ContainerNameMessage(config={"container_name": "c1", "name": "legacy"})
    base = ContainerStatusMessage(config={"container_name": "c1", "name": "legacy"})
    assert alias.model_dump()["config"] == base.model_dump()["config"]
    assert alias.model_dump()["config"]["container_name"] == "c1"
    with pytest.raises(ValidationError):
        ContainerNameMessage()

    ssh_alias = LastSshTimeResponse(container_name="c1", last_ssh_connect_time="t")
    ssh_base = ContainerLastSshTimeResponse(container_name="c1", last_ssh_connect_time="t")
    assert ssh_alias.model_dump() == ssh_base.model_dump()
    assert ssh_alias.success == 1
    with pytest.raises(ValidationError):
        LastSshTimeResponse(container_name="c1")


def test_internal_enums_and_remove_result_contracts():
    assert {member.value for member in MachineTypes} == {"GPU", "CPU"}
    assert RemoveContinaerReturn.SUCCESS == 0
    assert RemoveContinaerReturn.NOTFOUND == 1
    assert RemoveContinaerReturn.FAILED == 2

    class _Container:
        def __init__(self, owner):
            self.owner = owner
            self.removed = False

        def remove(self, *args, **kwargs):
            self.removed = True
            self.owner.items.pop("c1", None)

    class _Containers:
        def __init__(self):
            self.items = {"c1": _Container(self)}

        def get(self, name):
            if name in self.items:
                return self.items[name]
            raise not_found(str(name))

    class _Client:
        def __init__(self):
            self.containers = _Containers()

    client = _Client()
    extensions.docker_client = client
    assert remove_container("c1") == RemoveContinaerReturn.SUCCESS
    assert client.containers.items == {}
    assert client.containers.items.get("c1") is None


def test_internal_enum_type_boundary():
    assert {member.name: member.value for member in InternalContainerStatus} == {
        "ONLINE": "online",
        "OFFLINE": "offline",
        "BUILDING": "building",
        "CREATING": "creating",
        "STARTING": "starting",
        "RESTARTING": "restarting",
        "STOPPING": "stopping",
        "FAILED": "failed",
        "PAUSED": "paused",
        "UNKNOWN": "unknown",
    }
    with pytest.raises(ValidationError):
        ContainerStatusResponse(
            container_status=InternalContainerStatus.ONLINE,
            container_name="c1",
        )
    accepted = ContainerStatusResponse(
        container_status=InternalContainerStatus.ONLINE.value,
        container_name="c1",
    )
    assert accepted.container_status == "online"


def test_machine_status_type_boundary():
    assert {member.name: member.value for member in MachineStatus} == {
        "ONLINE": "online",
        "OFFLINE": "offline",
        "MAINTENANCE": "maintenance",
    }
    with pytest.raises(ValidationError):
        MachineStatusResponse(machine_status=MachineStatus.ONLINE)
    assert MachineStatusResponse(machine_status="online").machine_status == "online"


def test_status_response_hard_block_fields(monkeypatch):
    client = TestClient(create_app())
    hard = ContainerStatusCache()
    hard.set_hard_block("c1", "sshd_not_installed", "missing")
    monkeypatch.setattr(extensions, "status_cache", hard)

    resp = client.post("/api/container_status", json={"config": {"container_name": "c1"}})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] == 0
    assert body["container_status"] == "failed"
    assert body["error"] == "operation failed"
    assert body["error_reason"] == "sshd_not_installed"
    assert body["failed_reason"] == "sshd_not_installed"
    assert body["failed_detail"] == "missing"
    assert body["last_action"] is None

    soft = ContainerStatusCache()
    container = FakeRuntimeContainer("c1", status="running")
    _seed(soft, "c1", container, mark_ready=True)
    ref = soft.accept_action("c1", "pause", "pausing")
    assert _finish(soft, "c1", ref, "failed", "docker_api_error")
    monkeypatch.setattr(extensions, "status_cache", soft)

    soft_body = client.post(
        "/api/container_status",
        json={"config": {"container_name": "c1"}},
    ).json()
    assert soft_body["success"] == 1
    assert soft_body["container_status"] == "online"
    assert soft_body["last_action"]["phase"] == "failed"
    assert soft_body["error_reason"] is None
    assert soft_body["failed_reason"] is None
    assert soft_body["failed_detail"] is None


def test_last_ssh_wss_allows_none():
    cache = extensions.last_ssh_cache
    with cache._lock:
        cache._cache["c1"] = {
            "value": None,
            "updated_at": datetime.datetime.utcnow(),
        }
    try:
        frame = wss.build_last_ssh_snapshot()
        assert frame["topic"] == "last_ssh"
        entry = frame["payload"]["c1"]
        assert entry["last_ssh_connect_time"] is None
        assert entry["updated_at"]
    finally:
        with cache._lock:
            cache._cache.pop("c1", None)


def test_event_positive_trace_and_unknown_diagnostic(monkeypatch, caplog):
    cache = ContainerStatusCache()
    container = FakeRuntimeContainer("c1", status="running")
    _install(monkeypatch, [container])
    records = []
    monkeypatch.setattr(extensions.event_log, "record", lambda *args, **kwargs: records.append((args, kwargs)))

    cache._apply_event({"Action": "start", "Actor": {"Attributes": {"name": "c1"}}})
    assert records
    assert records[0][0][0] == "c1"
    assert records[0][0][1] == "start"
    assert container.reload_calls >= 1
    assert cache.get_state("c1")["status"] == "starting"

    before = cache.get_state("c1")
    with caplog.at_level(logging.WARNING, logger="FuxiYu_NodeKernel.docker_operates.status_cache"):
        cache._apply_event({"Action": "future_action", "Actor": {"Attributes": {"name": "c1"}}})
    assert len(records) == 1
    assert cache.get_state("c1")["status"] == before["status"]
    assert cache.take_deleted() == []
    assert cache.take_delete_candidates() == []
    assert any(
        "unrecognized docker event" in record.message
        and "future_action" in record.message
        and "c1" in record.message
        for record in caplog.records
    )


def test_event_inspect_failure_keeps_last_known_with_diagnostic(monkeypatch, caplog):
    cache = ContainerStatusCache()
    container = FakeRuntimeContainer("c1", status="running")
    _install(monkeypatch, [container])
    _seed(cache, "c1", container, mark_ready=True)

    def _boom():
        raise RuntimeError("inspect down")

    container.reload = _boom
    with caplog.at_level(logging.WARNING, logger="FuxiYu_NodeKernel.docker_operates.status_cache"):
        cache._apply_event({"Action": "pause", "Actor": {"Attributes": {"name": "c1"}}})

    assert cache.get_state("c1")["status"] == "online"
    assert any(
        "event fresh inspect failed" in record.message
        and "c1" in record.message
        and "inspect down" in record.message
        for record in caplog.records
    )


def test_late_state_event_does_not_rollback_online(monkeypatch):
    cache = ContainerStatusCache()
    container = FakeRuntimeContainer("c1", status="running")
    _install(monkeypatch, [container])
    monkeypatch.setattr(extensions, "status_cache", cache)
    _seed(cache, "c1", container, mark_ready=True)

    ref = cache.accept_action("c1", "unpause", "unpausing")
    result = execute_pause_action("c1", "unpause", {**ref, "name": "c1"})
    assert result.phase == "idempotent_confirmed"
    assert _finish(cache, "c1", ref, result.phase, result.error_reason)
    assert cache.get_state("c1")["status"] == "online"

    cache._apply_event({"Action": "pause", "Actor": {"Attributes": {"name": "c1"}}})
    state = cache.get_state("c1")
    assert state["status"] == "online"
    assert state["last_action"]["ref"] == ref

    container.set_status("paused")
    cache._apply_event({"Action": "pause", "Actor": {"Attributes": {"name": "c1"}}})
    assert cache.get_state("c1")["status"] == "paused"


def test_unpause_docker_error_uses_fresh_inspect(monkeypatch):
    cache = ContainerStatusCache()
    monkeypatch.setattr(extensions, "status_cache", cache)
    container = FakeRuntimeContainer("c1", status="paused")
    _install(monkeypatch, [container])
    _seed(cache, "c1", container, mark_ready=True)
    container.raise_on_unpause = docker.errors.APIError("permission denied")

    ref = cache.accept_action("c1", "unpause", "unpausing")
    result = execute_pause_action("c1", "unpause", {**ref, "name": "c1"})
    assert result.phase == "failed"
    assert result.error_reason == "docker_api_error"
    assert _finish(cache, "c1", ref, result.phase, result.error_reason)
    state = cache.get_state("c1")
    assert state["status"] == "paused"
    assert state["last_action"]["phase"] == "failed"
    assert container.unpause_calls == 1

    cache2 = ContainerStatusCache()
    monkeypatch.setattr(extensions, "status_cache", cache2)
    container2 = FakeRuntimeContainer("c1", status="paused")
    _install(monkeypatch, [container2])
    _seed(cache2, "c1", container2, mark_ready=True)
    calls = {"n": 0}

    def _flaky_reload():
        calls["n"] += 1
        if calls["n"] >= 2:
            raise RuntimeError("post inspect down")

    container2.reload = _flaky_reload
    container2.raise_on_unpause = docker.errors.APIError("daemon timeout")
    ref2 = cache2.accept_action("c1", "unpause", "unpausing")
    result2 = execute_pause_action("c1", "unpause", {**ref2, "name": "c1"})
    assert result2.phase == "unconfirmed"
    assert result2.error_reason == "docker_api_error"
    assert _finish(cache2, "c1", ref2, result2.phase, result2.error_reason)
    # unconfirmed 不是完成证明；运行态保留 unknown，受理过渡在 TTL 内仍遮挡读面，
    # TTL 到期后读面显示 unknown，而不是成功或永久 failed。
    assert cache2.get("c1")["status"] == "unknown"
    assert cache2.get_state("c1")["status"] == "unpausing"
    record = cache2._meta_for("c1")["current_action"]
    record.accepted_at = record.accepted_at - datetime.timedelta(seconds=record.ttl + 1)
    assert cache2.get_state("c1")["status"] == "unknown"


def test_repeated_pause_on_paused_is_idempotent(monkeypatch):
    cache = ContainerStatusCache()
    monkeypatch.setattr(extensions, "status_cache", cache)
    container = FakeRuntimeContainer("c1", status="paused")
    _install(monkeypatch, [container])
    _seed(cache, "c1", container, mark_ready=True)

    ref = cache.accept_action("c1", "pause", "pausing")
    result = execute_pause_action("c1", "pause", {**ref, "name": "c1"})
    assert result.phase == "idempotent_confirmed"
    assert _finish(cache, "c1", ref, result.phase, result.error_reason)
    state = cache.get_state("c1")
    assert state["status"] == "paused"
    assert state["last_action"]["phase"] == "idempotent_confirmed"
    assert container.pause_calls == 0


def test_repeated_unpause_without_ready_keeps_ready_check(monkeypatch):
    cache = ContainerStatusCache()
    monkeypatch.setattr(extensions, "status_cache", cache)
    container = FakeRuntimeContainer("c1", status="running")
    _install(monkeypatch, [container])
    _seed(cache, "c1", container)
    assert cache.get_state("c1")["status"] == "starting"
    assert cache.get_state("c1")["ready_check"] is True

    ref = cache.accept_action("c1", "unpause", "unpausing")
    result = execute_pause_action("c1", "unpause", {**ref, "name": "c1"})
    assert result.phase == "idempotent_confirmed"
    assert _finish(cache, "c1", ref, result.phase, result.error_reason)
    state = cache.get_state("c1")
    assert state["status"] == "starting"
    assert state["ready_check"] is True
    assert state["last_action"]["phase"] == "idempotent_confirmed"
    assert container.unpause_calls == 0


def test_hard_block_survives_action_ttl(monkeypatch):
    cache = ContainerStatusCache()
    monkeypatch.setattr(extensions, "status_cache", cache)
    container = FakeRuntimeContainer("c1", status="running")
    _seed(cache, "c1", container, mark_ready=True)

    cache.accept_action("c1", "pause", "pausing")
    assert cache.set_hard_block("c1", "sshd_not_installed", "missing")
    record = cache._meta_for("c1")["current_action"]
    record.accepted_at = record.accepted_at - datetime.timedelta(seconds=record.ttl + 1)
    assert record.expires_at < time.time()

    state = cache.get_state("c1")
    assert state["status"] == "failed"
    assert state["failed_reason"] == "sshd_not_installed"
    entry = cache.get("c1")
    assert entry is not None
    assert entry["hard_block"] is True


def test_sshd_not_installed_probe_sets_hard_block(monkeypatch):
    cache = ContainerStatusCache()
    container = FakeRuntimeContainer("c1", status="running", exec_exit_code=127)
    _install(monkeypatch, [container])
    cache.mark_ready_check("c1")
    cache._probe_ready_checks_once()

    state = cache.get_state("c1")
    assert state["status"] == "failed"
    assert state["failed_reason"] == "sshd_not_installed"
    entry = cache.get("c1")
    assert entry is not None
    assert entry["hard_block"] is True
    assert "ready_identity" not in entry


def test_exited_is_offline_without_hard_block():
    cache = ContainerStatusCache()
    container = FakeRuntimeContainer("c1", status="exited")
    _seed(cache, "c1", container)
    assert cache.get_state("c1")["status"] == "offline"
    entry = cache.get("c1")
    assert entry is not None
    assert entry.get("hard_block") is not True

    ref = cache.accept_action("c1", "pause", "pausing")
    assert _finish(cache, "c1", ref, "failed", "docker_api_error")
    state = cache.get_state("c1")
    assert state["status"] == "offline"
    assert state["last_action"]["phase"] == "failed"
    assert cache.get("c1").get("hard_block") is not True


def test_dead_hard_block_survives_event_and_stale_observation(monkeypatch):
    cache = ContainerStatusCache()
    container = FakeRuntimeContainer("c1", status="dead")
    _install(monkeypatch, [container])
    monkeypatch.setattr(extensions.event_log, "record", lambda *args, **kwargs: None)
    _seed(cache, "c1", container)
    assert cache.get_state("c1")["status"] == "failed"
    assert cache.get("c1")["hard_block"] is True

    stale = cache.issue_observation("c1", "stale-before-event")
    cache._apply_event({"Action": "die", "Actor": {"Attributes": {"name": "c1"}}})
    assert cache.get_state("c1")["status"] == "failed"
    assert cache.get("c1")["hard_block"] is True
    assert cache.publish_observed("c1", stale, fact_from_container(container)) is False
    assert cache.get_state("c1")["status"] == "failed"
    assert cache.get("c1")["hard_block"] is True
    assert cache.take_deleted() == []


def test_hard_block_cleared_by_recreated_object(monkeypatch):
    for reason in ("sshd_not_installed", "created_half_built", "docker_dead"):
        cache = ContainerStatusCache()
        old = FakeRuntimeContainer("c1", status="running", docker_id="A")
        _install(monkeypatch, [old])
        _seed(cache, "c1", old, mark_ready=True)
        old_ref = cache.accept_action("c1", "start", "starting")
        assert cache.set_hard_block("c1", reason, "test")
        stale = cache.issue_observation("c1", "stale-before-recreate")

        new = FakeRuntimeContainer("c1", status="running", docker_id="B")
        ticket = cache.issue_observation("c1", "reconcile")
        assert cache.publish_observed("c1", ticket, fact_from_container(new)) is True
        state = cache.get_state("c1")
        assert state["status"] == "starting"
        assert state["ready_check"] is True
        entry = cache.get("c1")
        assert entry is not None
        assert entry["docker_id"] == "B"
        assert entry.get("hard_block") is not True
        assert cache.publish_observed(
            "c1",
            stale,
            fact_from_container(FakeRuntimeContainer("c1", status="running", docker_id="C")),
        ) is False
        assert cache.finish_action_ref({**old_ref, "name": "c1"}, "confirmed") is False


def test_list_failure_keeps_last_known_and_reports_collect_error(monkeypatch):
    cache = ContainerStatusCache()
    container = FakeRuntimeContainer("c1", status="running")
    client = _install(monkeypatch, [container])
    _seed(cache, "c1", container, mark_ready=True)

    def _boom(*args, **kwargs):
        raise RuntimeError("daemon down")

    client.containers.list = _boom
    cache._reconcile_once()
    assert cache.get_collect_error() == "collect_failed"
    assert cache.get_state("c1")["status"] == "online"
    assert cache.take_deleted() == []


def test_unknown_recovers_on_next_successful_observe(monkeypatch):
    cache = ContainerStatusCache()
    container = FakeRuntimeContainer("c1", status="running")
    client = _install(monkeypatch, [container])
    _seed(cache, "c1", container, mark_ready=True)
    original_get = client.containers.get

    def _boom(name):
        raise RuntimeError("inspect failed")

    client.containers.get = _boom
    cache._reconcile_once()
    state = cache.get_state("c1")
    assert state["status"] == "unknown"
    assert state["status_source"] == "collect_error"
    assert state["last_known_status"] == "online"

    client.containers.get = original_get
    cache._reconcile_once()
    state = cache.get_state("c1")
    assert state["status"] == "online"
    assert state.get("status_source") is None
    assert state.get("unknown_since") is None


def test_restart_does_not_revive_old_failed_pending(monkeypatch):
    old = ContainerStatusCache()
    old_container = FakeRuntimeContainer("c1", status="running")
    _seed(old, "c1", old_container, mark_ready=True)
    old_ref = old.accept_action("c1", "unpause", "unpausing")
    assert _finish(old, "c1", old_ref, "failed", "unpause_failed")

    new = ContainerStatusCache()
    container = FakeRuntimeContainer("c1", status="running")
    _install(monkeypatch, [container])
    new._reconcile_once()
    state = new.get_state("c1")
    assert state["status"] == "starting"
    assert state["ready_check"] is True
    assert state.get("last_action") is None
    assert new.finish_action_ref({**old_ref, "name": "c1"}, "confirmed") is False


def test_identity_change_invalidates_old_delete_candidate():
    cache = ContainerStatusCache()
    old = FakeRuntimeContainer("c1", status="running", docker_id="A")
    _seed(cache, "c1", old, mark_ready=True)
    generation = cache._meta_for("c1")["generation"]
    cache._deleted = [{"name": "c1", "generation": generation}]

    new = FakeRuntimeContainer("c1", status="running", docker_id="B")
    ticket = cache.issue_observation("c1", "reconcile")
    assert cache.publish_observed("c1", ticket, fact_from_container(new)) is True
    assert cache.take_delete_candidates() == []
    assert cache._meta_for("c1")["generation"] == generation + 1
    assert cache.get("c1")["docker_id"] == "B"


def test_create_pending_identity_deferral_is_diagnosed(monkeypatch, caplog):
    cache = ContainerStatusCache()
    ref = cache.accept_action("c1", "create", "creating", create=True)
    bind = FakeRuntimeContainer("c1", status="running", docker_id="B")
    bind_ticket = cache.issue_observation(
        "c1",
        "create",
        action_seq=ref["seq"],
        from_create_confirmation=True,
    )
    assert cache.publish_observed("c1", bind_ticket, fact_from_container(bind)) is True

    other = FakeRuntimeContainer("c1", status="running", docker_id="C")
    other_ticket = cache.issue_observation("c1", "reconcile", action_seq=ref["seq"])
    with caplog.at_level(logging.INFO, logger="FuxiYu_NodeKernel.docker_operates.status_cache"):
        assert cache.publish_observed("c1", other_ticket, fact_from_container(other)) is False

    assert cache.get("c1")["docker_id"] == "B"
    assert cache._meta_for("c1")["create_pending"] is True
    assert any(
        "identity_change_deferred" in record.message
        and "c1" in record.message
        and "B" in record.message
        and "C" in record.message
        for record in caplog.records
    )


def test_new_generation_rejects_old_ref():
    cache = ContainerStatusCache()
    old = FakeRuntimeContainer("c1", status="running", docker_id="A")
    _seed(cache, "c1", old, mark_ready=True)
    old_ref = cache.accept_action("c1", "start", "starting")

    new = FakeRuntimeContainer("c1", status="running", docker_id="B")
    ticket = cache.issue_observation("c1", "reconcile")
    assert cache.publish_observed("c1", ticket, fact_from_container(new)) is True
    assert cache.action_generation_valid({**old_ref, "name": "c1"}) is False
    assert cache.finish_action_ref({**old_ref, "name": "c1"}, "confirmed") is False

    new_ref = cache.accept_action("c1", "start", "starting")
    assert new_ref["generation"] == cache._meta_for("c1")["generation"]
    assert new_ref["seq"] > 0
    assert cache.action_generation_valid({**old_ref, "name": "c1"}) is False


def test_action_records_are_bounded():
    cache = ContainerStatusCache()
    latest = None
    for _ in range(40):
        latest = cache.accept_action("c1", "pause", "pausing")

    meta = cache._meta_for("c1")
    records = list(meta["actions"].values())
    assert len(records) <= 32
    assert len(records) == 32
    assert meta["last_action"].ref == latest
    assert sum(1 for record in records if not record.terminal) == 1
    assert records[-1].ref == latest
