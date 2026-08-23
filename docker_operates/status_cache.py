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
    "pgrep -f sshd >/dev/null 2>&1 || "
    "ps aux 2>/dev/null | grep -q [s]shd"
)

# 转换态超时兜底（秒）：后台任务异常退出时防止永久卡 ing。
# 必须宽于正常流程耗时上限（创建含镜像 pull + sshd 安装，可达数十分钟），按操作分级：
_ACTION_TTL = {
    "create": 1800,   # 镜像 pull + apt 安装 sshd，最长达 30 分钟
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

# docker events 的 status 字段 → 应用状态字符串
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


def _map_container_to_status(container) -> str:
    """docker 容器对象（c.status）→ 应用状态字符串。"""
    return _DOCKER_STATUS_TO_APP.get(getattr(container, 'status', '') or '', ContainerStatus.UNKNOWN.value)


def _map_event_to_status(event: dict) -> str:
    """docker events 事件 → 应用状态字符串（事件是"发生了什么"，不是终态）。"""
    return _EVENT_STATUS_MAP.get(str(event.get("status", "")), ContainerStatus.UNKNOWN.value)


class ContainerStatusCache:
    def __init__(self):
        self._cache = {}    # name -> {"status": str, "updated_at": str, "ready_check"?}
        self._pending = {}  # name -> {"action", "status", "error_reason", "started_at"}
        self._deleted = []  # 对账发现的消失容器名（待 WSS pusher 取走推 delete 帧）
        self._lock = threading.Lock()

    def take_deleted(self) -> list[str]:
        """取走待推送的消失容器名（取后清空）。"""
        with self._lock:
            deleted, self._deleted = self._deleted, []
        return deleted


    ##################
    # 转换态管理

    def begin_action(self, name: str, action: str, ing_status: str) -> None:
        """标记转换开始：等待返回值期间保持 ing 状态（creating/starting/stopping...）。

        *ing_status* 为等待阶段对外暴露的状态（如 'starting'）。
        """
        with self._lock:
            self._pending[name] = {
                "action": action,
                "status": ing_status,
                "error_reason": None,
                "started_at": datetime.datetime.utcnow(),
                "ttl": _ACTION_TTL.get(action, PENDING_TTL_SEC),
            }
        logger.info("status-cache begin_action: name=%s action=%s status=%s", name, action, ing_status)

    def finish_action(self, name: str, status: str | None, error_reason: str | None = None) -> None:
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
                    entry["error_reason"] = error_reason
            logger.warning("status-cache finish_action failed: name=%s reason=%s", name, error_reason)
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
        logger.info("status-cache clear_pending: name=%s", name)

    def mark_ready_check(self, name: str, status: str = ContainerStatus.STARTING.value) -> None:
        """创建完成入口：清 pending + 落 starting + 标记 sshd 就绪确认中。

        docker 层看到 running 早于 sshd 就绪，就绪确认由采集侧 probe 循环负责
        （exec 检查 :22 监听，就绪后升 online 并清标记）。
        """
        with self._lock:
            self._pending.pop(name, None)
            self._cache[name] = {
                "status": status,
                "ready_check": True,
                "updated_at": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S'),
            }
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
                            "error_reason": "operation_timeout", "timed_out": True}
            return dict(entry)

    ##################
    # 采集侧（docker 事件/对账 → 缓存回填；API 层不可调用）

    def update(self, name: str, status: str) -> None:
        """采集回填口（events/对账/转换态终态共用）：
        存在则更新、不存在则创建（填充器语义：events/对账发现新容器也要能落缓存）。"""
        with self._lock:
            old = self._cache.get(name, {}).get("status")
            self._cache[name] = {
                "status": status,
                "updated_at": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S'),
            }
        if old != status:
            logger.info("status-cache update: name=%s %s -> %s", name, old, status)

    def _apply_event(self, event: dict) -> None:
        """采集侧：单条 docker event → 状态缓存 + 事件轨迹（event_log）。"""
        actor = event.get("Actor") or {}
        attrs = actor.get("Attributes") or {}
        name = attrs.get("name")
        if not name:
            return
        status = _map_event_to_status(event)
        keep_ready_check = False
        with self._lock:
            entry = self._cache.get(name)
            if entry is not None and entry.get("ready_check") and status == ContainerStatus.ONLINE.value:
                keep_ready_check = True
        if keep_ready_check:
            logger.debug("status-cache event kept ready_check: name=%s event=%s", name, event.get("status"))
        else:
            self.update(name, status)
        # 事件轨迹：同步记录到 event_log（时间轴/告警/推送素材）
        from .. import extensions
        extensions.event_log.record(
            name,
            event.get("status", ""),
            exit_code=attrs.get("exitCode"),
            reason="oom" if event.get("status") == "oom" else None,
        )

    def _apply_container(self, container) -> None:
        """采集侧：单容器对账 → 状态缓存。

        就绪确认中的容器（ready_check）：docker running 时保持 starting（等 probe 确认 sshd），
        非 running 按终态覆盖（update 整条目覆盖，自动清标记）。
        """
        with self._lock:
            entry = self._cache.get(container.name)
            if entry is not None and entry.get("ready_check") \
                    and str(getattr(container, 'status', '') or '') == 'running':
                return  # 保持 starting + ready_check，等 probe 升 online
        self.update(container.name, _map_container_to_status(container))

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
            return {"source": "pending", "status": pending["status"],
                    "error_reason": pending.get("error_reason")}
        cached = self.get(name)
        if cached is not None:
            return {"source": "cache", "status": cached["status"],
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
            names = set(self._cache) | set(self._pending)
        result = {}
        for name in names:
            st = self.get_state(name)
            if st["source"] != "miss":
                result[name] = st
        return result

    #################
    # 循环维护

    def start(self):
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

    def _probe_loop(self):  # sshd 就绪确认：对 ready_check 容器节流探测，就绪升 online
        while True:
            time.sleep(PROBE_INTERVAL)
            try:
                with self._lock:
                    targets = [name for name, e in self._cache.items() if e.get("ready_check")]
                for name in targets:
                    if self._probe_sshd(name):
                        logger.info("status-cache sshd probe ready: name=%s", name)
                        self.update(name, ContainerStatus.ONLINE.value)  # update 整条目覆盖，自动清 ready_check
                    else:
                        logger.debug("status-cache sshd probe not ready: name=%s", name)
            except Exception as e:
                logger.warning("status-cache probe loop interrupted (will retry): %s", e)

    def _events_loop(self):  # 主通道：docker events 订阅（push）
        while True:
            try:
                client = docker.from_env()
                for event in client.events(decode=True, filters={"type": "container"}):
                    self._apply_event(event)
            except Exception as e:
                logger.warning("status-cache events loop interrupted (will retry): %s", e)
                time.sleep(2)  # docker daemon 断连重试

    def _reconcile_loop(self):  # 兜底：定时全量对账（poll）
        while True:
            time.sleep(RECONCILE_INTERVAL)
            try:
                client = docker.from_env()
                live = set()
                for c in client.containers.list(all=True):
                    live.add(c.name)
                    self._apply_container(c)
                # 消失检测（幽灵容器感知）：缓存/pending 有、docker 无 → 清缓存 + 入队 delete
                with self._lock:
                    known = set(self._cache) | set(self._pending)
                vanished = known - live
                for name in sorted(vanished):
                    with self._lock:
                        self._cache.pop(name, None)
                        self._pending.pop(name, None)
                        self._deleted.append(name)
                    logger.warning("status-cache reconcile: container %r vanished (delete queued)", name)
            except Exception as e:
                logger.warning("status-cache reconcile failed (will retry): %s", e)
