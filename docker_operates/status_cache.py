# docker_operates/status_cache.py（Node 侧）
"""容器状态缓存：docker events 订阅（主）+ 定时对账（兜底）→ 内存缓存。

本模块同时维护三条相互独立但共用同一把锁的边界：

- RuntimeState：当前可解释的运行态（online/offline/paused/starting/failed/unknown）。
- ActionRecord：每次 create/start/stop/restart/pause/unpause 的受理与结果；
  动作失败只写动作诊断，绝不直接成为运行态 failed。
- Observation：读取 Docker **之前**签发的 ``{generation, action_seq, read_seq}``
  票据；发布时先校验票据，再允许比较 Docker ID 或写运行态。

本地 generation 只在当前 Node 进程/缓存内有效，不是 Docker 对象身份，也不是
Global Q70 的跨进程代际。所有状态写入都必须经过观察票校验；动作队列按名称串行。
"""
import collections
import dataclasses
import datetime
import logging
import subprocess
import threading
import time
import uuid

import docker

from ..constant import ContainerStatus
from .docker_fact import DockerFact, fact_from_attrs, fact_from_container
from .port_mappings import extract_port_info

logger = logging.getLogger(__name__)

# 缓存对账间隔（秒）：事件流漏报时的兜底全量刷新
RECONCILE_INTERVAL = 15

# sshd 就绪探测间隔（秒）：对「创建完成、等待就绪确认」的容器做 exec probe。
PROBE_INTERVAL = 10

# sshd 就绪判定：容器内 :22 监听检查（四路合并，一次 exec）
_SSHD_READY_CMD = (
    "ss -ltn 2>/dev/null | grep -q :22 || "
    "netstat -ltn 2>/dev/null | grep -q :22 || "
    "pgrep -f '[s]shd' >/dev/null 2>&1 || "
    "ps aux 2>/dev/null | grep -q [s]shd"
)

# 转换态超时兜底（秒）。TTL 只停止受理过渡遮挡读面，不删除动作记录、
# 不清硬阻塞、也不把动作失败写成运行态 failed。
_ACTION_TTL = {
    "create": 1800,
    "start": 300,
    "stop": 300,
    "restart": 300,
    "pause": 300,
    "unpause": 300,
}
PENDING_TTL_SEC = 300

# 终结/非终结动作相位。unconfirmed/timed_out 不是完成证明。
TERMINAL_PHASES = {"confirmed", "idempotent_confirmed", "failed", "superseded"}
NON_TERMINAL_PHASES = {"accepted", "unconfirmed", "timed_out"}
VALID_PHASES = TERMINAL_PHASES | NON_TERMINAL_PHASES

# 运行态 failed 只允许由这些既有门禁/真实 Docker 故障形成（外加 created 半成品）。
HARD_BLOCK_REASONS = {
    "sshd_not_installed",
    "created_half_built",
    "docker_dead",
    "startup_command_exited",
}

_DOCKER_STATUS_TO_APP = {
    "running": ContainerStatus.ONLINE.value,
    "exited": ContainerStatus.OFFLINE.value,
    "dead": ContainerStatus.OFFLINE.value,
    "created": ContainerStatus.STARTING.value,
    "restarting": ContainerStatus.RESTARTING.value,
    "paused": ContainerStatus.PAUSED.value,
    "removing": ContainerStatus.OFFLINE.value,
}

# docker events 的动作（Action 优先，status 兼容）→ 是否需要触发新鲜观察。
_EVENT_STATE_ACTIONS = {
    "start",
    "unpause",
    "stop",
    "die",
    "kill",
    "destroy",
    "oom",
    "pause",
    "create",
    "restart",
}

# 噪声事件（不改变容器状态，绝不落缓存/event_log；数据通路对账契约 C2）。
_EVENT_NOISE = {
    "attach",
    "detach",
    "top",
    "exec_create",
    "exec_start",
    "exec_detach",
    "exec_die",
    "resize",
    "copy",
    "export",
    "import",
    "update",
    "rename",
    "commit",
    "health_status",
}

COLLECT_ERROR_MARKER = "collect_failed"


def _utc_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


@dataclasses.dataclass(frozen=True)
class ActionRef:
    """Node 本进程内的动作引用。"""

    node_epoch: str
    generation: int
    seq: int

    def as_dict(self) -> dict:
        return {"node_epoch": self.node_epoch, "generation": self.generation, "seq": self.seq}


@dataclasses.dataclass(frozen=True)
class Observation:
    """读取 Docker 前签发的观察票。"""

    node_epoch: str
    generation: int
    action_seq: int
    read_seq: int
    source: str = "inspect"
    from_create_confirmation: bool = False
    metrics: bool = False


@dataclasses.dataclass
class ActionOutcome:
    """动作执行结果（由 runner 返回，worker 负责 CAS 收尾）。"""

    phase: str
    error_reason: str | None = None


@dataclasses.dataclass
class _ActionRecord:
    ref: dict
    action: str
    phase: str
    transition: str
    accepted_at: datetime.datetime
    ttl: float
    error_reason: str | None = None
    finished_at: datetime.datetime | None = None
    docker_id: str | None = None
    from_create: bool = False

    @property
    def terminal(self) -> bool:
        return self.phase in TERMINAL_PHASES

    @property
    def expires_at(self) -> float:
        return self.accepted_at.timestamp() + self.ttl

    def projection(self) -> dict:
        return {
            "ref": dict(self.ref),
            "action": self.action,
            "phase": self.phase,
            "error_reason": self.error_reason,
        }


def _map_container_to_status(container) -> str:
    """docker 容器对象（c.status）→ 应用状态字符串；未映射 → unknown。"""
    raw = str(getattr(container, "status", "") or "")
    status = _DOCKER_STATUS_TO_APP.get(raw)
    if status is None:
        logger.warning(
            "status-cache: unmapped docker container status: name=%s status=%r",
            getattr(container, "name", "?"),
            raw,
        )
        return ContainerStatus.UNKNOWN.value
    return status


def _round_or_none(value, digits: int = 1):
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _sum_blkio_bytes(stats: dict, op_name: str) -> int:
    total = 0
    for item in ((stats.get("blkio_stats") or {}).get("io_service_bytes_recursive") or []):
        if str(item.get("op", "")).lower() == op_name:
            total += int(item.get("value") or 0)
    return total


def _allocated_gpu_devices(container) -> list[str]:
    try:
        attrs = getattr(container, "attrs", {}) or {}
        requests = ((attrs.get("HostConfig") or {}).get("DeviceRequests") or [])
    except Exception:
        return []
    devices: list[str] = []
    for req in requests:
        ids = req.get("DeviceIDs") or req.get("device_ids") or []
        if isinstance(ids, (list, tuple)):
            devices.extend(str(item) for item in ids)
    return devices


def _nvidia_gpu_runtime_by_index() -> dict[str, dict]:
    try:
        r = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception as e:
        logger.debug("status-cache nvidia-smi runtime skipped: %s", e)
        return {}
    if r.returncode != 0 or not r.stdout.strip():
        return {}

    result: dict[str, dict] = {}
    for line in r.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 5:
            continue
        try:
            index = int(parts[0])
            utilization = float(parts[2])
            memory_used = float(parts[3])
            memory_total = float(parts[4])
        except ValueError:
            continue
        item = {
            "vendor": "nvidia",
            "index": index,
            "name": parts[1],
            "utilization_gpu_percent": _round_or_none(utilization),
            "memory_used_mb": _round_or_none(memory_used),
            "memory_total_mb": _round_or_none(memory_total),
        }
        if memory_total > 0:
            item["memory_usage_percent"] = _round_or_none((memory_used / memory_total) * 100)
        result[str(index)] = item
    return result


