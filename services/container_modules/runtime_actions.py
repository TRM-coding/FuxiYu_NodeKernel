"""容器动作执行：新鲜 inspect 观察、结果分类与 pause/start/stop/restart 入口。

本模块只承接原 ``services.container_service`` 中的动作执行职责，不新增运行态、
动作相位或协议；票/代际的发布顺序与时机仍由现有 status cache 契约决定。
"""
import dataclasses
import logging

import docker

from ... import extensions
from ...docker_operates.docker_fact import DockerFact, fact_from_container
from ...utils import sanitizer as _sanitizer

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class ActionExecutionResult:
    """结构化动作结果；phase 不是运行态，失败不得写容器 failed。"""

    phase: str
    error_reason: str | None = None
    detail: str | None = None
    fact: DockerFact | None = None


@dataclasses.dataclass(frozen=True)
class ActionObservation:
    """一次动作 inspect 的结构化结果；异常只在本调用链内传递，不新增全局状态。"""

    fact: DockerFact | None
    container: object | None
    ticket: object | None
    error: Exception | None = None
    error_reason: str | None = None


def _inspect_error_reason(err: Exception) -> str:
    """区分明确不存在、超时与 Docker/连接/API 不可判定。"""

    if isinstance(err, docker.errors.NotFound):
        return "not_found"
    if _looks_like_timeout(err):
        return "timeout"
    return "docker_api_error"


def _inspect_failure_result(
    observation: ActionObservation,
    *,
    fact: DockerFact | None = None,
) -> ActionExecutionResult:
    """把 inspect 异常映射为动作结果；只有明确 NotFound 才是 not_found。"""

    reason = observation.error_reason or "inspect_failed"
    if reason == "not_found":
        return _fail("failed", "not_found", observation.error, fact)
    return _fail("unconfirmed", reason, observation.error, fact)


def _action_detail(err: Exception, *, limit: int = 300) -> str:
    text = str(err or "")
    return text[:limit]


def _is_not_paused_error(err: Exception) -> bool:
    return "is not paused" in str(err).lower()


def _looks_like_timeout(err: Exception) -> bool:
    name = type(err).__name__.lower()
    return "timeout" in name or "timed out" in str(err).lower()


def _action_client():
    if extensions.docker_client is None:
        extensions.init_docker()
    return extensions.docker_client


def _action_inspect(name: str) -> DockerFact:
    container = _action_client().containers.get(name)
    reload = getattr(container, "reload", None)
    if callable(reload):
        reload()
    return fact_from_container(container)


def _action_observe(name: str, source: str, ref: dict) -> ActionObservation:
    """动作读面观察：固定受理 ref 的 epoch/generation/seq 签票，再 inspect。

    返回结构化结果；container 是本次 inspect 捕获的对象，后续 Docker 副作用
    应作用于该对象。NotFound/API/连接/超时不在本函数里被抹平成 none。
    """
    cache = extensions.status_cache
    ticket = cache.issue_observation(
        name,
        source,
        generation=ref.get("generation"),
        action_seq=ref.get("seq"),
    )
    try:
        container = _action_client().containers.get(name)
        reload = getattr(container, "reload", None)
        if callable(reload):
            reload()
        fact = fact_from_container(container)
    except Exception as e:
        reason = _inspect_error_reason(e)
        runtime_reason = {
            "not_found": "not_found",
            "timeout": "inspect_timeout",
        }.get(reason, "inspect_failed")
        cache.publish_unknown(name, ticket, reason=runtime_reason)
        return ActionObservation(
            fact=None,
            container=None,
            ticket=ticket,
            error=e,
            error_reason=reason,
        )
    cache.publish_observed(name, ticket, fact)
    return ActionObservation(fact=fact, container=container, ticket=ticket)


def _action_publish(name: str, fact: DockerFact, source: str, ref: dict) -> bool:
    cache = extensions.status_cache
    ticket = cache.issue_observation(
        name,
        source,
        generation=ref.get("generation"),
        action_seq=ref.get("seq"),
    )
    return cache.publish_observed(name, ticket, fact)


def _fail(phase: str, reason: str | None, err: Exception | None = None, fact: DockerFact | None = None) -> ActionExecutionResult:
    return ActionExecutionResult(
        phase=phase,
        error_reason=reason,
        detail=_action_detail(err) if err is not None else None,
        fact=fact,
    )


