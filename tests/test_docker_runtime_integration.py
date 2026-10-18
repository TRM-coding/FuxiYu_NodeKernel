"""可选真实 Docker 集成（默认 pytest.ini 排除，`pytest -m docker` 开启）。

边界：

- 只使用本机 Docker daemon；不 SSH、不访问生产主机。
- 每个用例生成唯一名称和本次运行 label，只清理本次 ``containers.run`` 返回的
  Docker ID；绝不为复用名称而删除已存在的同名容器。
- 只有 daemon 不可用或本地测试镜像确实缺失时才 skip；镜像/环境错误与实现行为
  失败分开记录，行为断言失败 MUST NOT 被 skip 吞掉。
"""
from __future__ import annotations

import contextlib
import json
import os
import threading
import uuid

import docker
import pytest

from FuxiYu_NodeKernel import extensions
from FuxiYu_NodeKernel.docker_operates import status_cache as status_cache_module
from FuxiYu_NodeKernel.docker_operates.docker_fact import fact_from_container
from FuxiYu_NodeKernel.docker_operates.status_cache import ContainerStatusCache
from FuxiYu_NodeKernel.network import wss
from FuxiYu_NodeKernel.services import container_service

pytestmark = pytest.mark.docker

_LABEL_KEY = "fuxi.node.test"
_LABEL_VALUE = "runtime-integration"
_RUN_LABEL = "fuxi.node.test.run"
_IMAGE_CACHE: str | None = None
# 本机 Docker Hub 可能不可达；优先使用已存在的本地镜像。真实环境可用
# NODE_TEST_IMAGE 指定镜像；仍不存在时才尝试 pull。
_IMAGE_CANDIDATES = (
    "alpine:3.20",
    "alpine:latest",
    "swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/library/alpine:latest",
    "busybox:latest",
    "eclipse-temurin:21-jre-alpine",
)


def _client_or_skip():
    """daemon 不可用是环境缺口，明确 skip；不使用 remote context。"""
    try:
        client = docker.from_env()
        client.ping()
        return client
    except Exception as e:
        pytest.skip(f"local Docker daemon unavailable: {e}")


def _resolve_test_image(client) -> str:
    global _IMAGE_CACHE
    if _IMAGE_CACHE:
        return _IMAGE_CACHE

    candidates = []
    configured = os.getenv("NODE_TEST_IMAGE")
    if configured:
        candidates.append(configured)
    candidates.extend(_IMAGE_CANDIDATES)

    errors: list[str] = []
    for tag in candidates:
        try:
            client.images.get(tag)
        except docker.errors.ImageNotFound:
            continue
        except docker.errors.APIError as e:
            errors.append(f"{tag}: {e}")
            continue
        _IMAGE_CACHE = tag
        return tag

    pull_tag = configured or "alpine:3.20"
    try:
        client.images.pull(pull_tag)
    except Exception as e:
        pytest.skip(
            "local Docker test image unavailable (set NODE_TEST_IMAGE to an already-local image): "
            f"{e}; local probe errors={errors}"
        )
    _IMAGE_CACHE = pull_tag
    return pull_tag


def _unique_name(prefix: str) -> str:
    return f"pytest-node-{prefix}-{uuid.uuid4().hex[:12]}"


def _run_sleeper(client, prefix: str):
    """创建本次用例独占的容器；返回 (container, run_id)。

    不按名称删除任何已有容器。名称冲突时让 Docker 报错，而不是先删同名对象。
    """
    image = _resolve_test_image(client)
    run_id = uuid.uuid4().hex
    name = _unique_name(prefix)
    labels = {_LABEL_KEY: _LABEL_VALUE, _RUN_LABEL: run_id}
    try:
        container = client.containers.run(
            image,
            name=name,
            command=["sleep", "120"],
            detach=True,
            remove=False,
            labels=labels,
        )
    except docker.errors.ImageNotFound as e:
        pytest.skip(f"local Docker test image disappeared: {e}")
    except docker.errors.APIError as e:
        text = str(e).lower()
        if "no such image" in text or "pull access denied" in text or "image not found" in text:
            pytest.skip(f"local Docker test image unavailable: {e}")
        raise
    container.reload()
    if container.status != "running":
        logs = ""
        try:
            logs = container.logs().decode("utf-8", errors="replace")[-1000:]
        except Exception:
            pass
        pytest.fail(f"test container did not stay running: status={container.status} logs={logs}")
    return container, run_id


