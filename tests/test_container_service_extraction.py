"""container_service 职责抽取的结构回归。

只锁模块归属、依赖方向和稳定入口的对象同一性；动作算法与代理行为仍由既有
行为测试覆盖，不在这里复刻实现。
"""
from __future__ import annotations

import ast
from pathlib import Path

from FuxiYu_NodeKernel import extensions
from FuxiYu_NodeKernel.docker_operates import proxy_config
from FuxiYu_NodeKernel.docker_operates.docker_fact import fact_from_container
from FuxiYu_NodeKernel.docker_operates.status_cache import ContainerStatusCache
from FuxiYu_NodeKernel.services import container_service
from FuxiYu_NodeKernel.services.container_modules import runtime_actions

from .runtime_fakes import FakeRuntimeContainer, install_runtime

_MOVED_ACTION_NAMES = (
    "ActionExecutionResult",
    "ActionObservation",
    "execute_container_action",
    "execute_pause_action",
    "execute_start_action",
    "execute_stop_action",
    "execute_restart_action",
)

_MOVED_PROXY_NAMES = (
    "_clean_proxy_value",
    "_inject_build_proxy",
    "_runtime_proxy_env",
    "_runtime_proxy_setup_command",
)


def _imported_modules(module) -> list[str]:
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.append("." * node.level + (node.module or ""))
    return names


def test_service_action_entry_reexports_the_moved_implementation():
    for name in _MOVED_ACTION_NAMES:
        moved = getattr(runtime_actions, name)
        assert moved.__module__ == runtime_actions.__name__
        # 稳定入口必须是同一个对象，而不是另一份复制/包装实现。
        assert getattr(container_service, name) is moved

    assert (
        container_service.ActionExecutionResult
        is runtime_actions.ActionExecutionResult
    )


def test_proxy_helpers_live_in_docker_operates_proxy_config():
    for name in _MOVED_PROXY_NAMES:
        moved = getattr(proxy_config, name)
        assert moved.__module__ == proxy_config.__name__
        assert getattr(container_service, name) is moved
    assert proxy_config._PROXY_ENV_KEYS == ("http_proxy", "https_proxy")


def test_moved_modules_do_not_depend_on_container_service():
    for module in (proxy_config, runtime_actions):
        imports = _imported_modules(module)
        assert not any("container_service" in name for name in imports), (
            module.__name__,
            imports,
        )
    # docker_operates 只放代理读取/生成，不应反向依赖 services。
    assert not any("services" in name for name in _imported_modules(proxy_config))


def test_service_action_entry_runs_real_moved_action(monkeypatch):
    cache = ContainerStatusCache()
    monkeypatch.setattr(extensions, "status_cache", cache)
    container = FakeRuntimeContainer("c1", status="running")
    ticket = cache.issue_observation("c1", "seed")
    assert cache.publish_observed(
        "c1", ticket, fact_from_container(container), mark_ready=True
    )
    install_runtime(monkeypatch, [container])

    ref = cache.accept_action("c1", "pause", "pausing")
    result = container_service.execute_container_action(
        "c1", "pause", {**ref, "name": "c1"}
    )

    assert type(result) is runtime_actions.ActionExecutionResult
    assert result.phase == "confirmed"
    assert container.pause_calls == 1