def _post_call_result(
    name: str,
    ref: dict,
    pre: DockerFact,
    *,
    source: str,
    expect,
    fail_reason: str,
) -> ActionExecutionResult:
    """动作调用后的新鲜 inspect 确认；不可判定时 unconfirmed，绝不写永久 failed。"""
    observation = _action_observe(name, source, ref)
    if observation.error is not None:
        return _inspect_failure_result(observation, fact=pre)
    post = observation.fact
    if post is None:
        return _fail("unconfirmed", "action_unknown", None, pre)
    if expect(post):
        return ActionExecutionResult("confirmed", None, None, post)
    return _fail("failed", fail_reason, None, post)


def execute_pause_action(name: str, action: str, ref: dict) -> ActionExecutionResult:
    """pause/unpause 新鲜 inspect + 幂等表。"""
    if action not in ("pause", "unpause"):
        return _fail("failed", "invalid_action")
    try:
        _sanitizer.validate_username(name)
    except Exception as e:
        return _fail("failed", "invalid_container_name", e)
    if not extensions.status_cache.action_generation_valid(ref):
        return _fail("superseded", "generation_changed")

    observation = _action_observe(name, f"action:{action}:pre", ref)
    if observation.error is not None:
        return _inspect_failure_result(observation)
    before = observation.fact
    container = observation.container
    if before is None:
        return _fail("failed", "not_found")
    if before.dead:
        return _fail("failed", "docker_dead", None, before)
    if action == "pause":
        if before.paused:
            return ActionExecutionResult("idempotent_confirmed", None, None, before)
        if not before.running:
            return _fail("failed", "not_running", None, before)
    else:
        if before.running and not before.paused:
            return ActionExecutionResult("idempotent_confirmed", None, None, before)
        if not before.running:
            return _fail("failed", "not_running", None, before)

    if not extensions.status_cache.action_generation_valid(ref):
        return _fail("superseded", "generation_changed", None, before)
    try:
        if action == "pause":
            container.pause()
        else:
            container.unpause()
    except docker.errors.NotFound as e:
        return _fail("failed", "not_found", e, before)
    except Exception as e:
        # `is not paused`/重复动作：以新鲜实态为准，不以错误文本直接判定。
        observation = _action_observe(name, f"action:{action}:error_inspect", ref)
        if observation.error is not None:
            reason = "timeout" if _looks_like_timeout(e) else "docker_api_error"
            return _fail("unconfirmed", reason, e, before)
        after = observation.fact
        if after is not None:
            if action == "unpause" and after.running and not after.paused:
                return ActionExecutionResult("idempotent_confirmed", None, _action_detail(e), after)
            if action == "pause" and after.paused:
                return ActionExecutionResult("idempotent_confirmed", None, _action_detail(e), after)
            if not after.running:
                return _fail("failed", "not_running", e, after)
        reason = "timeout" if _looks_like_timeout(e) else "docker_api_error"
        return _fail("failed" if after is not None else "unconfirmed", reason, e, after)

    if action == "pause":
        return _post_call_result(name, ref, before, source="action:pause:post", expect=lambda f: f.paused, fail_reason="state_mismatch")
    return _post_call_result(
        name,
        ref,
        before,
        source="action:unpause:post",
        expect=lambda f: f.running and not f.paused,
        fail_reason="state_mismatch",
    )


def _start_sshd_best_effort(container, name: str) -> None:
    try:
        container.exec_run(["/usr/sbin/sshd"], user="root")
    except Exception as e:
        logger.debug("start_container sshd best-effort failed: name=%s err=%s", name, e)


