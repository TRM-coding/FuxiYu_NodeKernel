"""Docker 容器事实读取（Node 内部）。

只把一次 Docker inspect 已取得的字段整理成不可变事实对象；不访问网络、
不写缓存。运行态发布、路径核对和动作确认共用这个解析，避免各路径各自
解释 ``status``/``State``。
"""
from __future__ import annotations

import dataclasses
import datetime
from typing import Any, Mapping


@dataclasses.dataclass(frozen=True)
class DockerFact:
    """一次新鲜 Docker 观察的只读事实。"""

    docker_id: str | None
    status: str | None
    running: bool
    paused: bool
    restarting: bool
    dead: bool
    started_at: str | None = None
    pid: int | None = None
    oom_killed: bool = False
    exit_code: int | None = None
    error: str | None = None
    source: str = "inspect"
    read_ns: int | None = None
    attrs: Mapping[str, Any] | None = dataclasses.field(default=None, repr=False, compare=False)

    @property
    def identity(self) -> tuple[str | None, str | None]:
        return self.docker_id, self.started_at


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return False


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def fact_from_attrs(
    attrs: Mapping[str, Any] | None,
    *,
    docker_id: str | None = None,
    status: str | None = None,
    source: str = "inspect",
) -> DockerFact:
    """把 Docker inspect/列表对象 attrs 解析成事实。

    ``attrs`` 缺失或不完整时返回不可判定事实（status=None），调用方必须按
    unknown 处理，不能猜 online/offline。
    """
    state = (attrs or {}).get("State") or {}
    raw_status = str(status or state.get("Status") or (attrs or {}).get("status") or "").lower() or None
    if raw_status is None:
        return DockerFact(
            docker_id=docker_id,
            status=None,
            running=False,
            paused=False,
            restarting=False,
            dead=False,
            source=source,
            read_ns=_now_ns(),
            attrs=attrs,
        )
    paused = _as_bool(state.get("Paused")) or raw_status == "paused"
    restarting = _as_bool(state.get("Restarting")) or raw_status == "restarting"
    dead = _as_bool(state.get("Dead")) or raw_status == "dead"
    running = _as_bool(state.get("Running"))
    if not running and raw_status == "running":
        running = True
    if paused and not running:
        # docker 的 paused 容器 State.Running 通常为 true；若某个假/旧对象没有
        # 给出 Running，paused 仍应视为进程存在但被冻结。
        running = True
    return DockerFact(
        docker_id=docker_id or (attrs or {}).get("Id"),
        status=raw_status,
        running=running,
        paused=paused,
        restarting=restarting,
        dead=dead,
        started_at=(str(state.get("StartedAt")) if state.get("StartedAt") not in (None, "", "0001-01-01T00:00:00Z") else None),
        pid=_as_int(state.get("Pid")),
        oom_killed=_as_bool(state.get("OOMKilled")),
        exit_code=_as_int(state.get("ExitCode")),
        error=(str(state.get("Error")) if state.get("Error") else None),
        source=source,
        read_ns=_now_ns(),
        attrs=attrs,
    )


def fact_from_container(container, *, source: str = "inspect") -> DockerFact:
    """从 docker-py 容器对象解析事实（不主动 reload）。"""
    attrs = getattr(container, "attrs", None) or {}
    return fact_from_attrs(
        attrs,
        docker_id=getattr(container, "id", None),
        status=getattr(container, "status", None),
        source=source,
    )


def _now_ns() -> int:
    """仅用于诊断/测试日志，不参与发布资格判定。"""
    return int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1_000_000_000)
