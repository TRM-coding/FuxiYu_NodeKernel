"""可选真实 Docker 集成（默认 pytest.ini 排除，`pytest -m docker` 开启）。

本机没有 Docker daemon 时必须明确 skip，不能伪造通过；测试只使用本地 daemon，
不 SSH、不访问生产主机。
"""
import docker
import pytest

from FuxiYu_NodeKernel import extensions
from FuxiYu_NodeKernel.docker_operates.docker_fact import fact_from_container
from FuxiYu_NodeKernel.docker_operates.status_cache import ContainerStatusCache
from FuxiYu_NodeKernel.services import container_service

pytestmark = pytest.mark.docker


def _client_or_skip():
    try:
        client = docker.from_env()
        client.ping()
        return client
    except Exception as e:
        pytest.skip(f"local Docker daemon unavailable: {e}")


def _run_sleeper(client, name: str):
    try:
        old = client.containers.get(name)
        old.remove(force=True)
    except docker.errors.NotFound:
        pass
    try:
        return client.containers.run(
            "alpine:3.20",
            name=name,
            command=["sleep", "120"],
            detach=True,
            remove=False,
        )
    except Exception as e:
        pytest.skip(f"local Docker test image unavailable: {e}")


def test_real_unpause_running_container_is_idempotent(monkeypatch):
    client = _client_or_skip()
    name = "pytest_node_unpause_idempotent"
    container = _run_sleeper(client, name)
    try:
        container.reload()
        cache = ContainerStatusCache()
        monkeypatch.setattr(extensions, "status_cache", cache)
        monkeypatch.setattr(extensions, "docker_client", client)
        ticket = cache.issue_observation(name, "docker-integration")
        cache.publish_observed(name, ticket, fact_from_container(container), mark_ready=True)

        ref = cache.accept_action(name, "unpause", "unpausing")
        result = container_service.execute_pause_action(name, "unpause", {**ref, "name": name})
        assert result.phase == "idempotent_confirmed"
        assert cache.get_state(name)["status"] == "online"
        container.reload()
        assert container.status == "running"
    finally:
        try:
            container.remove(force=True)
        except Exception:
            pass


def test_real_offline_container_unpause_does_not_report_success(monkeypatch):
    client = _client_or_skip()
    name = "pytest_node_unpause_offline"
    container = _run_sleeper(client, name)
    try:
        container.stop(timeout=5)
        container.reload()
        cache = ContainerStatusCache()
        monkeypatch.setattr(extensions, "status_cache", cache)
        monkeypatch.setattr(extensions, "docker_client", client)
        ref = cache.accept_action(name, "unpause", "unpausing")
        result = container_service.execute_pause_action(name, "unpause", {**ref, "name": name})
        assert result.phase == "failed"
        assert result.error_reason == "not_running"
        assert cache.get_state(name)["status"] == "offline"
    finally:
        try:
            container.remove(force=True)
        except Exception:
            pass