def _remove_own_container(client, container, run_id: str) -> None:
    """只清理本次创建、label 匹配的 Docker ID；找不到即已清理。"""
    container_id = getattr(container, "id", None)
    if not container_id:
        return
    try:
        current = client.containers.get(container_id)
    except docker.errors.NotFound:
        return
    labels = ((getattr(current, "attrs", None) or {}).get("Config") or {}).get("Labels") or {}
    if labels.get(_LABEL_KEY) != _LABEL_VALUE or labels.get(_RUN_LABEL) != run_id:
        print(f"skip cleanup: container {container_id} does not carry this test run label")
        return
    try:
        current.remove(force=True)
    except docker.errors.NotFound:
        return


@contextlib.contextmanager
def _sleeper(client, prefix: str):
    container, run_id = _run_sleeper(client, prefix)
    try:
        yield container
    finally:
        _remove_own_container(client, container, run_id)


def _seed_online(cache: ContainerStatusCache, container) -> dict:
    container.reload()
    name = container.name
    ticket = cache.issue_observation(name, "docker-integration-seed")
    assert cache.publish_observed(
        name,
        ticket,
        fact_from_container(container),
        mark_ready=True,
    )
    state = cache.get_state(name)
    assert state["status"] == "online"
    return cache.get(name) or {}


def _finish(cache: ContainerStatusCache, name: str, ref: dict, result) -> None:
    assert cache.finish_action_ref(
        {**ref, "name": name},
        result.phase,
        result.error_reason,
    )


def _run_pause_action(cache: ContainerStatusCache, name: str, action: str):
    transition = "pausing" if action == "pause" else "unpausing"
    ref = cache.accept_action(name, action, transition)
    result = container_service.execute_pause_action(name, action, {**ref, "name": name})
    _finish(cache, name, ref, result)
    return ref, result


def test_real_unpause_running_container_is_idempotent(monkeypatch):
    client = _client_or_skip()
    with _sleeper(client, "unpause-idempotent") as container:
        name = container.name
        cache = ContainerStatusCache()
        monkeypatch.setattr(extensions, "status_cache", cache)
        monkeypatch.setattr(extensions, "docker_client", client)
        seeded = _seed_online(cache, container)
        ready_before = dict(seeded["ready_identity"])

        ref, result = _run_pause_action(cache, name, "unpause")

        assert result.phase == "idempotent_confirmed"
        state = cache.get_state(name)
        assert state["status"] == "online"
        assert state["last_action"] == {
            "ref": ref,
            "action": "unpause",
            "phase": "idempotent_confirmed",
            "error_reason": None,
        }
        assert cache.get(name)["ready_identity"] == ready_before
        assert "unpause_failed" not in str(state)
        container.reload()
        assert container.status == "running"

        frame = wss.build_status_snapshot()
        entry = frame["payload"][name]
        assert entry["status"] == "online"
        assert entry["last_action"]["phase"] == "idempotent_confirmed"
        assert json.loads(json.dumps(frame))["payload"][name]["last_action"]["ref"] == ref


def test_real_offline_container_unpause_does_not_report_success(monkeypatch):
    client = _client_or_skip()
    with _sleeper(client, "unpause-offline") as container:
        name = container.name
        container.stop(timeout=10)
        container.reload()
        assert container.status == "exited"

        cache = ContainerStatusCache()
        monkeypatch.setattr(extensions, "status_cache", cache)
        monkeypatch.setattr(extensions, "docker_client", client)
        ticket = cache.issue_observation(name, "docker-integration-seed")
        assert cache.publish_observed(name, ticket, fact_from_container(container))
        assert cache.get_state(name)["status"] == "offline"

        ref, result = _run_pause_action(cache, name, "unpause")

        assert result.phase == "failed"
        assert result.error_reason == "not_running"
        state = cache.get_state(name)
        assert state["status"] == "offline"
        assert state["last_action"]["ref"] == ref
        assert state["last_action"]["phase"] == "failed"
        assert "unpause_failed" not in str(state)


