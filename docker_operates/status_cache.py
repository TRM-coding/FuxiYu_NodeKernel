# docker_operates/status_cache.py（Node 侧）
"""容器状态缓存：docker events 订阅（主）+ 定时对账（兜底）→ 内存缓存。

与 disk_usage_cache/last_ssh_cache 同构的「采集 & 读缓存」模式：
- 采集侧（update/_apply_event/_apply_container/_events_loop/_reconcile_loop）：
  docker 状态 → 缓存回填。API 层不负责任何形式的内容采集。
- 读取侧（get/get_state/snapshot）：只读缓存 + 状态语义，不做任何 IO。
- 转换态（begin_action/finish_action/clear_pending/get_pending）：独立变量字段，
  覆盖"动作已触发、返回值未到"的等待阶段。

Ctrl 侧高频轮询/订阅的是本缓存，而不是直接打 docker——
docker 状态映射到应用枚举语义与 blueprints/__init__.py 的 /container_status 对齐
（running→online 等；sshd 就绪细节由动作追踪 creation/action status 覆盖，缓存不做 exec 检查）。
"""
import datetime
import logging
import subprocess
import threading
import time

import docker

from ..constant import ContainerStatus

logger = logging.getLogger(__name__)

# 缓存对账间隔（秒）：事件流漏报时的兜底全量刷新
RECONCILE_INTERVAL = 15

# sshd 就绪探测间隔（秒）：对「创建完成、等待就绪确认」的容器做 exec probe。
# 就绪确认中的容器数量极少（创建中的那几台），10s 节流成本可控。
PROBE_INTERVAL = 10

# sshd 就绪判定：容器内 :22 监听检查（四路合并，一次 exec）
_SSHD_READY_CMD = (
    "ss -ltn 2>/dev/null | grep -q :22 || "
    "netstat -ltn 2>/dev/null | grep -q :22 || "
    "pgrep -f '[s]shd' >/dev/null 2>&1 || "
    "ps aux 2>/dev/null | grep -q [s]shd"
)

# 转换态超时兜底（秒）：后台任务异常退出时防止永久卡 ing。
# 必须宽于正常流程耗时上限（创建含镜像 build + sshd gate，可达数十分钟），按操作分级：
_ACTION_TTL = {
    "create": 1800,   # 镜像构建/创建/sshd gate，最长 30 分钟
    "start": 300,
    "stop": 300,
    "restart": 300,
    "pause": 300,
    "unpause": 300,
}
PENDING_TTL_SEC = 300  # 未知操作的兜底

# docker 终态（containers.list 的 c.status）→ 应用状态字符串
_DOCKER_STATUS_TO_APP = {
    "running": ContainerStatus.ONLINE.value,
    "exited": ContainerStatus.OFFLINE.value,
    "dead": ContainerStatus.OFFLINE.value,
    "created": ContainerStatus.STARTING.value,
    "restarting": ContainerStatus.RESTARTING.value,
    "paused": ContainerStatus.PAUSED.value,
    "removing": ContainerStatus.OFFLINE.value,
}

# docker events 的 status 字段 → 应用状态字符串（状态事件：改变容器状态）
_EVENT_STATUS_MAP = {
    "start": ContainerStatus.ONLINE.value,
    "unpause": ContainerStatus.ONLINE.value,
    "stop": ContainerStatus.OFFLINE.value,
    "die": ContainerStatus.OFFLINE.value,
    "kill": ContainerStatus.OFFLINE.value,
    "destroy": ContainerStatus.OFFLINE.value,
    "oom": ContainerStatus.OFFLINE.value,
    "pause": ContainerStatus.PAUSED.value,
    "create": ContainerStatus.STARTING.value,
    "restart": ContainerStatus.RESTARTING.value,
}

# 噪声事件（不改变容器状态，绝不落缓存/event_log；数据通路对账契约 C2）
_EVENT_NOISE = {
    "attach", "detach", "top", "exec_create", "exec_start", "exec_detach",
    "resize", "copy", "export", "import", "update", "rename", "commit",
    "health_status",
}

# 采集失败标记：对账/采集异常时置位，WSS 快照以显式 collect_error 形状发出，
# 绝不发空 dict（避免 Ctrl 误判容器全部消失；数据通路对账契约 C1）。
COLLECT_ERROR_MARKER = "collect_failed"