def _container_runtime_metrics(container, gpu_runtime_by_index: dict[str, dict] | None = None) -> dict:
    gpu_device_ids = _allocated_gpu_devices(container)
    gpu_runtime_by_index = gpu_runtime_by_index or {}
    metrics = {
        "collected_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        "gpu": {
            "device_ids": gpu_device_ids,
            "devices": [
                gpu_runtime_by_index[device_id]
                for device_id in gpu_device_ids
                if device_id in gpu_runtime_by_index
            ],
        },
    }
    if str(getattr(container, "status", "") or "") != "running":
        logger.debug(
            "status-cache runtime metrics skipped: name=%s status=%s",
            getattr(container, "name", "?"),
            getattr(container, "status", None),
        )
        return metrics
    try:
        stats = container.stats(stream=False) or {}
    except Exception as e:
        logger.warning(
            "status-cache runtime metrics skipped: name=%s err=%s",
            getattr(container, "name", "?"),
            e,
        )
        return metrics

    cpu_stats = stats.get("cpu_stats") or {}
    precpu_stats = stats.get("precpu_stats") or {}
    cpu_delta = (
        ((cpu_stats.get("cpu_usage") or {}).get("total_usage") or 0)
        - ((precpu_stats.get("cpu_usage") or {}).get("total_usage") or 0)
    )
    system_delta = (cpu_stats.get("system_cpu_usage") or 0) - (precpu_stats.get("system_cpu_usage") or 0)
    online_cpus = cpu_stats.get("online_cpus") or len((cpu_stats.get("cpu_usage") or {}).get("percpu_usage") or []) or 1
    if cpu_delta > 0 and system_delta > 0:
        metrics["cpu_usage_percent"] = _round_or_none((cpu_delta / system_delta) * online_cpus * 100)

    memory_stats = stats.get("memory_stats") or {}
    memory_usage = memory_stats.get("usage")
    memory_limit = memory_stats.get("limit")
    cache_bytes = (memory_stats.get("stats") or {}).get("cache") or 0
    if memory_usage is not None:
        effective_usage = max(0, int(memory_usage) - int(cache_bytes))
        metrics["memory_usage_mb"] = _round_or_none(effective_usage / (1024 ** 2))
    if memory_limit:
        metrics["memory_limit_mb"] = _round_or_none(int(memory_limit) / (1024 ** 2))
        if memory_usage is not None:
            metrics["memory_usage_percent"] = _round_or_none(
                (max(0, int(memory_usage) - int(cache_bytes)) / int(memory_limit)) * 100
            )

    rx = tx = 0
    for net in (stats.get("networks") or {}).values():
        rx += int(net.get("rx_bytes") or 0)
        tx += int(net.get("tx_bytes") or 0)
    if rx or tx:
        metrics["network_rx_mb"] = _round_or_none(rx / (1024 ** 2))
        metrics["network_tx_mb"] = _round_or_none(tx / (1024 ** 2))

    read_bytes = _sum_blkio_bytes(stats, "read")
    write_bytes = _sum_blkio_bytes(stats, "write")
    if read_bytes or write_bytes:
        metrics["block_read_mb"] = _round_or_none(read_bytes / (1024 ** 2))
        metrics["block_write_mb"] = _round_or_none(write_bytes / (1024 ** 2))
    return metrics


