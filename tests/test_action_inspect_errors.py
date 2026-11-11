"""动作 pre/post inspect 的错误分类与不确定性回归。

覆盖 pause/start/stop/restart 的 pre-inspect NotFound、APIError、连接错误和
timeout；只有明确 NotFound 才是 not_found。动作结果与运行态分离，inspect
不可判定不会被写成永久 failed。
"""
from __future__ import annotations

import docker
import pytest

from FuxiYu_NodeKernel import extensions
from FuxiYu_NodeKernel.constant import ContainerStatus
from FuxiYu_NodeKernel.docker_operates.docker_fact import fact_from_container
from FuxiYu_NodeKernel.docker_operates.status_cache import ContainerStatusCache
from FuxiYu_NodeKernel.services.container_service import execute_container_action

from .runtime_fakes import FakeRuntimeContainer, install_runtime, not_found

ACTIONS = [
    ("pause", "pausing"),
    ("start", "starting"),
    ("stop", "stopping"),
    ("restart", "restarting"),
]

ERROR_CASES = [
    ("not_found", "failed", "not_found"),
    ("api_error", "unconfirmed", "docker_api_error"),
    ("connection_error", "unconfirmed", "docker_api_error"),
    ("timeout", "unconfirmed", "timeout"),
]


def _seed_online(cache: ContainerStatusCache, name: str = "c1"):
    container = FakeRuntimeContainer(name, status="running")
    ticket = cache.issue_observation(name, "seed")
    assert cache.publish_observed(name, ticket, fact_from_container(container), mark_ready=True)
    return container


def _error(kind: str) -> Exception:
    if kind == "not_found":
        return not_found("c1")
    if kind == "api_error":
        return docker.errors.APIError("daemon api error")
    if kind == "connection_error":
        return docker.errors.DockerException("connection refused")
    return TimeoutError("inspect timed out")


@pytest.mark.parametrize(("kind", "expected_phase", "expected_reason"), ERROR_CASES)
@pytest.mark.parametrize(("action", "transition"), ACTIONS)
def test_pre_inspect_errors_are_classified_not_all_not_found(
    monkeypatch, kind, expected_phase, expected_reason, action, transition
):
    cache = ContainerStatusCache()
    monkeypatch.setattr(extensions, "status_cache", cache)
    _seed_online(cache)

    class _Containers:
        def get(self, name):
            raise _error(kind)

    class _Client:
        containers = _Containers()

    monkeypatch.setattr(extensions, "docker_client", _Client())
    ref = cache.accept_action("c1", action, transition)
    full_ref = {**ref, "name": "c1"}

    result = execute_container_action("c1", action, full_ref)

    assert result.phase == expected_phase
    assert result.error_reason == expected_reason
    if kind != "not_found":
        assert result.detail is not None
    assert cache.finish_action_ref(full_ref, result.phase, result.error_reason)

    state = cache.get_state("c1")
    last = state["last_action"]
    assert last["ref"] == ref
    assert last["phase"] == expected_phase
    assert last["error_reason"] == expected_reason
    assert state["status"] != ContainerStatus.FAILED.value


def test_post_inspect_api_error_is_unconfirmed_not_not_found(monkeypatch):
    cache = ContainerStatusCache()
    monkeypatch.setattr(extensions, "status_cache", cache)
    container = _seed_online(cache)
    client = install_runtime(monkeypatch, [container])
    original_get = client.containers.get
    calls = {"n": 0}

    def _get(name):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise docker.errors.APIError("post inspect down")
        return original_get(name)

    client.containers.get = _get
    ref = cache.accept_action("c1", "pause", "pausing")
    full_ref = {**ref, "name": "c1"}

    result = execute_container_action("c1", "pause", full_ref)

    assert result.phase == "unconfirmed"
    assert result.error_reason == "docker_api_error"
    assert "post inspect down" in (result.detail or "")
    assert cache.finish_action_ref(full_ref, result.phase, result.error_reason)
    state = cache.get_state("c1")
    assert state["last_action"]["phase"] == "unconfirmed"
    assert state["last_action"]["error_reason"] == "docker_api_error"
    assert state["status"] != ContainerStatus.FAILED.value