def test_real_pause_preserves_ready_and_external_restart_stales_it(monkeypatch):
    client = _client_or_skip()
    with _sleeper(client, "restart-regate") as container:
        name = container.name
        cache = ContainerStatusCache()
        monkeypatch.setattr(extensions, "status_cache", cache)
        monkeypatch.setattr(extensions, "docker_client", client)
        seeded = _seed_online(cache, container)
        ready_before = dict(seeded["ready_identity"])
        assert ready_before.get("started_at")

        _, pause_result = _run_pause_action(cache, name, "pause")
        assert pause_result.phase == "confirmed"
        paused_state = cache.get_state(name)
        assert paused_state["status"] == "paused"
        assert cache.get(name)["ready_identity"] == ready_before

        _, unpause_result = _run_pause_action(cache, name, "unpause")
        assert unpause_result.phase == "confirmed"
        assert cache.get_state(name)["status"] == "online"
        assert cache.get(name)["ready_identity"] == ready_before

        # 同 Docker ID 的外部重启：ID 不变，StartedAt 必须变化。
        container.restart(timeout=10)
        container.reload()
        assert container.status == "running"
        fresh = fact_from_container(container)
        assert fresh.started_at
        assert fresh.started_at != ready_before["started_at"]
        ticket = cache.issue_observation(name, "external-restart")
        assert cache.publish_observed(name, ticket, fresh)

        state = cache.get_state(name)
        assert state["status"] == "starting"
        assert state["ready_check"] is True
        assert cache.get(name)["ready_verified"] is False
        assert "ready_identity" not in cache.get(name)


def test_real_slow_stats_does_not_publish_stale_list_state(monkeypatch):
    """list 取得 paused 旧对象；stats 期间真实容器已 running，最终按名解析 wins。"""
    client = _client_or_skip()
    with _sleeper(client, "slow-stats") as container:
        name = container.name
        cache = ContainerStatusCache()
        monkeypatch.setattr(extensions, "status_cache", cache)
        monkeypatch.setattr(extensions, "docker_client", client)
        _seed_online(cache, container)

        # 先让 Docker 真实进入 paused；缓存仍是 running/online，模拟旧列表对象。
        container.pause()
        container.reload()
        assert container.status == "paused"

        entered = threading.Event()
        release = threading.Event()
        original_metrics = status_cache_module._container_runtime_metrics

        def _blocked_metrics(target, gpu_runtime_by_index=None):
            if target.name == name and not entered.is_set():
                entered.set()
                if not release.wait(10):
                    raise TimeoutError("slow stats barrier timeout")
            return original_metrics(target, gpu_runtime_by_index)

        monkeypatch.setattr(status_cache_module, "_container_runtime_metrics", _blocked_metrics)
        worker = threading.Thread(target=cache._reconcile_once, name="real-slow-reconcile")
        worker.start()
        try:
            assert entered.wait(10), "reconcile did not reach the controlled stats barrier"
            # stats 阻塞期间真实容器恢复 running；旧 list 对象仍然报告 paused。
            container.unpause()
            container.reload()
            assert container.status == "running"
        finally:
            release.set()
            worker.join(30)
        assert not worker.is_alive(), "reconcile thread did not finish"

        state = cache.get_state(name)
        assert state["status"] == "online"
        assert cache.get(name)["status"] == "online"
        assert state["status"] != "paused"


@pytest.mark.skip(
    reason=(
        "不能在不破坏本机 Docker storage/宿主挂载的前提下安全制造真实 dead 状态；"
        "dead 的运行态/动作映射由 tests/test_runtime_guard.py 中 "
        "test_pause_unpause_offline_dead_never_report_success 覆盖，"
        "这里明确跳过而不是伪造真实 Docker 通过"
    )
)
def test_real_dead_container_unpause_does_not_report_success():
    """保留显式 skip 位：真实 dead 仍需独立、可安全清理的隔离宿主 fixture。"""

    pytest.fail("explicit skip marker was removed; provide a safe real dead fixture before enabling")