class ContainerStatusCache:
    def __init__(self):
        # 每进程启动生成一次；Node 重启后旧 action_ref 永不匹配。
        self.node_epoch = str(uuid.uuid4())
        self._cache = {}      # name -> RuntimeState
        self._pending = {}    # legacy view: name -> transition dict
        self._build_pending = {}  # legacy build 读面；不参与 vanished 检测
        self._deleted = []    # [{"name", "generation"}]
        self._collect_error = None
        self._lock = threading.RLock()
        self._meta = {}       # name -> generation/action_seq/read_seq/current_action/last_action
        self._action_queues = {}
        self._action_workers = set()

    # ------------------------------------------------------------------
    # 内部小工具
    # ------------------------------------------------------------------
    def _meta_for(self, name: str) -> dict:
        meta = self._meta.get(name)
        if meta is None:
            meta = {
                "generation": 0,
                "action_seq": 0,
                "read_seq": 0,
                "last_applied_read_seq": 0,
                "metrics_read_seq": 0,
                "last_applied_metrics_read_seq": 0,
                "current_action": None,
                "last_action": None,
                "actions": collections.OrderedDict(),
                "create_pending": False,
                "path_version": 0,
            }
            self._meta[name] = meta
        return meta

    @staticmethod
    def _action_key(ref: dict) -> str:
        return f"{ref.get('node_epoch')}:{ref.get('generation')}:{ref.get('seq')}"

    def _remember_action_locked(self, meta: dict, record: "_ActionRecord") -> None:
        actions = meta.setdefault("actions", collections.OrderedDict())
        actions[self._action_key(record.ref)] = record
        while len(actions) > 32:
            oldest_key, oldest = next(iter(actions.items()))
            if not oldest.terminal:
                break
            actions.pop(oldest_key, None)

    def _reset_meta_locked(self, name: str, *, bump_generation: bool = True) -> dict:
        meta = self._meta_for(name)
        if bump_generation:
            meta["generation"] += 1
        meta["action_seq"] = 0
        meta["last_applied_read_seq"] = 0
        meta["last_applied_metrics_read_seq"] = 0
        meta["current_action"] = None
        meta["last_action"] = None
        meta["create_pending"] = False
        return meta

    def _runtime_identity(self, name: str) -> str | None:
        entry = self._cache.get(name) or {}
        return entry.get("docker_id")

    def _invalidate_ready_locked(self, name: str) -> None:
        entry = self._cache.get(name)
        if entry is not None:
            entry["ready_verified"] = False
            entry.pop("ready_identity", None)

    def _create_transition_locked(self, name: str) -> str:
        """create pending 时对外仍展示受理时的 building/creating 过渡。"""
        current = self._meta_for(name).get("current_action")
        if current is not None and current.action == "create" and not current.terminal:
            return current.transition
        return ContainerStatus.CREATING.value

    def _set_unknown_locked(
        self,
        name: str,
        source: str,
        *,
        reason: str | None = None,
        keep_metrics: bool = True,
    ) -> None:
        old = self._cache.get(name) or {}
        last_known = old.get("last_known_status") or (
            old.get("status") if old.get("status") not in (None, ContainerStatus.UNKNOWN.value) else None
        )
        entry = dict(old)
        entry["status"] = ContainerStatus.UNKNOWN.value
        entry["status_source"] = source
        entry.setdefault("unknown_since", _utc_iso())
        if last_known:
            entry["last_known_status"] = last_known
        entry["updated_at"] = _utc_iso()
        entry.pop("ready_check", None)
        if reason:
            entry["collect_error"] = reason
        if not keep_metrics:
            entry.pop("runtime_metrics", None)
        self._cache[name] = entry

    def _classify_fact_locked(
        self,
        name: str,
        fact: DockerFact,
        *,
        mark_ready: bool,
        source: str,
    ) -> str:
        """把已验证票据的新鲜事实映射为运行态，返回写入的 status。"""
        old = self._cache.get(name) or {}
        old_status = old.get("status")
        old_ready = old.get("ready_identity") or {}
        same_process = bool(
            fact.docker_id
            and fact.started_at
            and old_ready.get("docker_id") == fact.docker_id
            and old_ready.get("started_at") == fact.started_at
        )
        ready_ok = bool(old.get("ready_verified")) and same_process and fact.started_at is not None

        entry = dict(old)
        entry["updated_at"] = _utc_iso()
        entry.pop("status_source", None)
        entry.pop("unknown_since", None)
        entry.pop("cold_verify_since", None)
        entry.pop("collect_error", None)
        if fact.docker_id:
            entry["docker_id"] = fact.docker_id

        if mark_ready and fact.docker_id and fact.started_at:
            entry["ready_identity"] = {"docker_id": fact.docker_id, "started_at": fact.started_at}
            entry["ready_verified"] = True
            ready_ok = True
        elif fact.started_at and fact.docker_id and same_process and old.get("ready_verified"):
            entry["ready_identity"] = {"docker_id": fact.docker_id, "started_at": fact.started_at}
            entry["ready_verified"] = True
        elif not same_process:
            # 运行进程已变化（restart/外部重启/新对象/缺 StartedAt）：旧就绪证明失效。
            if fact.docker_id != old.get("docker_id") or fact.started_at != old_ready.get("started_at"):
                entry["ready_verified"] = False
                entry.pop("ready_identity", None)
                ready_ok = False

        hard_block = old.get("hard_block") is True and old.get("failed_reason") in HARD_BLOCK_REASONS

        if fact.paused:
            entry.pop("ready_check", None)
            if hard_block:
                # 已证实的硬阻塞不因暂停事实自动解除；保留到门禁通过/新代/删除。
                # 暂停不提供 sshd/created/dead 条件消失的证据。
                entry["status"] = ContainerStatus.FAILED.value
                entry["hard_block"] = True
                entry["ready_verified"] = False
                entry.pop("ready_identity", None)
            else:
                entry["status"] = ContainerStatus.PAUSED.value
                entry.pop("failed_reason", None)
                entry.pop("failed_detail", None)
                entry.pop("hard_block", None)
                # pause 保留同一进程的就绪证明
        elif fact.dead:
            entry["status"] = ContainerStatus.FAILED.value
            entry["hard_block"] = True
            entry["failed_reason"] = "docker_dead"
            entry["failed_detail"] = fact.error
            entry.pop("ready_check", None)
        elif fact.status == "created":
            if self._meta_for(name).get("create_pending"):
                # 创建仍在进行时，created 只是尚未 start 的中间态；不能提前
                # 抢先形成硬阻塞（否则读面会在合法 create 期间显示 failed）。
                entry["status"] = self._create_transition_locked(name)
                entry["ready_verified"] = False
                entry.pop("ready_identity", None)
                entry.pop("ready_check", None)
                entry.pop("hard_block", None)
                entry.pop("failed_reason", None)
                entry.pop("failed_detail", None)
            else:
                entry["status"] = ContainerStatus.FAILED.value
                entry["hard_block"] = True
                entry["failed_reason"] = "created_half_built"
                entry["failed_detail"] = "container object exists in docker 'created' state"
                entry.pop("ready_check", None)
        elif fact.restarting:
            entry["status"] = ContainerStatus.RESTARTING.value
            entry["ready_check"] = True
            entry["ready_verified"] = False
            entry.pop("ready_identity", None)
            entry.pop("hard_block", None)
            entry.pop("failed_reason", None)
            entry.pop("failed_detail", None)
        elif fact.running:
            if hard_block and entry.get("failed_reason") == "sshd_not_installed" and not ready_ok:
                # Docker running 不能证明 sshd 已修复：保持硬阻塞，等 probe 通过。
                entry["status"] = ContainerStatus.FAILED.value
                entry["hard_block"] = True
                entry.pop("ready_check", None)
            elif ready_ok:
                entry["status"] = ContainerStatus.ONLINE.value
                entry.pop("ready_check", None)
                entry.pop("hard_block", None)
                entry.pop("failed_reason", None)
                entry.pop("failed_detail", None)
            else:
                entry["status"] = ContainerStatus.STARTING.value
                entry["ready_check"] = True
                entry.pop("hard_block", None)
                entry.pop("failed_reason", None)
                entry.pop("failed_detail", None)
        elif fact.status in {"exited", "stopped", "removing"}:
            entry["status"] = ContainerStatus.OFFLINE.value
            entry.pop("ready_check", None)
            entry.pop("hard_block", None)
            entry.pop("failed_reason", None)
            entry.pop("failed_detail", None)
        else:
            entry["status"] = ContainerStatus.UNKNOWN.value
            entry["status_source"] = source or "inspect_unknown"
            entry["unknown_since"] = old.get("unknown_since") or _utc_iso()
            if old_status and old_status != ContainerStatus.UNKNOWN.value:
                entry["last_known_status"] = old_status
            entry.pop("ready_check", None)

        if entry.get("status") != ContainerStatus.UNKNOWN.value:
            entry["last_known_status"] = entry["status"]
        self._cache[name] = entry
        return entry["status"]

    def _publish_locked(self, name: str, ticket: Observation, fact: DockerFact | None, *, mark_ready: bool = False) -> bool:
        meta = self._meta_for(name)
        if ticket.node_epoch != self.node_epoch:
            logger.info("status-cache publish rejected: stale node epoch name=%s", name)
            return False
        if ticket.generation != meta["generation"]:
            logger.info(
                "status-cache publish rejected: name=%s stale generation ticket=%s current=%s",
                name,
                ticket.generation,
                meta["generation"],
            )
            return False
        if ticket.action_seq != meta["action_seq"]:
            logger.info(
                "status-cache publish rejected: name=%s superseded action ticket=%s current=%s",
                name,
                ticket.action_seq,
                meta["action_seq"],
            )
            return False
        if ticket.read_seq <= meta["last_applied_read_seq"]:
            logger.info(
                "status-cache publish rejected: name=%s stale read ticket=%s applied=%s",
                name,
                ticket.read_seq,
                meta["last_applied_read_seq"],
            )
            return False
        if fact is None:
            self._set_unknown_locked(name, ticket.source or "inspect_unknown", reason="inspect_unavailable")
            meta["last_applied_read_seq"] = ticket.read_seq
            return True

        entry = self._cache.get(name) or {}
        current_docker = entry.get("docker_id")
        if fact.docker_id and current_docker and fact.docker_id != current_docker:
            if meta["create_pending"]:
                logger.info(
                    "status-cache identity_change_deferred: name=%s current=%s observed=%s create_pending=true",
                    name,
                    current_docker,
                    fact.docker_id,
                )
                return False
            # 票已通过 generation/action_seq/read_seq 校验，才允许推进新代际。
            old_action = meta.get("current_action")
            if old_action is not None and not old_action.terminal:
                old_action.phase = "superseded"
                old_action.error_reason = old_action.error_reason or "identity_changed"
                old_action.finished_at = _utc_now()
            meta["generation"] += 1
            meta["action_seq"] = 0
            meta["last_applied_read_seq"] = 0
            meta["last_applied_metrics_read_seq"] = 0
            meta["current_action"] = None
            meta["create_pending"] = False
            self._cache.pop(name, None)
            self._pending.pop(name, None)
            self._deleted = [item for item in self._deleted if self._deleted_name(item) != name]
            logger.warning(
                "status-cache identity changed: name=%s old=%s new=%s generation=%s",
                name,
                current_docker,
                fact.docker_id,
                meta["generation"],
            )
            self._classify_fact_locked(name, fact, mark_ready=mark_ready, source=ticket.source)
        else:
            if fact.docker_id and not current_docker:
                if meta["create_pending"] and not ticket.from_create_confirmation:
                    logger.info(
                        "status-cache identity_bind_deferred: name=%s observed=%s create_pending=true",
                        name,
                        fact.docker_id,
                    )
                    return False
                entry = self._cache.setdefault(name, {"status": ContainerStatus.UNKNOWN.value, "updated_at": _utc_iso()})
                entry["docker_id"] = fact.docker_id
            self._classify_fact_locked(name, fact, mark_ready=mark_ready, source=ticket.source)

        # create 自身确认的首次 docker_id 绑定：不推进代际、不取消 create。
        if meta["create_pending"] and ticket.from_create_confirmation:
            logger.info("status-cache create first bind: name=%s docker_id=%s", name, fact.docker_id)
        meta["last_applied_read_seq"] = ticket.read_seq
        return True

    def _inspect_fact(self, name: str, client=None) -> DockerFact:
        from .. import extensions

        if client is None:
            client = extensions.docker_client
        if client is None:
            client = docker.from_env()
        container = client.containers.get(name)
        reload = getattr(container, "reload", None)
        if callable(reload):
            reload()
        return fact_from_container(container)

    def _confirm_absent(self, name: str, client) -> bool:
        try:
            client.containers.get(name)
            return False
        except docker.errors.NotFound:
            return True

    # ------------------------------------------------------------------
    # 读面
    # ------------------------------------------------------------------
    def get_collect_error(self) -> str | None:
        with self._lock:
            return self._collect_error

    def get(self, name: str) -> dict | None:
        with self._lock:
            entry = self._cache.get(name)
            return dict(entry) if entry is not None else None

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._cache)

    def _last_action_projection(self, meta: dict) -> dict | None:
        record = meta.get("last_action")
        return record.projection() if record is not None else None

    def _project_state_locked(self, name: str) -> dict:
        meta = self._meta_for(name)
        runtime = self._cache.get(name)
        last_action = self._last_action_projection(meta)

        if runtime is not None and runtime.get("status") == ContainerStatus.FAILED.value:
            reason = runtime.get("failed_reason")
            if runtime.get("hard_block") and reason in HARD_BLOCK_REASONS:
                return {
                    "source": "cache",
                    "status": ContainerStatus.FAILED.value,
                    "failed_reason": reason,
                    "failed_detail": runtime.get("failed_detail"),
                    "error_reason": reason,
                    "runtime_metrics": runtime.get("runtime_metrics"),
                    "port": runtime.get("port"),
                    "port_mappings": runtime.get("port_mappings"),
                    "cache_updated_at": runtime.get("updated_at"),
                    "last_action": last_action,
                }

        if runtime is not None and runtime.get("ready_check"):
            return {
                "source": "cache",
                "status": runtime.get("status") or ContainerStatus.STARTING.value,
                "ready_check": True,
                "runtime_metrics": runtime.get("runtime_metrics"),
                "port": runtime.get("port"),
                "port_mappings": runtime.get("port_mappings"),
                "cache_updated_at": runtime.get("updated_at"),
                "last_action": last_action,
            }

        # 当前动作受理过渡态；过期后不再遮挡运行态，但动作记录仍保留。
        current = meta.get("current_action")
        if current is not None and not current.terminal:
            if time.time() <= current.expires_at:
                return {
                    "source": "pending",
                    "status": current.transition,
                    "runtime_metrics": (runtime or {}).get("runtime_metrics"),
                    "port": (runtime or {}).get("port"),
                    "port_mappings": (runtime or {}).get("port_mappings"),
                    "last_action": last_action,
                }
            current.phase = "timed_out"
            last_action = self._last_action_projection(meta)

        build = self._build_pending.get(name)
        if build is not None:
            status = build.get("status") or ContainerStatus.BUILDING.value
            if status != ContainerStatus.FAILED.value and time.time() > build.get("expires_at", 0):
                status = ContainerStatus.BUILDING.value
            return {
                "source": "build",
                "status": status,
                "failed_reason": build.get("failed_reason"),
                "failed_detail": build.get("failed_detail"),
                "error_reason": build.get("failed_reason"),
                "last_action": last_action,
            }

        if runtime is not None:
            raw_status = runtime.get("status") or ContainerStatus.UNKNOWN.value
            status_source = runtime.get("status_source")
            unknown_since = runtime.get("unknown_since")
            last_known = runtime.get("last_known_status")
            if raw_status == ContainerStatus.FAILED.value:
                # 只有允许集合内的硬阻塞可以占用运行态 failed；历史/动作失败
                # 痕迹不得继续冒充当前运行态。
                reason = runtime.get("failed_reason")
                if not (runtime.get("hard_block") and reason in HARD_BLOCK_REASONS):
                    raw_status = ContainerStatus.UNKNOWN.value
                    status_source = "inconsistent_failed"
                    unknown_since = unknown_since or runtime.get("updated_at")
                    # failed_reason 不是状态值；不得写进 last_known_status。
                    last_known = last_known if last_known in {
                        ContainerStatus.ONLINE.value,
                        ContainerStatus.OFFLINE.value,
                        ContainerStatus.PAUSED.value,
                        ContainerStatus.STARTING.value,
                        ContainerStatus.RESTARTING.value,
                    } else None
            result = {
                "source": "cache",
                "status": raw_status,
                "failed_reason": runtime.get("failed_reason") if raw_status == ContainerStatus.FAILED.value else None,
                "failed_detail": runtime.get("failed_detail") if raw_status == ContainerStatus.FAILED.value else None,
                "runtime_metrics": runtime.get("runtime_metrics"),
                "port": runtime.get("port"),
                "port_mappings": runtime.get("port_mappings"),
                "error_reason": runtime.get("failed_reason") if raw_status == ContainerStatus.FAILED.value else None,
                "cache_updated_at": runtime.get("updated_at"),
                "last_action": last_action,
            }
            if status_source:
                result["status_source"] = status_source
            if unknown_since:
                result["unknown_since"] = unknown_since
            if last_known:
                result["last_known_status"] = last_known
            return result

        if last_action is not None:
            return {"source": "miss", "status": ContainerStatus.UNKNOWN.value, "last_action": last_action}
        return {"source": "miss", "last_action": None}

    def get_state(self, name: str) -> dict:
        with self._lock:
            return self._project_state_locked(name)

    def list_states(self) -> dict:
        with self._lock:
            names = set(self._cache) | set(self._pending) | set(self._build_pending)
            result = {}
            for name in names:
                st = self._project_state_locked(name)
                if st.get("source") == "miss":
                    continue
                result[name] = st
            return result

    # ------------------------------------------------------------------
    # 观察票与发布 CAS
    # ------------------------------------------------------------------
    def issue_observation(
        self,
        name: str,
        source: str = "inspect",
        *,
        generation: int | None = None,
        action_seq: int | None = None,
        from_create_confirmation: bool = False,
        metrics: bool = False,
    ) -> Observation:
        """签发读取前票据。

        ``generation``/``action_seq`` 必须由动作受理时的 ref 显式固定；不传才取
        当前值（对账/事件等无动作上下文的观察）。旧动作不能借新代票。
        """
        with self._lock:
            meta = self._meta_for(name)
            ticket_generation = meta["generation"] if generation is None else generation
            ticket_action_seq = meta["action_seq"] if action_seq is None else action_seq
            if metrics:
                meta["metrics_read_seq"] += 1
                return Observation(
                    node_epoch=self.node_epoch,
                    generation=ticket_generation,
                    action_seq=ticket_action_seq,
                    read_seq=meta["metrics_read_seq"],
                    source=source,
                    from_create_confirmation=from_create_confirmation,
                    metrics=True,
                )
            meta["read_seq"] += 1
            return Observation(
                node_epoch=self.node_epoch,
                generation=ticket_generation,
                action_seq=ticket_action_seq,
                read_seq=meta["read_seq"],
                source=source,
                from_create_confirmation=from_create_confirmation,
            )

    def publish_fact(
        self,
        name: str,
        ticket: Observation,
        fact: DockerFact | None,
        *,
        runtime_metrics: dict | None = None,
        mark_ready: bool = False,
    ) -> bool:
        """兼容别名：返回 CAS 是否发布。"""
        return self.publish_observed(
            name,
            ticket,
            fact,
            runtime_metrics=runtime_metrics,
            mark_ready=mark_ready,
        )

    def publish_observed(
        self,
        name: str,
        ticket: Observation,
        fact: DockerFact | None,
        *,
        runtime_metrics: dict | None = None,
        mark_ready: bool = False,
        attrs: dict | None = None,
    ) -> bool:
        with self._lock:
            if ticket.metrics:
                return False
            ok = self._publish_locked(name, ticket, fact, mark_ready=mark_ready)
            if ok:
                entry = self._cache.get(name)
                if entry is not None:
                    if runtime_metrics is not None:
                        entry["runtime_metrics"] = runtime_metrics
                    if attrs is not None:
                        port, port_mappings = extract_port_info(attrs)
                        if port is not None:
                            entry["port"] = port
                        entry["port_mappings"] = port_mappings
            return ok

    def publish_unknown(self, name: str, ticket: Observation, *, reason: str | None = None) -> bool:
        with self._lock:
            if ticket.metrics:
                return False
            ok = self._publish_locked(name, ticket, None)
            if ok:
                entry = self._cache.get(name)
                if entry is not None and reason:
                    entry["status_source"] = reason
            return ok

    def publish_metrics(self, name: str, ticket: Observation, runtime_metrics: dict) -> bool:
        if not ticket.metrics:
            return False
        with self._lock:
            meta = self._meta_for(name)
            if ticket.node_epoch != self.node_epoch:
                return False
            if ticket.generation != meta["generation"]:
                return False
            if ticket.action_seq != meta["action_seq"]:
                return False
            if ticket.read_seq <= meta["last_applied_metrics_read_seq"]:
                return False
            entry = self._cache.get(name)
            if entry is None:
                return False
            entry["runtime_metrics"] = runtime_metrics
            entry["updated_at"] = _utc_iso()
            meta["last_applied_metrics_read_seq"] = ticket.read_seq
            return True

    def refresh_from_docker(
        self,
        name: str,
        *,
        source: str = "inspect",
        action_ref: dict | None = None,
        generation: int | None = None,
        action_seq: int | None = None,
        from_create_confirmation: bool = False,
        runtime_metrics: dict | None = None,
        mark_ready: bool = False,
        client=None,
    ) -> DockerFact | None:
        """读取前签票 → 新鲜 inspect → 发布 CAS。inspect 失败转 unknown。

        动作后置观察必须传 ``action_ref``（受理时的 epoch/generation/seq），
        不能只固定 seq 而让 generation 取当前值。
        """
        if action_ref is not None:
            if action_ref.get("node_epoch") != self.node_epoch:
                logger.info("status-cache action observation rejected: stale epoch name=%s ref=%s", name, action_ref)
                return None
            generation = action_ref.get("generation")
            action_seq = action_ref.get("seq")
        ticket = self.issue_observation(
            name,
            source,
            generation=generation,
            action_seq=action_seq,
            from_create_confirmation=from_create_confirmation,
        )
        try:
            fact = self._inspect_fact(name, client=client)
        except docker.errors.NotFound:
            self.publish_unknown(name, ticket, reason="not_found")
            return None
        except Exception as e:
            logger.warning("status-cache fresh inspect failed: name=%s err=%s", name, e)
            self.publish_unknown(name, ticket, reason="inspect_failed")
            return None
        self.publish_observed(
            name,
            ticket,
            fact,
            runtime_metrics=runtime_metrics,
            mark_ready=mark_ready,
            attrs=getattr(fact, "attrs", None) if fact is not None else None,
        )
        return fact

    # ------------------------------------------------------------------
    # 动作受理 / 动作队列 / 动作结果
    # ------------------------------------------------------------------
    def _build_action_locked(
        self,
        name: str,
        action: str,
        transition: str,
        *,
        create: bool,
    ) -> _ActionRecord:
        meta = self._meta_for(name)
        if create:
            meta["generation"] += 1
            meta["action_seq"] = 0
            meta["last_applied_read_seq"] = 0
            meta["last_applied_metrics_read_seq"] = 0
            old = meta.get("current_action")
            if old is not None and not old.terminal:
                old.phase = "superseded"
                old.error_reason = old.error_reason or "new_create"
                old.finished_at = _utc_now()
            meta["current_action"] = None
            meta["create_pending"] = True
            # create 受理先于后台线程可见；reconcile 不会把 building/creating 当证据。
            self._cache[name] = {
                "status": transition,
                "updated_at": _utc_iso(),
            }
            self._pending.pop(name, None)
            self._build_pending.pop(name, None)
            self._deleted = [item for item in self._deleted if self._deleted_name(item) != name]
            self._invalidate_ready_locked(name)
            # 旧代尚未执行的队列项由 worker 的代际检查跳过。
        else:
            prev = meta.get("current_action")
            if prev is not None and not prev.terminal:
                prev.phase = "superseded"
                prev.error_reason = "superseded_by_new_action"
                prev.finished_at = _utc_now()
        meta["action_seq"] += 1
        seq = meta["action_seq"]
        ref = ActionRef(self.node_epoch, meta["generation"], seq)
        ttl = _ACTION_TTL.get(action, PENDING_TTL_SEC)
        record = _ActionRecord(
            ref=ref.as_dict(),
            action=action,
            phase="accepted",
            transition=transition,
            accepted_at=_utc_now(),
            ttl=ttl,
            docker_id=self._runtime_identity(name),
            from_create=create,
        )
        if action == "restart":
            # 显式 restart 受理即清除旧 ready 证明；StartedAt 变化后不得复用。
            self._invalidate_ready_locked(name)
        self._remember_action_locked(meta, record)
        meta["current_action"] = record
        meta["last_action"] = record
        self._pending[name] = {
            "action": action,
            "status": transition,
            "failed_reason": None,
            "failed_detail": None,
            "started_at": datetime.datetime.utcnow(),
            "ttl": ttl,
            "ref": ref.as_dict(),
        }
        return record

    def accept_action(self, name: str, action: str, transition: str, *, create: bool = False) -> dict:
        """在返回受理响应前分配 action_seq/action_ref 并登记过渡态。"""
        with self._lock:
            record = self._build_action_locked(name, action, transition, create=create)
            logger.info(
                "status-cache accept_action: name=%s action=%s ref=%s transition=%s",
                name,
                action,
                record.ref,
                transition,
            )
            return dict(record.ref)

    def submit_action(self, name: str, action: str, transition: str, runner, *, create: bool = False) -> dict:
        """受理动作并按名称串行执行。runner(full_ref) 返回 ActionOutcome。

        返回值只含 wire 三元组；内部队列/runner 的 ref 额外带 ``name`` 供收尾定位。
        """
        with self._lock:
            record = self._build_action_locked(name, action, transition, create=create)
            ref = dict(record.ref)
            full_ref = {**ref, "name": name, "action": action}
            queue = self._action_queues.setdefault(name, collections.deque())
            queued = (full_ref, runner)
            queue.append(queued)
            if name not in self._action_workers:
                self._action_workers.add(name)
                try:
                    threading.Thread(
                        target=self._action_worker,
                        args=(name,),
                        daemon=True,
                        name=f"status-action-{name}",
                    ).start()
                except Exception:
                    # 本项已被标记 failed；必须把它从队列移除，否则下一次成功启动
                    # worker 时会把这次从未执行的副作用重新跑一遍。
                    try:
                        queue.remove(queued)
                    except ValueError:
                        pass
                    if not queue:
                        self._action_queues.pop(name, None)
                    self._action_workers.discard(name)
                    self.finish_action_ref(full_ref, "failed", "background_thread_failed")
                    raise
        logger.info("status-cache submit_action: name=%s action=%s ref=%s", name, action, ref)
        return ref

    def _action_worker(self, name: str) -> None:
        while True:
            with self._lock:
                queue = self._action_queues.get(name)
                if not queue:
                    self._action_queues.pop(name, None)
                    self._action_workers.discard(name)
                    return
                ref, runner = queue.popleft()
                meta = self._meta_for(name)
                if ref.get("node_epoch") != self.node_epoch or ref.get("generation") != meta["generation"]:
                    logger.info("status-cache action skipped (generation changed): name=%s ref=%s", name, ref)
                    self.finish_action_ref(ref, "superseded", "generation_changed")
                    continue
                record = self._find_action_locked(meta, self._pure_ref(ref))
                if record is None:
                    logger.info("status-cache action skipped (missing record): name=%s ref=%s", name, ref)
                    continue
                if record.phase == "failed":
                    # 受理后的启动/执行失败已终结该动作；绝不因后续 worker 重跑副作用。
                    logger.info("status-cache action skipped (already failed): name=%s ref=%s", name, ref)
                    continue
            try:
                outcome = runner(ref)
                phase = getattr(outcome, "phase", None) or "failed"
                reason = getattr(outcome, "error_reason", None)
                detail = getattr(outcome, "detail", None)
                if detail:
                    logger.warning(
                        "status-cache action detail: name=%s action=%s ref=%s phase=%s reason=%s detail=%s",
                        name,
                        ref.get("action") or "unknown",
                        ref,
                        phase,
                        reason,
                        detail,
                    )
            except Exception as e:
                logger.warning("status-cache action runner failed: name=%s ref=%s err=%s", name, ref, e)
                phase, reason = "failed", "action_runner_error"
            self.finish_action_ref(ref, phase, reason)

    @staticmethod
    def _deleted_name(item) -> str | None:
        if isinstance(item, dict):
            return item.get("name")
        return str(item)

    @staticmethod
    def _pure_ref(ref: dict) -> dict:
        return {key: ref.get(key) for key in ("node_epoch", "generation", "seq")}

    def action_generation_valid(self, ref: dict) -> bool:
        """动作代际是否仍有效（同一代际内被新动作取代时仍可执行其 Docker 意图）。"""
        name = ref.get("name")
        if not name:
            return False
        with self._lock:
            meta = self._meta_for(name)
            return (
                ref.get("node_epoch") == self.node_epoch
                and ref.get("generation") == meta["generation"]
            )

    def action_is_current(self, ref: dict) -> bool:
        name = ref.get("name")
        if not name:
            return False
        with self._lock:
            meta = self._meta_for(name)
            current = meta.get("current_action")
            return (
                ref.get("node_epoch") == self.node_epoch
                and ref.get("generation") == meta["generation"]
                and ref.get("seq") == meta["action_seq"]
                and current is not None
                and current.ref == self._pure_ref(ref)
                and not current.terminal
            )

    def _find_action_locked(self, meta: dict, ref: dict):
        key = self._action_key(ref)
        record = (meta.get("actions") or {}).get(key)
        if record is not None:
            return record
        current = meta.get("current_action")
        if current is not None and current.ref == ref:
            return current
        last = meta.get("last_action")
        if last is not None and last.ref == ref:
            return last
        return None

    def finish_action_ref(self, ref: dict, phase: str, error_reason: str | None = None) -> bool:
        name = ref.get("name")
        if not name:
            logger.warning("status-cache finish_action_ref missing name: ref=%s", ref)
            return False
        pure = self._pure_ref(ref)
        with self._lock:
            meta = self._meta_for(name)
            if pure.get("node_epoch") != self.node_epoch:
                logger.info("status-cache finish rejected: stale epoch name=%s ref=%s", name, pure)
                return False
            record = self._find_action_locked(meta, pure)
            if record is None:
                logger.info("status-cache finish rejected: unknown/old ref name=%s ref=%s", name, pure)
                return False
            if phase not in VALID_PHASES:
                phase = "failed"
                error_reason = error_reason or "invalid_phase"
            if record.terminal:
                # create 被同代新动作取代后，原 record 已是终态；但其后台 Docker
                # 意图仍会跑完。跑完后必须释放 create 对名称的 pending 所有权，
                # 否则后续观察永远无法绑定/换代，删除候选也被永久挡住。
                if (
                    record.action == "create"
                    and record.from_create
                    and pure.get("generation") == meta.get("generation")
                    and meta.get("create_pending")
                ):
                    current = meta.get("current_action")
                    if current is None or current.ref != pure:
                        meta["create_pending"] = False
                        logger.info(
                            "status-cache create ownership released after terminal create: name=%s ref=%s",
                            name,
                            pure,
                        )
                if phase in NON_TERMINAL_PHASES:
                    logger.info(
                        "status-cache finish ignored: terminal not regressed name=%s ref=%s phase=%s current=%s",
                        name,
                        pure,
                        phase,
                        record.phase,
                    )
                else:
                    logger.info(
                        "status-cache finish ignored: terminal already set name=%s ref=%s current=%s incoming=%s",
                        name,
                        pure,
                        record.phase,
                        phase,
                    )
                return False
            if pure.get("seq") != meta["action_seq"] or pure.get("generation") != meta["generation"]:
                record.phase = "superseded"
                record.error_reason = record.error_reason or "superseded"
                record.finished_at = _utc_now()
                logger.info("status-cache action superseded: name=%s ref=%s", name, pure)
                return False
            record.phase = phase
            record.error_reason = error_reason
            if phase in TERMINAL_PHASES:
                record.finished_at = _utc_now()
                if meta.get("current_action") is record:
                    meta["current_action"] = None
                self._pending.pop(name, None)
                if record.from_create:
                    meta["create_pending"] = False
                if record.action == "create" and phase in {"confirmed", "idempotent_confirmed", "failed"}:
                    runtime = self._cache.get(name) or {}
                    if runtime.get("status") in (ContainerStatus.BUILDING.value, ContainerStatus.CREATING.value):
                        if runtime.get("docker_id"):
                            # create 结束时 Docker 对象仍停在 created（没有运行进程）：
                            # 此时才形成半成品硬阻塞。创建进行中不提前阻塞。
                            self.set_hard_block(
                                name,
                                "created_half_built",
                                "container object remains in docker 'created' state after create finished",
                            )
                        elif phase == "failed":
                            self._set_unknown_locked(name, "create_failed", reason=error_reason)
                            runtime = self._cache.get(name) or {}
                            runtime.pop("last_known_status", None)
            logger.info(
                "status-cache finish_action: name=%s action=%s ref=%s phase=%s reason=%s",
                name,
                record.action,
                pure,
                phase,
                error_reason,
            )
            return True

    def begin_action(self, name: str, action: str, ing_status: str) -> dict:
        """兼容旧调用：受理一个不自动执行的过渡动作，返回 action_ref。"""
        with self._lock:
            return dict(self._build_action_locked(name, action, ing_status, create=(action == "create")).ref)

    def finish_action(
        self,
        name: str,
        status: str | None,
        failed_reason: str | None = None,
        failed_detail: str | None = None,
    ) -> None:
        """兼容旧调用：只终结当前动作，绝不直接回写运行态。

        生产动作走 ``submit_action`` + 观察票发布；运行态只能由新鲜 Docker
        事实经 ``publish_observed`` 写入。``status`` 仅用于兼容签名和失败相位
        识别，不再被当作运行态事实。
        """
        with self._lock:
            meta = self._meta_for(name)
            record = meta.get("current_action")
            if record is None:
                logger.warning("status-cache finish_action ignored: no current action name=%s", name)
                return
            ref = {**dict(record.ref), "name": name}
            phase = "failed" if status == ContainerStatus.FAILED.value else "confirmed"
            if not self.finish_action_ref(ref, phase, failed_reason):
                logger.warning("status-cache finish_action ignored: stale action name=%s ref=%s", name, ref)
                return
            logger.info(
                "status-cache finish_action compat: name=%s phase=%s (runtime not written)",
                name,
                phase,
            )

    def clear_pending(self, name: str) -> None:
        with self._lock:
            meta = self._meta_for(name)
            record = meta.get("current_action")
            if record is not None and not record.terminal:
                record.phase = "superseded"
                record.error_reason = "cleared"
                record.finished_at = _utc_now()
            meta["current_action"] = None
            meta["create_pending"] = False
            self._pending.pop(name, None)
            self._build_pending.pop(name, None)
        logger.info("status-cache clear_pending: name=%s", name)

    def get_pending(self, name: str) -> dict | None:
        with self._lock:
            meta = self._meta_for(name)
            record = meta.get("current_action")
            if record is not None and not record.terminal:
                if time.time() > record.expires_at:
                    record.phase = "timed_out"
                    logger.warning(
                        "status-cache pending timeout: name=%s action=%s ttl=%s (transition hidden)",
                        name,
                        record.action,
                        record.ttl,
                    )
                    return None
                return {
                    "action": record.action,
                    "status": record.transition,
                    "failed_reason": record.error_reason,
                    "failed_detail": None,
                    "started_at": datetime.datetime.utcfromtimestamp(record.accepted_at.timestamp()),
                    "ttl": record.ttl,
                    "ref": dict(record.ref),
                }
            legacy = self._pending.get(name)
            return dict(legacy) if legacy is not None else None

    def get_build_pending(self, name: str) -> dict | None:
        with self._lock:
            entry = self._build_pending.get(name)
            if entry is None:
                return None
            if entry["status"] != ContainerStatus.FAILED.value:
                age = (datetime.datetime.utcnow() - entry["started_at"]).total_seconds()
                if age > entry.get("ttl", PENDING_TTL_SEC):
                    entry["status"] = ContainerStatus.FAILED.value
                    entry["failed_reason"] = "build_timeout"
                    entry["failed_detail"] = f"image build timed out after {entry.get('ttl', PENDING_TTL_SEC)} seconds"
            return dict(entry)

    def begin_build(self, name: str) -> None:
        with self._lock:
            self._deleted = [item for item in self._deleted if self._deleted_name(item) != name]
            self._build_pending[name] = {
                "action": "build",
                "status": ContainerStatus.BUILDING.value,
                "failed_reason": None,
                "failed_detail": None,
                "started_at": datetime.datetime.utcnow(),
                "ttl": _ACTION_TTL.get("create", PENDING_TTL_SEC),
                "expires_at": time.time() + _ACTION_TTL.get("create", PENDING_TTL_SEC),
            }
        logger.info("status-cache begin_build: name=%s status=%s", name, ContainerStatus.BUILDING.value)

    def finish_build_failed(self, name: str, failed_reason: str | None = None, failed_detail: str | None = None) -> None:
        with self._lock:
            entry = self._build_pending.get(name)
            if entry is None:
                entry = {
                    "action": "build",
                    "started_at": datetime.datetime.utcnow(),
                    "ttl": _ACTION_TTL.get("create", PENDING_TTL_SEC),
                }
                self._build_pending[name] = entry
            entry["status"] = ContainerStatus.FAILED.value
            entry["failed_reason"] = failed_reason
            entry["failed_detail"] = failed_detail
        logger.warning(
            "status-cache finish_build_failed: name=%s reason=%s detail=%s",
            name,
            failed_reason,
            failed_detail,
        )

    def clear_build(self, name: str) -> None:
        with self._lock:
            self._build_pending.pop(name, None)
        logger.info("status-cache clear_build: name=%s", name)

    def mark_ready_check(
        self,
        name: str,
        status: str = ContainerStatus.STARTING.value,
        *,
        cold_verify: bool = False,
    ) -> None:
        with self._lock:
            old_entry = self._cache.get(name, {})
            meta = self._meta_for(name)
            if meta.get("current_action") is not None and not meta["current_action"].terminal:
                meta["current_action"].phase = "confirmed"
                meta["current_action"].finished_at = _utc_now()
                meta["current_action"] = None
            meta["create_pending"] = False
            self._pending.pop(name, None)
            entry = {
                "status": status,
                "ready_check": True,
                "updated_at": _utc_iso(),
            }
            if old_entry.get("docker_id"):
                entry["docker_id"] = old_entry["docker_id"]
            if old_entry.get("ready_verified") and old_entry.get("ready_identity"):
                entry["ready_verified"] = True
                entry["ready_identity"] = old_entry["ready_identity"]
            if cold_verify:
                entry["cold_verify_since"] = entry["updated_at"]
            if old_entry.get("port") is not None:
                entry["port"] = old_entry.get("port")
            if old_entry.get("port_mappings") is not None:
                entry["port_mappings"] = old_entry.get("port_mappings")
            if old_entry.get("runtime_metrics") is not None:
                entry["runtime_metrics"] = old_entry.get("runtime_metrics")
            self._cache[name] = entry
        logger.info("status-cache mark_ready_check: name=%s status=%s ready_check=true", name, status)

    def mark_ready_verified(
        self,
        name: str,
        fact: DockerFact,
        *,
        ticket: Observation,
        runtime_metrics: dict | None = None,
    ) -> bool:
        """发布就绪证明；ticket 必须在读取该事实 **之前** 签发。

        生产 probe 由 ``_probe_ready_once`` 保证 pre-inspect→probe→post-inspect
        同一进程；本方法不再自行“读完事实后补票”。
        """
        return self.publish_observed(name, ticket, fact, runtime_metrics=runtime_metrics, mark_ready=True)

    def set_hard_block(self, name: str, reason: str, detail: str | None = None) -> bool:
        if reason not in HARD_BLOCK_REASONS:
            logger.warning("status-cache hard block rejected (not in allowed set): name=%s reason=%s", name, reason)
            return False
        with self._lock:
            entry = dict(self._cache.get(name) or {})
            entry.update(
                {
                    "status": ContainerStatus.FAILED.value,
                    "hard_block": True,
                    "failed_reason": reason,
                    "failed_detail": detail,
                    "updated_at": _utc_iso(),
                }
            )
            entry.pop("ready_check", None)
            self._cache[name] = entry
            # 硬阻塞成立后，旧的 ready 证明不能成为后续 running 事实直接
            # 解除阻塞的旁路；必须重新通过 probe/门禁。
            self._invalidate_ready_locked(name)
        logger.warning("status-cache hard block: name=%s reason=%s detail=%s", name, reason, detail)
        return True

    def set_port_info(
        self,
        name: str,
        port: int | None,
        port_mappings: list | None,
        *,
        ref: dict | None = None,
    ) -> bool:
        with self._lock:
            if ref is not None and not self.action_is_current({**ref, "name": name}):
                logger.info("status-cache set_port_info rejected: stale action name=%s ref=%s", name, ref)
                return False
            entry = self._cache.setdefault(
                name,
                {
                    "status": ContainerStatus.UNKNOWN.value,
                    "updated_at": _utc_iso(),
                },
            )
            if port is not None:
                entry["port"] = port
            if port_mappings is not None:
                entry["port_mappings"] = port_mappings
        logger.info("status-cache set_port_info: name=%s port=%s mappings=%s", name, port, port_mappings)
        return True

    def update_runtime_metrics(self, name: str, runtime_metrics: dict) -> None:
        with self._lock:
            if name not in self._cache:
                return
            self._cache[name]["runtime_metrics"] = runtime_metrics
            self._cache[name]["updated_at"] = _utc_iso()

    # ------------------------------------------------------------------
    # Docker 事件（只触发新鲜 inspect，不直接写运行态）
    # ------------------------------------------------------------------
    @staticmethod
    def normalize_event_action(event: dict) -> str | None:
        raw = event.get("Action")
        if raw is None or str(raw).strip() == "":
            raw = event.get("status")
        if raw is None:
            return None
        # exec_create: /bin/sh / exec_start: ... 等带后缀动作按基础 exec_* 噪声处理。
        base = str(raw).split(":", 1)[0].strip().lower()
        return base or None

    def _apply_event(self, event: dict) -> None:
        actor = event.get("Actor") or {}
        attrs = actor.get("Attributes") or {}
        name = attrs.get("name") or event.get("name")
        if not name:
            return
        action = self.normalize_event_action(event)
        if not action:
            logger.warning("status-cache: docker event without action ignored: name=%s event=%r", name, event)
            return
        if action in _EVENT_NOISE:
            return
        if action not in _EVENT_STATE_ACTIONS:
            logger.warning("status-cache: unrecognized docker event ignored: name=%s action=%s", name, action)
            return

        # 事件轨迹（只记录已声明的状态动作；噪声/unknown 不进入）。
        from .. import extensions

        extensions.event_log.record(
            name,
            action,
            exit_code=attrs.get("exitCode"),
            reason="oom" if action == "oom" else None,
        )

        # 事件只作为触发器和诊断；观察票必须在新鲜 inspect 之前签发。
        # 事件时间/接收顺序不参与事实排序，inspect 不可判定时保留最后已知。
        ticket = self.issue_observation(name, f"event:{action}")
        try:
            fact = self._inspect_fact(name)
        except docker.errors.NotFound:
            logger.info("status-cache event inspect not_found (delete path owns removal): name=%s action=%s", name, action)
            return
        except Exception as e:
            logger.warning("status-cache event fresh inspect failed, keep last known: name=%s action=%s err=%s", name, action, e)
            return
        self.publish_observed(name, ticket, fact)

    # ------------------------------------------------------------------
    # 对账（Docker.list 只用于发现；最终事实按名称新鲜解析）
    # ------------------------------------------------------------------
    def _apply_container(self, container, gpu_runtime_by_index: dict[str, dict] | None = None) -> None:
        """单容器对账兼容入口：指标后按名称新鲜解析；旧对象不回写状态。"""
        name = container.name
        metrics_ticket = self.issue_observation(name, "reconcile_metrics", metrics=True)
        metrics = _container_runtime_metrics(container, gpu_runtime_by_index)
        ticket = self.issue_observation(name, "reconcile")
        try:
            fact = self._inspect_fact(name)
        except Exception as e:
            logger.warning("status-cache _apply_container fresh resolve failed: name=%s err=%s", name, e)
            self.publish_unknown(name, ticket, reason="collect_error")
            return
        if self.publish_observed(name, ticket, fact, attrs=getattr(fact, "attrs", None)):
            self.publish_metrics(name, metrics_ticket, metrics)

    def _reconcile_once(self) -> None:
        """单轮全量对账：只评价本轮开始前已知的代际，消失须单容器再确认。"""
        try:
            client = docker.from_env()
            with self._lock:
                baseline = {}
                for name, entry in self._cache.items():
                    if entry.get("docker_id") or entry.get("status") not in (
                        ContainerStatus.UNKNOWN.value,
                        ContainerStatus.BUILDING.value,
                        ContainerStatus.CREATING.value,
                    ):
                        baseline[name] = self._meta_for(name)["generation"]
            live = set()
            gpu_runtime_by_index = _nvidia_gpu_runtime_by_index()
            for c in client.containers.list(all=True):
                name = c.name
                live.add(name)
                # 指标与状态使用独立 read_seq；stats 慢不能抬高状态观察票。
                metrics_ticket = self.issue_observation(name, "reconcile_metrics", metrics=True)
                metrics = _container_runtime_metrics(c, gpu_runtime_by_index)
                # stats 可能耗时很久；最终状态必须在 stats 后按名称新鲜解析。
                ticket = self.issue_observation(name, "reconcile")
                try:
                    fresh = client.containers.get(name)
                    reload = getattr(fresh, "reload", None)
                    if callable(reload):
                        reload()
                    fact = fact_from_container(fresh)
                except docker.errors.NotFound:
                    logger.info("status-cache reconcile: container vanished during enumeration: name=%s", name)
                    continue
                except Exception as e:
                    logger.warning("status-cache reconcile fresh resolve failed: name=%s err=%s", name, e)
                    self.publish_unknown(name, ticket, reason="collect_error")
                    continue
                if self.publish_observed(
                    name,
                    ticket,
                    fact,
                    attrs=getattr(fresh, "attrs", None),
                ):
                    self.publish_metrics(name, metrics_ticket, metrics)

            confirm_failed = False
            for name in sorted(set(baseline) - live):
                with self._lock:
                    meta = self._meta_for(name)
                    if meta["generation"] != baseline[name]:
                        logger.info("status-cache vanish candidate skipped (generation changed): name=%s", name)
                        continue
                    if meta.get("create_pending") or name in self._build_pending or name in self._pending:
                        logger.info("status-cache vanish candidate skipped (create pending): name=%s", name)
                        continue
                try:
                    absent = self._confirm_absent(name, client)
                except Exception as e:
                    confirm_failed = True
                    logger.warning("status-cache vanish confirmation failed, keep cache: name=%s err=%s", name, e)
                    continue
                if not absent:
                    logger.info("status-cache vanish candidate still exists in docker, keep cache: name=%s", name)
                    continue
                with self._lock:
                    meta = self._meta_for(name)
                    if meta["generation"] != baseline[name] or meta.get("create_pending") \
                            or name in self._build_pending:
                        logger.info("status-cache vanish candidate invalidated before queue: name=%s", name)
                        continue
                    self._cache.pop(name, None)
                    self._pending.pop(name, None)
                    if not any(self._deleted_name(item) == name for item in self._deleted):
                        self._deleted.append({"name": name, "generation": meta["generation"]})
                    runtime = meta.get("current_action")
                    if runtime is not None and not runtime.terminal:
                        runtime.phase = "superseded"
                        runtime.error_reason = "container_vanished"
                        runtime.finished_at = _utc_now()
                        meta["current_action"] = None
                logger.warning("status-cache reconcile: container %r vanished (delete candidate queued)", name)
            with self._lock:
                self._collect_error = COLLECT_ERROR_MARKER if confirm_failed else None
        except Exception as e:
            with self._lock:
                self._collect_error = COLLECT_ERROR_MARKER
            logger.warning("status-cache reconcile failed (collect_error set): %s", e)

    # ------------------------------------------------------------------
    # 删除候选（携带本地代际；发送前再次确认）
    # ------------------------------------------------------------------
    def forget_container_generation(self, name: str) -> None:
        with self._lock:
            self._cache.pop(name, None)
            self._pending.pop(name, None)
            self._build_pending.pop(name, None)
            meta = self._meta_for(name)
            meta["generation"] += 1
            meta["action_seq"] = 0
            meta["last_applied_read_seq"] = 0
            meta["last_applied_metrics_read_seq"] = 0
            meta["current_action"] = None
            meta["last_action"] = None
            meta["create_pending"] = False
            meta.setdefault("actions", collections.OrderedDict()).clear()
            self._deleted = [item for item in self._deleted if self._deleted_name(item) != name]
        logger.info("status-cache forget_container_generation: name=%s", name)

    def take_deleted(self) -> list[str]:
        """兼容旧测试/调用的候选名读取；WSS MUST 使用 take_confirmed_deleted。"""
        with self._lock:
            items, self._deleted = self._deleted, []
        return [self._deleted_name(item) for item in items]

    def take_delete_candidates(self) -> list[dict]:
        with self._lock:
            items, self._deleted = self._deleted, []
        return items

    def take_confirmed_deleted(self) -> list[str]:
        """WSS 发送前：代际复核 + Docker 单容器再次确认，只有明确 NotFound 才发送。

        本轮 Docker 采集已失败时不得发送删除帧；候选保留在内部队列，等下一次
        成功对账后再确认。这里与 ``_collect_error`` 在同一锁内判断/取出，避免
        采集错误刚置位时把候选取走。
        """
        with self._lock:
            if self._collect_error:
                logger.warning(
                    "status-cache delete candidates held: collect_error=%s",
                    self._collect_error,
                )
                return []
            candidates, self._deleted = self._deleted, []
        confirmed: list[str] = []
        retry: list[dict] = []
        if not candidates:
            return confirmed
        try:
            from .. import extensions

            client = extensions.docker_client
            if client is None:
                client = docker.from_env()
        except Exception as e:
            logger.warning("status-cache delete confirm unavailable, keep candidates: %s", e)
            with self._lock:
                self._deleted.extend(candidates)
                self._collect_error = COLLECT_ERROR_MARKER
            return confirmed

        for candidate in candidates:
            if not isinstance(candidate, dict):
                candidate = {"name": str(candidate), "generation": None}
            name = candidate["name"]
            with self._lock:
                meta = self._meta_for(name)
                if candidate.get("generation") is None:
                    candidate["generation"] = meta["generation"]
                if meta["generation"] != candidate["generation"] or meta.get("create_pending") \
                        or name in self._build_pending:
                    logger.info("status-cache delete candidate invalidated before send: name=%s", name)
                    continue
            try:
                absent = self._confirm_absent(name, client)
            except Exception as e:
                logger.warning("status-cache delete confirm failed, keep candidate: name=%s err=%s", name, e)
                retry.append(candidate)
                continue
            if not absent:
                logger.info("status-cache delete candidate reappeared, dropped: name=%s", name)
                continue
            with self._lock:
                meta = self._meta_for(name)
                if meta["generation"] != candidate["generation"] or meta.get("create_pending") \
                        or name in self._build_pending:
                    continue
                self._cache.pop(name, None)
                self._pending.pop(name, None)
                # 删除也是一次对象代际结束：推进代际并清空动作诊断，让在途旧票/
                # 旧 finish 不能再重建该名称的运行态或复活旧 last_action。
                meta["generation"] += 1
                meta["action_seq"] = 0
                meta["last_applied_read_seq"] = 0
                meta["last_applied_metrics_read_seq"] = 0
                meta["current_action"] = None
                meta["last_action"] = None
                meta["create_pending"] = False
                meta.setdefault("actions", collections.OrderedDict()).clear()
            confirmed.append(name)
            logger.warning("status-cache delete confirmed: name=%s generation=%s", name, candidate["generation"])
        if retry:
            with self._lock:
                for candidate in retry:
                    if not any(self._deleted_name(item) == candidate["name"] for item in self._deleted):
                        self._deleted.append(candidate)
        return confirmed

    # ------------------------------------------------------------------
    # 就绪确认/自愈
    # ------------------------------------------------------------------
    @staticmethod
    def _probe_client():
        from .. import extensions
        if extensions.docker_client is None:
            extensions.init_docker()
        return extensions.docker_client

    def _probe_sshd_container(self, container) -> bool:
        try:
            r = container.exec_run(["/bin/sh", "-c", _SSHD_READY_CMD], user="root")
            return getattr(r, "exit_code", r[0]) == 0
        except Exception:
            return False

    def _probe_sshd(self, name: str) -> bool:
        try:
            container = self._probe_client().containers.get(name)
            return self._probe_sshd_container(container)
        except Exception:
            return False

    def _ensure_sshd_started_container(self, container, name: str) -> str:
        try:
            r = container.exec_run(
                ["/bin/sh", "-c", "mkdir -p /run/sshd && /usr/sbin/sshd"],
                user="root",
            )
            exit_code = getattr(r, "exit_code", None)
            if exit_code is None:
                try:
                    exit_code = int(r[0])
                except Exception:
                    exit_code = -1
            if exit_code == 0:
                logger.info("status-cache sshd started (ensure): name=%s", name)
                return "started"
            out = ""
            try:
                out = r.output.decode("utf-8", errors="ignore") if isinstance(r.output, bytes) else str(r.output or "")
            except Exception:
                pass
            if exit_code == 127 or "not found" in (out or "").lower():
                logger.warning("status-cache sshd NOT installed in %s (exit=%s): %s", name, exit_code, out.strip()[:120])
                return "not_installed"
            logger.debug("status-cache sshd start exit=%s (transient, will retry): name=%s out=%s", exit_code, name, out.strip()[:120])
            return "transient"
        except Exception as e:
            logger.debug("status-cache sshd start attempt failed (will retry): name=%s err=%s", name, e)
            return "transient"

    def _runtime_metrics_for_name(self, name: str, gpu_runtime_by_index: dict[str, dict] | None = None) -> dict | None:
        try:
            from .. import extensions
            if extensions.docker_client is None:
                extensions.init_docker()
            container = extensions.docker_client.containers.get(name)
            if hasattr(container, "reload"):
                container.reload()
            return _container_runtime_metrics(container, gpu_runtime_by_index)
        except Exception as e:
            logger.debug("status-cache runtime metrics refresh failed: name=%s err=%s", name, e)
            return None

    def _ensure_sshd_started(self, name: str) -> str:
        try:
            return self._ensure_sshd_started_container(self._probe_client().containers.get(name), name)
        except Exception as e:
            logger.debug("status-cache sshd start attempt failed (will retry): name=%s err=%s", name, e)
            return "transient"

    @staticmethod
    def _same_probe_process(pre: DockerFact, post: DockerFact) -> bool:
        return bool(
            pre.docker_id
            and pre.started_at
            and pre.docker_id == post.docker_id
            and pre.started_at == post.started_at
        )

    def _set_hard_block_if_current(
        self,
        name: str,
        ticket: Observation,
        fact: DockerFact,
        reason: str,
        detail: str | None,
    ) -> bool:
        """probe 失败晚到：只有票仍当前且对象/进程未变时才写硬阻塞。"""
        with self._lock:
            meta = self._meta_for(name)
            if ticket.node_epoch != self.node_epoch:
                return False
            if ticket.generation != meta["generation"] or ticket.action_seq != meta["action_seq"]:
                logger.info("status-cache probe hard block dropped (superseded): name=%s", name)
                return False
            if ticket.read_seq <= meta["last_applied_read_seq"]:
                logger.info("status-cache probe hard block dropped (stale read): name=%s", name)
                return False
            entry = self._cache.get(name) or {}
            if entry.get("docker_id") and fact.docker_id and entry["docker_id"] != fact.docker_id:
                logger.info("status-cache probe hard block dropped (object changed): name=%s", name)
                return False
            ready = entry.get("ready_identity") or {}
            if fact.started_at and ready.get("started_at") and ready["started_at"] != fact.started_at:
                logger.info("status-cache probe hard block dropped (process changed): name=%s", name)
                return False
            entry = dict(entry)
            entry.update(
                {
                    "status": ContainerStatus.FAILED.value,
                    "hard_block": True,
                    "failed_reason": reason,
                    "failed_detail": detail,
                    "docker_id": fact.docker_id or entry.get("docker_id"),
                    "ready_verified": False,
                    "updated_at": _utc_iso(),
                }
            )
            entry.pop("ready_identity", None)
            entry.pop("ready_check", None)
            self._cache[name] = entry
            meta["last_applied_read_seq"] = ticket.read_seq
            return True

    def _probe_ready_once(self, name: str, gpu_runtime_by_index: dict[str, dict] | None = None) -> None:
        """对同一 Docker 进程完成“inspect→probe→同进程 post-inspect”后才 ready。"""
        ticket = self.issue_observation(name, "probe")
        try:
            client = self._probe_client()
            container = client.containers.get(name)
            reload = getattr(container, "reload", None)
            if callable(reload):
                reload()
            pre = fact_from_container(container)
        except Exception as e:
            logger.warning("status-cache probe pre-inspect failed: name=%s err=%s", name, e)
            return
        if not pre.running or pre.dead or pre.paused or pre.status in {
            "created", "restarting", "exited", "stopped", "removing"
        }:
            # 非 running 事实仍要先收敛运行态；不得对已变化对象继续 probe。
            self.publish_observed(name, ticket, pre)
            return

        if self._probe_sshd_container(container):
            try:
                post_container = client.containers.get(name)
                post_reload = getattr(post_container, "reload", None)
                if callable(post_reload):
                    post_reload()
                post = fact_from_container(post_container)
            except Exception as e:
                logger.warning("status-cache probe post-inspect failed: name=%s err=%s", name, e)
                return
            if not self._same_probe_process(pre, post) or not post.running or post.paused:
                logger.info(
                    "status-cache probe result dropped (process changed): name=%s pre=%s post=%s",
                    name,
                    pre.identity,
                    post.identity,
                )
                return
            metrics = _container_runtime_metrics(container, gpu_runtime_by_index)
            if self.publish_observed(name, ticket, post, runtime_metrics=metrics, mark_ready=True):
                logger.info("status-cache sshd probe ready: name=%s", name)
            return

        ensure_status = self._ensure_sshd_started_container(container, name)
        if ensure_status != "not_installed":
            logger.warning("status-cache sshd probe not ready, trying to start sshd: name=%s", name)
            return
        try:
            post_container = client.containers.get(name)
            post_reload = getattr(post_container, "reload", None)
            if callable(post_reload):
                post_reload()
            post = fact_from_container(post_container)
        except Exception as e:
            logger.warning("status-cache probe not-installed post-inspect failed: name=%s err=%s", name, e)
            return
        if not self._same_probe_process(pre, post):
            logger.info("status-cache not-installed result dropped (process changed): name=%s", name)
            return
        if self._set_hard_block_if_current(
            name,
            ticket,
            post,
            "sshd_not_installed",
            "container image does not provide /usr/sbin/sshd",
        ):
            logger.warning("status-cache: sshd missing in %s; marking FAILED (manual handling)", name)

    def _probe_ready_checks_once(self) -> None:
        try:
            with self._lock:
                targets = [
                    name
                    for name, e in self._cache.items()
                    if e.get("ready_check")
                    or (e.get("hard_block") and e.get("failed_reason") == "sshd_not_installed")
                ]
            gpu_runtime_by_index = None
            for name in targets:
                self._probe_ready_once(name, gpu_runtime_by_index)
        except Exception as e:
            logger.warning("status-cache probe loop interrupted (will retry): %s", e)

    def _probe_loop(self):
        while True:
            time.sleep(PROBE_INTERVAL)
            self._probe_ready_checks_once()

    def _events_loop(self):
        while True:
            try:
                client = docker.from_env()
                for event in client.events(decode=True, filters={"type": "container"}):
                    self._apply_event(event)
            except Exception as e:
                logger.warning("status-cache events loop interrupted (will retry): %s", e)
                time.sleep(2)

    def _reconcile_loop(self):
        while True:
            time.sleep(RECONCILE_INTERVAL)
            self._reconcile_once()

    def start(self):
        self._reconcile_once()
        threading.Thread(target=self._events_loop, daemon=True, name="status-cache-events").start()
        threading.Thread(target=self._reconcile_loop, daemon=True, name="status-cache-reconcile").start()
        threading.Thread(target=self._probe_loop, daemon=True, name="status-cache-probe").start()
