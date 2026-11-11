"""guard 6.3：固定种子随机交错的轨迹、不变量与有界最小化。

失败输出包含种子、完整操作轨迹和缩小后的最小复现；最小化本身也在此测试中
接受“故意失败”的验证，避免只写一个从不失败的空壳。
"""
from __future__ import annotations

import json
import random

from FuxiYu_NodeKernel.constant import ContainerStatus
from FuxiYu_NodeKernel.docker_operates.docker_fact import fact_from_container
from FuxiYu_NodeKernel.docker_operates.status_cache import (
    HARD_BLOCK_REASONS,
    ContainerStatusCache,
    VALID_PHASES,
)

from .runtime_fakes import FakeRuntimeContainer


NAMES = ["a", "b", "c"]
ACTIONS = {
    "start": "starting",
    "stop": "stopping",
    "restart": "restarting",
    "pause": "pausing",
    "unpause": "unpausing",
    "create": "creating",
}


def generate_ops(seed: int, count: int = 400):
    rng = random.Random(seed)
    ops = []
    active_count = 0
    for _ in range(count):
        name = rng.choice(NAMES)
        kind = rng.choice(["accept", "finish", "publish", "stale_publish", "metrics"])
        if kind == "accept":
            action = rng.choice(list(ACTIONS))
            ops.append(("accept", name, action, action == "create"))
            active_count += 1
        elif kind == "finish" and active_count:
            ops.append(("finish", name, rng.randrange(active_count), rng.choice(sorted(VALID_PHASES - {"timed_out"}))))
        elif kind == "publish":
            ops.append(("publish", name, rng.choice(["running", "paused", "exited", "dead", "created"])))
        elif kind == "stale_publish":
            ops.append(("stale_publish", name))
        else:
            ops.append(("metrics", name))
    return ops


def _containers_for_ops():
    return {
        name: FakeRuntimeContainer(
            name,
            status="running",
            docker_id=f"id-{name}",
            started_at="2026-10-17T19:00:00Z",
        )
        for name in NAMES
    }


def run_ops(ops):
    """执行操作并返回 (cache, trace, violations)。"""
    cache = ContainerStatusCache()
    containers = _containers_for_ops()
    active = []
    trace = []

    for index, op in enumerate(ops):
        kind = op[0]
        trace.append({"i": index, "op": op})
        try:
            if kind == "accept":
                _, name, action, create = op
                ref = cache.accept_action(name, action, ACTIONS[action], create=create)
                active.append((name, ref))
            elif kind == "finish":
                _, name, ref_index, phase = op
                if ref_index < len(active):
                    _, ref = active[ref_index]
                    cache.finish_action_ref({**ref, "name": name}, phase, "random")
            elif kind in {"publish", "stale_publish"}:
                _, name = op[0], op[1]
                container = containers[name]
                if kind == "publish":
                    container.set_status(op[2])
                ticket = cache.issue_observation(name, kind)
                if kind == "stale_publish":
                    newer = cache.issue_observation(name, "newer")
                    cache.publish_observed(name, newer, fact_from_container(container))
                    prior_applied = cache._meta_for(name)["last_applied_read_seq"]
                    cache.publish_observed(name, ticket, fact_from_container(container))
                    if cache._meta_for(name)["last_applied_read_seq"] != prior_applied:
                        trace.append({"i": index, "violation": "stale publish advanced applied seq"})
                else:
                    cache.publish_observed(name, ticket, fact_from_container(container))
            elif kind == "metrics":
                _, name = op
                ticket = cache.issue_observation(name, "metrics", metrics=True)
                cache.publish_metrics(name, ticket, {"cpu_usage_percent": 1.0})
            elif kind == "poison":
                # 只用于验证最小化器：制造一个无硬阻塞条件的 failed 运行态。
                _, name = op
                cache._cache[name] = {"status": ContainerStatus.FAILED.value, "updated_at": "2026-10-17T19:00:00"}
            else:
                trace.append({"i": index, "skip": "unknown op"})
        except Exception as exc:
            trace.append({"i": index, "exception": repr(exc)})

    violations = check_invariants(cache)
    return cache, trace, violations


def check_invariants(cache: ContainerStatusCache):
    violations = []
    for name in NAMES:
        meta = cache._meta_for(name)
        runtime = cache.get(name) or {}
        if meta["generation"] < 0 or meta["action_seq"] < 0 or meta["read_seq"] < 0:
            violations.append(f"{name}: negative sequence")
        if meta["last_applied_read_seq"] > meta["read_seq"]:
            violations.append(f"{name}: applied read_seq ahead of issued read_seq")
        if runtime.get("status") == ContainerStatus.FAILED.value:
            if runtime.get("hard_block") is not True or runtime.get("failed_reason") not in HARD_BLOCK_REASONS:
                violations.append(f"{name}: failed without allowed hard block")
        last = meta.get("last_action")
        if last is not None and last.phase not in VALID_PHASES:
            violations.append(f"{name}: invalid last phase {last.phase}")
        for record in (meta.get("actions") or {}).values():
            if record.phase not in VALID_PHASES:
                violations.append(f"{name}: invalid action phase {record.phase}")
    return violations


def bounded_minimize(ops, failing, max_passes: int = 3):
    """有界贪心删除：保持失败谓词成立的最小操作子序列。"""
    current = list(ops)
    passes = 0
    while passes < max_passes:
        changed = False
        index = 0
        while index < len(current):
            candidate = current[:index] + current[index + 1 :]
            if failing(candidate):
                current = candidate
                changed = True
            else:
                index += 1
        passes += 1
        if not changed:
            break
    return current


def test_fixed_seed_random_trace_holds_invariants():
    seed = 20261017
    ops = generate_ops(seed, 400)
    _cache, trace, violations = run_ops(ops)
    assert not violations, json.dumps(
        {"seed": seed, "violations": violations, "trace": trace, "ops": ops},
        ensure_ascii=False,
    )
    assert len(trace) == len(ops)


def test_failure_minimizer_produces_bounded_reproducer():
    seed = 7
    ops = generate_ops(seed, 30) + [("poison", "a")]
    _cache, trace, violations = run_ops(ops)
    assert violations, "poison must produce a detectable invariant failure"
    assert any(item.get("op") == ("poison", "a") for item in trace)

    def failing(candidate):
        return bool(run_ops(candidate)[2])

    reduced = bounded_minimize(ops, failing, max_passes=3)
    assert len(reduced) < len(ops)
    assert failing(reduced)
    assert any(op[0] == "poison" for op in reduced)
    # 缩小后的复现也可直接输出为 JSON（含失败路径本身可工作）。
    print(json.dumps({"seed": seed, "minimized_ops": reduced, "violations": run_ops(reduced)[2]}, ensure_ascii=False))
