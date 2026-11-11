# docker_operates/event_log.py（Node 侧）
"""容器运行事件记录：采集（events 订阅捕获）+ 环形缓冲（内存最近 N 条）。

与 status_cache 的分工：
- status_cache：最新状态快照（会被覆盖）
- event_log：事件历史轨迹（started/died(exit_code)/oom/stopped...），
  供容器详情"事件时间轴"、异常告警评估、WSS 推送（Ctrl 订阅落库）使用。

雏形：内存环形缓冲；将来 Ctrl 侧落 container_events 表（WSS 推送或 HTTP 拉取）。
"""
import datetime
import logging
import threading

logger = logging.getLogger(__name__)

# 环形缓冲上限：最近 N 条事件
MAX_EVENTS = 1000


class ContainerEventLog:
    def __init__(self):
        self._events = []  # 事件列表（尾部追加，超限从头部裁剪）
        self._lock = threading.Lock()

    ##################
    # 采集
    def record(self, container_name: str, event_type: str,
               exit_code: str | int | None = None, reason: str | None = None) -> None:
        """记录一次容器事件。

        *event_type*: docker events 的 status（start/die/oom/stop/pause...）
        *exit_code*: die 事件的退出码（137 = OOM 被杀等）
        *reason*: 原因标注（如 "oom"）
        """
        with self._lock:
            self._events.append({
                "container_name": container_name,
                "event_type": event_type,
                "exit_code": exit_code,
                "reason": reason,
                "occurred_at": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S'),
            })
            if len(self._events) > MAX_EVENTS:
                del self._events[:len(self._events) - MAX_EVENTS]

    ##################
    # 读缓存
    def recent(self, container_name: str | None = None, limit: int = 50) -> list[dict]:
        """最近事件（可按容器过滤），新→旧排序。"""
        with self._lock:
            events = self._events if container_name is None else [
                e for e in self._events if e["container_name"] == container_name
            ]
            return list(reversed(events[-limit:]))

    def snapshot(self) -> list[dict]:
        with self._lock:
            return list(self._events)