def _map_container_to_status(container) -> str:
    """docker 容器对象（c.status）→ 应用状态字符串。

    docker c.status 枚举 7 项全映射；未映射（理论不可达）→ unknown + warning。
    """
    raw = str(getattr(container, 'status', '') or '')
    status = _DOCKER_STATUS_TO_APP.get(raw)
    if status is None:
        logger.warning(
            "status-cache: unmapped docker container status: name=%s status=%r",
            getattr(container, 'name', '?'),
            raw,
        )
        return ContainerStatus.UNKNOWN.value
    return status


def _round_or_none(value, digits: int = 1):
    """数值展示统一保留一位；异常值不进快照。"""

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
    """从 Docker HostConfig 读取容器声明挂载的 GPU id。"""

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
    """采集宿主机 NVIDIA GPU 动态指标，按 index 建表。

    这是一轮 reconcile 共享的一次性采集；无 nvidia-smi/无 GPU 时返回空表。
    """

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
    """采集 Docker daemon 可直接提供的容器运行指标。

    Docker stats 不包含 GPU 利用率；GPU 动态值由本轮 reconcile 预采的
    nvidia-smi map 按容器 DeviceIDs 切片。
    """

    gpu_device_ids = _allocated_gpu_devices(container)
    gpu_runtime_by_index = gpu_runtime_by_index or {}
    metrics = {
        "collected_at": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S'),
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
            metrics["memory_usage_percent"] = _round_or_none((max(0, int(memory_usage) - int(cache_bytes)) / int(memory_limit)) * 100)

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
        self._cache = {}    # name -> {"status": str, "updated_at": str, "ready_check"?}
        self._pending = {}  # name -> {"action", "status", "failed_reason", "failed_detail", "started_at"}
        self._build_pending = {}  # name -> build 阶段状态；不参与 vanished 检测
        self._deleted = []  # 对账发现的消失容器名（待 WSS pusher 取走推 delete 帧）
        self._collect_error = None  # 采集失败标记（None=正常；非 None=快照发 collect_error 形状）
        self._lock = threading.Lock()

    def take_deleted(self) -> list[str]:
        """取走待推送的消失容器名（取后清空）。"""
        with self._lock:
            deleted, self._deleted = self._deleted, []
        return deleted

    def forget_container_generation(self, name: str) -> None:
        """同名容器代际失效：清理旧 cache/pending 与待推 delete。

        Ctrl 同步删除成功或同名新建开始时调用。delete 队列只表达外部消失；
        同步链路已闭环后，旧 delete 不应跨代作用到新同名容器。
        """
        with self._lock:
            self._cache.pop(name, None)
            self._pending.pop(name, None)
            self._build_pending.pop(name, None)
            self._deleted = [item for item in self._deleted if item != name]
        logger.info("status-cache forget_container_generation: name=%s", name)

    def get_collect_error(self) -> str | None:
        """读采集失败标记（None=采集正常；非 None=快照应发 collect_error 形状）。"""
        with self._lock:
            return self._collect_error


    ##################
    # 转换态管理

    def begin_build(self, name: str) -> None:
        """标记镜像构建开始。

        build 阶段还没有 Docker 容器对象，因此只进入读面，不参与 reconcile
        的 known 集合，避免构建失败被误判为 vanished/delete。
        """
        with self._lock:
            self._deleted = [item for item in self._deleted if item != name]
            self._build_pending[name] = {
                "action": "build",
                "status": ContainerStatus.BUILDING.value,
                "failed_reason": None,
                "failed_detail": None,
                "started_at": datetime.datetime.utcnow(),
                "ttl": _ACTION_TTL.get("create", PENDING_TTL_SEC),
            }
        logger.info("status-cache begin_build: name=%s status=%s", name, ContainerStatus.BUILDING.value)

    def finish_build_failed(
        self,
        name: str,
        failed_reason: str | None = None,
        failed_detail: str | None = None,
    ) -> None:
        """build 阶段失败：保留 failed 给读面，但不参与 vanished。"""
        with self._lock:
            entry = self._build_pending.get(name)
            if entry is None:
                self._build_pending[name] = {
                    "action": "build",
                    "started_at": datetime.datetime.utcnow(),
                    "ttl": _ACTION_TTL.get("create", PENDING_TTL_SEC),
                }
                entry = self._build_pending[name]
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
        """清理 build 阶段读面状态。"""
        with self._lock:
            self._build_pending.pop(name, None)
        logger.info("status-cache clear_build: name=%s", name)

    def begin_action(self, name: str, action: str, ing_status: str) -> None:
        """标记转换开始：等待返回值期间保持 ing 状态（creating/starting/stopping...）。

        *ing_status* 为等待阶段对外暴露的状态（如 'starting'）。
        """
        with self._lock:
            self._deleted = [item for item in self._deleted if item != name]
            self._build_pending.pop(name, None)
            self._pending[name] = {
                "action": action,
                "status": ing_status,
                "failed_reason": None,
                "failed_detail": None,
                "started_at": datetime.datetime.utcnow(),
                "ttl": _ACTION_TTL.get(action, PENDING_TTL_SEC),
            }
        logger.info("status-cache begin_action: name=%s action=%s status=%s", name, action, ing_status)

    def finish_action(
        self,
        name: str,
        status: str | None,
        failed_reason: str | None = None,
        failed_detail: str | None = None,
    ) -> None:
        """转换结束，按返回值更新状态。

        - status=None：仅清 pending（创建完成场景：端点 miss 后走实时+sshd 检查回填）
        - status='failed'：pending 保留为终态语义（Ctrl 读取失败原因），等下次 begin 覆盖
        - 其他终态（online/offline...）：清 pending + 回填缓存（无缝衔接空闲态）
        """
        if status == ContainerStatus.FAILED.value:
            with self._lock:
                entry = self._pending.get(name)
                if entry is not None:
                    entry["status"] = ContainerStatus.FAILED.value
                    entry["failed_reason"] = failed_reason
                    entry["failed_detail"] = failed_detail
            logger.warning(
                "status-cache finish_action failed: name=%s reason=%s detail=%s",
                name,
                failed_reason,
                failed_detail,
            )
            return
        with self._lock:
            self._pending.pop(name, None)
        if status is not None:
            self.update(name, status)
        logger.info("status-cache finish_action: name=%s status=%s", name, status)

    def clear_pending(self, name: str) -> None:
        """直接清除 pending（如删除容器后清理遗留的 failed 标记）。"""
        with self._lock:
            self._pending.pop(name, None)
            self._build_pending.pop(name, None)
        logger.info("status-cache clear_pending: name=%s", name)

    def mark_ready_check(self, name: str, status: str = ContainerStatus.STARTING.value, *, cold_verify: bool = False) -> None:
        """创建完成入口：清 pending + 落 starting + 标记 sshd 就绪确认中。

        docker 层看到 running 早于 sshd 就绪，就绪确认由采集侧 probe 循环负责
        （exec 检查 :22 监听，就绪后升 online 并清标记）。

        *cold_verify*：node 重启/首连后的冷启动复核（容器非"刚被操作启动"而是
        cache 丢失后的复查）。此时对外推送 unknown + status_source=cold_start_verify，
        由 Ctrl 落容器轴 unknown 标记（不污染最后已知状态）；probe 通过升 online 时
        update() 整条重建自然清除该标记。
        """
        with self._lock:
            old_entry = self._cache.get(name, {})
            self._pending.pop(name, None)
            entry = {
                "status": status,
                "ready_check": True,
                "updated_at": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S'),
            }
            if cold_verify:
                entry["cold_verify_since"] = entry["updated_at"]
            # 端口信息（创建后 inspect 回填）随就绪确认保留
            if old_entry.get("port") is not None:
                entry["port"] = old_entry.get("port")
            if old_entry.get("port_mappings") is not None:
                entry["port_mappings"] = old_entry.get("port_mappings")
            self._cache[name] = entry
        logger.info("status-cache mark_ready_check: name=%s status=%s ready_check=true", name, status)

    def get_pending(self, name: str) -> dict | None:
        """读转换态；等待中的 ing 态超时（PENDING_TTL_SEC）强制转 failed，防止永久卡 ing。"""
        with self._lock:
            entry = self._pending.get(name)
            if entry is None:
                return None
            if entry["status"] != ContainerStatus.FAILED.value:
                age = (datetime.datetime.utcnow() - entry["started_at"]).total_seconds()
                if age > entry.get("ttl", PENDING_TTL_SEC):
                    self._pending.pop(name, None)
                    logger.warning(
                        "status-cache pending timeout: name=%s action=%s age=%s ttl=%s",
                        name,
                        entry["action"],
                        round(age, 3),
                        entry.get("ttl", PENDING_TTL_SEC),
                    )
                    return {"action": entry["action"], "status": ContainerStatus.FAILED.value,
                            "failed_reason": "operation_timeout",
                            "failed_detail": f"operation timed out after {entry.get('ttl', PENDING_TTL_SEC)} seconds",
                            "timed_out": True}
            return dict(entry)

    def get_build_pending(self, name: str) -> dict | None:
        """读 build 转换态；超时后转 failed，但不进入 vanished 候选。"""
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
                    logger.warning(
                        "status-cache build timeout: name=%s age=%s ttl=%s",
                        name,
                        round(age, 3),
                        entry.get("ttl", PENDING_TTL_SEC),
                    )
            return dict(entry)

    ##################
    # 采集侧（docker 事件/对账 → 缓存回填；API 层不可调用）

    def update(self, name: str, status: str, runtime_metrics: dict | None = None) -> None:
        """采集回填口（events/对账/转换态终态共用）：
        存在则更新、不存在则创建（填充器语义：events/对账发现新容器也要能落缓存）。"""
        with self._lock:
            old_entry = self._cache.get(name, {})
            old = old_entry.get("status")
            entry = {
                "status": status,
                "updated_at": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S'),
            }
            if runtime_metrics is not None:
                entry["runtime_metrics"] = runtime_metrics
            elif old_entry.get("runtime_metrics") is not None:
                entry["runtime_metrics"] = old_entry.get("runtime_metrics")
            # 端口信息（创建后 inspect 回填）随状态推进保留
            if old_entry.get("port") is not None:
                entry["port"] = old_entry.get("port")
            if old_entry.get("port_mappings") is not None:
                entry["port_mappings"] = old_entry.get("port_mappings")
            self._cache[name] = entry
        if old != status:
            logger.info("status-cache update: name=%s %s -> %s", name, old, status)

    def set_port_info(self, name: str, port: int | None, port_mappings: list | None) -> None:
        """创建完成后回填端口映射（docker 自动分配结果），随快照推给 Ctrl。"""
        with self._lock:
            entry = self._cache.setdefault(name, {"status": ContainerStatus.UNKNOWN.value})
            if port is not None:
                entry["port"] = port
            if port_mappings is not None:
                entry["port_mappings"] = port_mappings
        logger.info("status-cache set_port_info: name=%s port=%s mappings=%s", name, port, port_mappings)

    def update_runtime_metrics(self, name: str, runtime_metrics: dict) -> None:
        """只更新运行指标，不改变当前状态。"""

        with self._lock:
            if name not in self._cache:
                return
            self._cache[name]["runtime_metrics"] = runtime_metrics
            self._cache[name]["updated_at"] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')

    def _apply_event(self, event: dict) -> None:
        """采集侧：单条 docker event → 状态缓存 + 事件轨迹（event_log）。

        事件按性质分类（数据通路对账契约 C2）：
        - 状态事件（start/stop/die/...）→ 更新缓存 + 记录 event_log
        - 噪声事件（attach/top/exec_*/...）→ 忽略，绝不落缓存/event_log
        - 其余不可识别 → log warning + 忽略（unknown 不再回填缓存）
        """
        actor = event.get("Actor") or {}
        attrs = actor.get("Attributes") or {}
        name = attrs.get("name")
        if not name:
            return
        event_status = str(event.get("status", ""))
        if event_status in _EVENT_NOISE:
            return
        status = _EVENT_STATUS_MAP.get(event_status)
        if status is None:
            logger.warning(
                "status-cache: unrecognized docker event ignored: name=%s event=%s",
                name,
                event_status,
            )
            return
        keep_ready_check = False
        with self._lock:
            entry = self._cache.get(name)
            if entry is not None and entry.get("ready_check") and status == ContainerStatus.ONLINE.value:
                keep_ready_check = True
        if keep_ready_check:
            logger.debug("status-cache event kept ready_check: name=%s event=%s", name, event.get("status"))
        else:
            self.update(name, status)
        # 事件轨迹：状态事件同步记录到 event_log（时间轴/告警/推送素材）
        from .. import extensions
        extensions.event_log.record(
            name,
            event.get("status", ""),
            exit_code=attrs.get("exitCode"),
            reason="oom" if event_status == "oom" else None,
        )

    def _apply_container(self, container, gpu_runtime_by_index: dict[str, dict] | None = None) -> None:
        """采集侧：单容器对账 → 状态缓存。

        - 就绪确认中（ready_check）+ docker running → 保持 starting（等 probe 确认 sshd）
        - 冷启动/新容器（缓存无条目）+ docker running → **不直接 online**：落 starting +
          ready_check，由 probe 循环验 :22（不通补启动）后才 online——崩溃恢复复合确认，
          防"docker running 但 sshd 未就绪"的过早 ONLINE（契约 C1 延伸）
        - 冷启动/新容器 + docker "created"（从未运行）→ 陈旧半成品（create 中途炸/从未启动，
          无进程会推进）→ 终态 FAILED，等人工处置
        - 已有 FAILED 条目 → 终态守卫：不被对账从 docker 状态复活（恢复路径 = 平台操作 restart/删除重建）
        - 其余：按 docker 状态覆盖（update 整条目覆盖，自动清标记）
        """
        keep_ready_check = False
        with self._lock:
            entry = self._cache.get(container.name)
            if entry is not None and entry.get("ready_check") \
                    and str(getattr(container, 'status', '') or '') == 'running':
                keep_ready_check = True
        runtime_metrics = _container_runtime_metrics(container, gpu_runtime_by_index)
        if keep_ready_check:
            self.update_runtime_metrics(container.name, runtime_metrics)
            return  # 保持 starting + ready_check，等 probe 升 online
        if entry is None:
            raw = _map_container_to_status(container)
            if raw == ContainerStatus.ONLINE.value:
                # 冷启动复核：不直接 ONLINE（见 mark_ready_check cold_verify 说明）
                self.mark_ready_check(container.name, cold_verify=True)
                self.update_runtime_metrics(container.name, runtime_metrics)
                return
            if raw == ContainerStatus.STARTING.value:
                # docker "created"：从未运行的陈旧半成品，终态 FAILED（恢复 = 删除重建/平台操作）
                logger.warning(
                    "status-cache: cold-start container %r is docker 'created' (stale half-create); marking FAILED",
                    container.name,
                )
                self.update(container.name, ContainerStatus.FAILED.value, runtime_metrics=runtime_metrics)
                return
        elif entry.get("status") == ContainerStatus.FAILED.value:
            # 终态守卫：FAILED 不被对账复活（操作/事件路径仍可恢复：restart → ready_check 门禁）
            self.update_runtime_metrics(container.name, runtime_metrics)
            return
        self.update(container.name, _map_container_to_status(container), runtime_metrics=runtime_metrics)

    ##################
    # 读缓存

    def get(self, name: str) -> dict | None:
        """读空闲态缓存（返回拷贝，防外部篡改）。"""
        with self._lock:
            entry = self._cache.get(name)
        return dict(entry) if entry is not None else None

    def get_state(self, name: str) -> dict:
        """统一读状态：pending 优先（含超时兜底），缓存兜底。

        返回: {"source": "pending"|"cache"|"miss", "status", ...}
        """
        pending = self.get_pending(name)
        if pending is not None:
            cached = self.get(name) or {}
            return {"source": "pending", "status": pending["status"],
                    "failed_reason": pending.get("failed_reason"),
                    "failed_detail": pending.get("failed_detail"),
                    "runtime_metrics": cached.get("runtime_metrics"),
                    "port": cached.get("port"),
                    "port_mappings": cached.get("port_mappings"),
                    "error_reason": pending.get("failed_reason")}
        build_pending = self.get_build_pending(name)
        if build_pending is not None:
            return {"source": "build", "status": build_pending["status"],
                    "failed_reason": build_pending.get("failed_reason"),
                    "failed_detail": build_pending.get("failed_detail"),
                    "error_reason": build_pending.get("failed_reason")}
        cached = self.get(name)
        if cached is not None:
            return {"source": "cache", "status": cached["status"],
                    "failed_reason": cached.get("failed_reason"),
                    "failed_detail": cached.get("failed_detail"),
                    "runtime_metrics": cached.get("runtime_metrics"),
                    "port": cached.get("port"),
                    "port_mappings": cached.get("port_mappings"),
                    "error_reason": cached.get("failed_reason"),
                    "cache_updated_at": cached["updated_at"]}
        return {"source": "miss"}

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._cache)

    def list_states(self) -> dict:
        """全量状态快照（读侧 list 用）：pending 优先 + cache 兜底合并。

        返回: {name: {"source": "pending"|"cache", "status", "error_reason"?, "cache_updated_at"?}}
        复用 get_state 语义（含 pending 超时兜底），缓存无条目的容器不进列表。
        """
        with self._lock:
            names = set(self._cache) | set(self._pending) | set(self._build_pending)
        result = {}
        for name in names:
            st = self.get_state(name)
            if st["source"] != "miss":
                if st["source"] == "cache":
                    with self._lock:
                        cache_entry = self._cache.get(name)
                    if cache_entry and cache_entry.get("cold_verify_since"):
                        # 冷启动复核中：对外状态 unknown + 触发源，Ctrl 落容器轴 unknown 标记
                        st["status"] = ContainerStatus.UNKNOWN.value
                        st["status_source"] = "cold_start_verify"
                        st["unknown_since"] = cache_entry["cold_verify_since"]
                result[name] = st
        return result

    #################
    # 循环维护

    def start(self):
        # warm-up（数据通路对账契约 C1）：先同步全量对账一次再起采集线程，
        # 确保 WSS 首帧不是空快照；docker daemon 挂起时对账失败 → collect_error 置位，
        # 由 pusher 以显式 collect_error 形状发出，绝不发空 dict。
        self._reconcile_once()
        threading.Thread(target=self._events_loop, daemon=True, name="status-cache-events").start()
        threading.Thread(target=self._reconcile_loop, daemon=True, name="status-cache-reconcile").start()
        threading.Thread(target=self._probe_loop, daemon=True, name="status-cache-probe").start()

    def _probe_sshd(self, name: str) -> bool:
        """exec 检查容器内 sshd 是否就绪（:22 监听）。任何异常视为未就绪。"""
        try:
            from .. import extensions
            if extensions.docker_client is None:
                extensions.init_docker()
            container = extensions.docker_client.containers.get(name)
            r = container.exec_run(["/bin/sh", "-c", _SSHD_READY_CMD], user="root")
            return getattr(r, 'exit_code', r[0]) == 0
        except Exception:
            return False

    def _runtime_metrics_for_name(self, name: str, gpu_runtime_by_index: dict[str, dict] | None = None) -> dict | None:
        """按容器名采集一次运行指标；probe 升 online 时补齐首个可用快照。"""

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
        """保障：exec 拉起容器内 sshd（无 init 容器下 /usr/sbin/sshd 是唯一可靠入口，create 同款）。

        /usr/sbin/sshd 幂等：已在运行时报错退出，无害。
        返回: "started" | "not_installed"（sshd 未安装 → 终态 FAILED，等人工处置）| "transient"（可重试）
        """
        try:
            from .. import extensions
            if extensions.docker_client is None:
                extensions.init_docker()
            container = extensions.docker_client.containers.get(name)
            # 注意：docker-py exec_run 不支持 timeout 参数（真实环境传了会 TypeError，
            # 被吞后永远走 transient，FAILED 路径失效——真 docker 集成测试抓到的坑）
            r = container.exec_run(
                ["/bin/sh", "-c", "mkdir -p /run/sshd && /usr/sbin/sshd"],
                user="root",
            )
            exit_code = getattr(r, 'exit_code', None)
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
                out = r.output.decode('utf-8', errors='ignore') if isinstance(r.output, bytes) else str(r.output or '')
            except Exception:
                pass
            if exit_code == 127 or 'not found' in (out or '').lower():
                # sshd 未安装（create 半成品/安装失败）：平台不可用终态，FAILED 等人工处置
                logger.warning(
                    "status-cache sshd NOT installed in %s (exit=%s): %s",
                    name, exit_code, out.strip()[:120],
                )
                return "not_installed"
            logger.debug(
                "status-cache sshd start exit=%s (transient, will retry): name=%s out=%s",
                exit_code, name, out.strip()[:120],
            )
            return "transient"
        except Exception as e:
            logger.debug("status-cache sshd start attempt failed (will retry): name=%s err=%s", name, e)
            return "transient"

    def _probe_ready_checks_once(self) -> None:
        """单轮就绪确认（保障）：对 ready_check 容器探测，就绪升 online；未就绪尝试拉起。

        - 就绪（:22 监听）→ update 整条目覆盖为 online，自动清 ready_check
        - 未就绪 → _ensure_sshd_started 尝试拉起（无 init 容器下 sshd 不自启的兜底），保持 starting
        """
        try:
            with self._lock:
                targets = [name for name, e in self._cache.items() if e.get("ready_check")]
            gpu_runtime_by_index = None
            for name in targets:
                if self._probe_sshd(name):
                    logger.info("status-cache sshd probe ready: name=%s", name)
                    if gpu_runtime_by_index is None:
                        gpu_runtime_by_index = _nvidia_gpu_runtime_by_index()
                    self.update(
                        name,
                        ContainerStatus.ONLINE.value,
                        runtime_metrics=self._runtime_metrics_for_name(name, gpu_runtime_by_index),
                    )
                else:
                    # 自愈（保障）：sshd 未就绪 → 尝试拉起。无 init 容器下 /usr/sbin/sshd
                    # 是唯一可靠入口（create 同款启动方式）；幂等，已在运行时报错但无害。
                    ensure_status = self._ensure_sshd_started(name)
                    if ensure_status == "not_installed":
                        # sshd 未安装 = 平台不可用终态：FAILED，等人工处置（删除重建/修复）
                        logger.warning(
                            "status-cache: sshd missing in %s; marking FAILED (manual handling)",
                            name,
                        )
                        with self._lock:
                            self._cache[name] = {
                                "status": ContainerStatus.FAILED.value,
                                "failed_reason": "sshd_not_installed",
                                "failed_detail": "container image does not provide /usr/sbin/sshd",
                                "updated_at": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S'),
                            }
                    else:
                        logger.warning("status-cache sshd probe not ready, trying to start sshd: name=%s", name)
        except Exception as e:
            logger.warning("status-cache probe loop interrupted (will retry): %s", e)

    def _probe_loop(self):  # sshd 就绪确认 + 自愈：对 ready_check 容器节流探测，就绪升 online
        while True:
            time.sleep(PROBE_INTERVAL)
            self._probe_ready_checks_once()

    def _events_loop(self):  # 主通道：docker events 订阅（push）
        while True:
            try:
                client = docker.from_env()
                for event in client.events(decode=True, filters={"type": "container"}):
                    self._apply_event(event)
            except Exception as e:
                logger.warning("status-cache events loop interrupted (will retry): %s", e)
                time.sleep(2)  # docker daemon 断连重试

    def _reconcile_once(self) -> None:
        """单次全量对账（采集兜底 + 幽灵容器感知 + collect_error 置位/清除）。

        成功 → 清除 collect_error（快照恢复正常全量）；异常 → 置位
        COLLECT_ERROR_MARKER（快照以显式 collect_error 形状发出，Ctrl 置 FAILED）。
        """
        try:
            client = docker.from_env()
            live = set()
            gpu_runtime_by_index = _nvidia_gpu_runtime_by_index()
            for c in client.containers.list(all=True):
                live.add(c.name)
                self._apply_container(c, gpu_runtime_by_index)
            # 消失检测（幽灵容器感知）：只有缓存里出现过的容器才算“已产生过”。
            # build/pending 是过渡读面，不是 Docker 容器对象存在的证据，不能触发 delete。
            with self._lock:
                known = set(self._cache)
            vanished = known - live
            for name in sorted(vanished):
                with self._lock:
                    self._cache.pop(name, None)
                    self._pending.pop(name, None)
                    self._deleted.append(name)
                logger.warning("status-cache reconcile: container %r vanished (delete queued)", name)
            with self._lock:
                self._collect_error = None
        except Exception as e:
            with self._lock:
                self._collect_error = COLLECT_ERROR_MARKER
            logger.warning("status-cache reconcile failed (collect_error set): %s", e)

    def _reconcile_loop(self):  # 兜底：定时全量对账（poll）
        while True:
            time.sleep(RECONCILE_INTERVAL)
            self._reconcile_once()