def execute_start_action(name: str, ref: dict) -> ActionExecutionResult:
    try:
        _sanitizer.validate_username(name)
    except Exception as e:
        return _fail("failed", "invalid_container_name", e)
    if not extensions.status_cache.action_generation_valid(ref):
        return _fail("superseded", "generation_changed")
    observation = _action_observe(name, "action:start:pre", ref)
    if observation.error is not None:
        return _inspect_failure_result(observation)
    before = observation.fact
    container = observation.container
    if before is None:
        return _fail("failed", "not_found")
    if before.dead:
        return _fail("failed", "docker_dead", None, before)
    if before.status == "created":
        return _fail("failed", "created_half_built", None, before)
    if before.paused:
        return _fail("failed", "state_conflict", None, before)
    if before.running:
        runtime = extensions.status_cache.get(name) or {}
        ready = runtime.get("ready_verified") and (runtime.get("ready_identity") or {}) == {
            "docker_id": before.docker_id,
            "started_at": before.started_at,
        } and before.started_at is not None
        return ActionExecutionResult("idempotent_confirmed" if ready else "confirmed", None, None, before)

    if not extensions.status_cache.action_generation_valid(ref):
        return _fail("superseded", "generation_changed", None, before)
    try:
        container.start()
        _start_sshd_best_effort(container, name)
    except docker.errors.NotFound as e:
        return _fail("failed", "not_found", e, before)
    except Exception as e:
        observation = _action_observe(name, "action:start:error_inspect", ref)
        reason = "timeout" if _looks_like_timeout(e) else "docker_api_error"
        if observation.error is not None:
            return _fail("unconfirmed", reason, e, before)
        after = observation.fact
        return _fail("failed" if after is not None else "unconfirmed", reason, e, after)
    return _post_call_result(
        name,
        ref,
        before,
        source="action:start:post",
        expect=lambda f: f.running and not f.paused,
        fail_reason="state_mismatch",
    )


def execute_stop_action(name: str, ref: dict) -> ActionExecutionResult:
    try:
        _sanitizer.validate_username(name)
    except Exception as e:
        return _fail("failed", "invalid_container_name", e)
    if not extensions.status_cache.action_generation_valid(ref):
        return _fail("superseded", "generation_changed")
    observation = _action_observe(name, "action:stop:pre", ref)
    if observation.error is not None:
        return _inspect_failure_result(observation)
    before = observation.fact
    container = observation.container
    if before is None:
        return _fail("failed", "not_found")
    if before.dead:
        return _fail("failed", "docker_dead", None, before)
    if not before.running:
        return ActionExecutionResult("idempotent_confirmed", None, None, before)

    if not extensions.status_cache.action_generation_valid(ref):
        return _fail("superseded", "generation_changed", None, before)
    try:
        container.stop(timeout=10)
    except docker.errors.NotFound as e:
        return _fail("failed", "not_found", e, before)
    except Exception as e:
        observation = _action_observe(name, "action:stop:error_inspect", ref)
        reason = "timeout" if _looks_like_timeout(e) else "docker_api_error"
        if observation.error is not None:
            return _fail("unconfirmed", reason, e, before)
        after = observation.fact
        return _fail("failed" if after is not None else "unconfirmed", reason, e, after)
    return _post_call_result(
        name,
        ref,
        before,
        source="action:stop:post",
        expect=lambda f: not f.running,
        fail_reason="state_mismatch",
    )


def execute_restart_action(name: str, ref: dict) -> ActionExecutionResult:
    try:
        _sanitizer.validate_username(name)
    except Exception as e:
        return _fail("failed", "invalid_container_name", e)
    if not extensions.status_cache.action_generation_valid(ref):
        return _fail("superseded", "generation_changed")
    observation = _action_observe(name, "action:restart:pre", ref)
    if observation.error is not None:
        return _inspect_failure_result(observation)
    before = observation.fact
    container = observation.container
    if before is None:
        return _fail("failed", "not_found")
    if before.dead or before.status == "created":
        return _fail("failed", "docker_dead" if before.dead else "created_half_built", None, before)

    if not extensions.status_cache.action_generation_valid(ref):
        return _fail("superseded", "generation_changed", None, before)
    try:
        container.restart(timeout=10)
        _start_sshd_best_effort(container, name)
    except docker.errors.NotFound as e:
        return _fail("failed", "not_found", e, before)
    except Exception as e:
        observation = _action_observe(name, "action:restart:error_inspect", ref)
        reason = "timeout" if _looks_like_timeout(e) else "docker_api_error"
        if observation.error is not None:
            return _fail("unconfirmed", reason, e, before)
        after = observation.fact
        return _fail("failed" if after is not None else "unconfirmed", reason, e, after)
    return _post_call_result(
        name,
        ref,
        before,
        source="action:restart:post",
        expect=lambda f: f.running and not f.paused,
        fail_reason="state_mismatch",
    )


def execute_container_action(name: str, action: str, ref: dict) -> ActionExecutionResult:
    """六类动作之外不进入统一入口；create 由 API 后台构建流程自行执行。"""
    if action in ("pause", "unpause"):
        return execute_pause_action(name, action, ref)
    if action == "start":
        return execute_start_action(name, ref)
    if action == "stop":
        return execute_stop_action(name, ref)
    if action == "restart":
        return execute_restart_action(name, ref)
    return _fail("failed", "invalid_action")
