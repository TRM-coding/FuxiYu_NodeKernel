# docker_operates/disk_usage_cache.py（Node 侧）
"""磁盘用量缓存：采集与读取分离。

采集侧（collect_*）：真正执行 IO（docker attrs / df / du -sb / shutil），回填缓存。
读取侧（get_*）：只读缓存 + 状态语义（fresh/cached/stale/measuring），
miss 或过期时仅"触发"后台采集，不在读取路径上执行采集。

overlay2 与宿主机磁盘保持实时采集（attrs 查询与 shutil 调用轻量）；
bind mount 目录 du -sb 较重（大目录可达分钟级），走缓存 + 后台刷新。
"""
import datetime
import logging
import os
import shutil
import subprocess
import threading
import time

import docker

logger = logging.getLogger(__name__)

# bind mount 缓存 TTL（秒）：15 分钟
BIND_CACHE_TTL_SEC = 900
BIND_DU_TIMEOUT_SEC = 600
# 容器级用量滚动采集 TTL（秒）与流水线步进：与 last_ssh_cache 同构的滚动自驱
DISK_SWEEP_TTL_SEC = 900
DISK_SWEEP_STEP_SLEEP = 2


class DiskUsageCache:
    def __init__(self):
        self._bind_cache = {}  # bind_path -> {"bytes": int|None, "running": bool, "updated_at": datetime}
        # name -> {"usage": {...}, "updated_at": datetime}（滚动采集回填的容器用量快照）
        self._container_cache = {}
        self._lock = threading.Lock()

    ##################
    # 采集侧

    def collect_bind(self, bind_path: str) -> None:
        """后台线程体：跑 du -sb，完成后回填缓存；失败标记 running=False（下次请求重试）。"""
        started = time.monotonic()
        try:
            r = subprocess.run(
                ["du", "-sb", bind_path],
                capture_output=True, text=True, timeout=BIND_DU_TIMEOUT_SEC,
            )
            out = r.stdout.strip()
            if out:
                size = int(out.split()[0])
                with self._lock:
                    self._bind_cache[bind_path] = {
                        "bytes": size,
                        "running": False,
                        "updated_at": datetime.datetime.utcnow(),
                    }
                logger.debug("bind du ok: path=%s bytes=%s rc=%s elapsed=%.2fs",
                             bind_path, size, r.returncode, time.monotonic() - started)
                return
            # 空 stdout = du 一个测量值都没给出（路径不可达、权限不足、或解析到的不是 GNU du）。
            # 这一支与下面的异常一样曾经静默，于是"永远 measuring"无从追查——必须留痕。
            logger.warning("bind du empty stdout: path=%s rc=%s stderr=%r",
                           bind_path, r.returncode, r.stderr.strip()[:300])
        except subprocess.TimeoutExpired:
            logger.warning("bind du timeout: path=%s timeout=%ss elapsed=%.2fs",
                           bind_path, BIND_DU_TIMEOUT_SEC, time.monotonic() - started)
        except Exception as e:
            logger.warning("bind du failed: path=%s elapsed=%.2fs err=%r",
                           bind_path, time.monotonic() - started, e)
        # 失败: 标记 running=False，下次请求会重试
        with self._lock:
            entry = self._bind_cache.get(bind_path)
            if entry:
                entry["running"] = False

    def collect_overlay_rw(self, container_name: str) -> dict:
        """overlay2 writable layer with explicit source/error state."""
        import docker as _docker
        try:
            from .. import extensions
            if extensions.docker_client is None:
                extensions.init_docker()
            container = extensions.docker_client.containers.get(container_name)
            size_rw = container.attrs.get('SizeRw')
            if size_rw is not None:
                return {"overlay_rw_bytes": int(size_rw or 0), "overlay_rw_source": "attrs"}

            try:
                api = extensions.docker_client.api
                res = api._get(api._url("/containers/{0}/json", container.id), params={"size": 1})
                detail = api._result(res, True)
                inspect_size_rw = detail.get('SizeRw')
                if inspect_size_rw is not None:
                    return {"overlay_rw_bytes": int(inspect_size_rw or 0), "overlay_rw_source": "inspect_size"}
                return {
                    "overlay_rw_bytes": None,
                    "overlay_rw_source": "missing",
                    "overlay_rw_error": "inspect_size_missing",
                }
            except Exception as e:
                return {
                    "overlay_rw_bytes": None,
                    "overlay_rw_source": "error",
                    "overlay_rw_error": str(e),
                }
        except _docker.errors.NotFound:
            return {"overlay_rw_bytes": None, "overlay_rw_source": "not_found", "overlay_rw_error": "not_found"}
        except Exception as e:
            return {"overlay_rw_bytes": None, "overlay_rw_source": "error", "overlay_rw_error": str(e)}

    def collect_machine_disk(self) -> dict:
        """宿主机磁盘（轻量实时调用）。"""
        try:
            usage = shutil.disk_usage(os.getenv("NODE_CONTAINERS_BASE", "/home"))
            total_gb = usage.total / (1024**3)
            used_gb = usage.used / (1024**3)
            free_gb = usage.free / (1024**3)
            percent = (usage.used / usage.total * 100) if usage.total > 0 else 0.0
            return {
                "total_gb": round(total_gb, 1),
                "used_gb": round(used_gb, 1),
                "free_gb": round(free_gb, 1),
                "percent": round(percent, 1),
            }
        except Exception as e:
            return {"error": str(e)}

    def collect_container(self, container_name: str) -> None:
        """滚动采集线程体：单容器 overlay + bind 用量 → 回填 _container_cache。

        bind 目录 du -sb 较重（大目录分钟级），由 get_bind 异步后台执行；
        du 完成后最迟下轮 sweep 组装进快照。滚动自驱 + TTL 节流，读侧不触发采集。
        """
        import docker as _docker
        try:
            from .. import extensions
            if extensions.docker_client is None:
                extensions.init_docker()
            container = extensions.docker_client.containers.get(container_name)

            usage = {
                "container_name": container_name,
                "overlay_rw_bytes": None,
                "overlay_rw_source": "missing",
                "bind_mount_bytes": None,
                "bind_mount_path": None,
                "bind_mount_source": "none",
                "total_bytes": None,
            }

            # 第一路: overlay2 可写层（实时 attrs，轻量）
            try:
                overlay = self.collect_overlay_rw(container_name)
                usage["overlay_rw_bytes"] = overlay.get("overlay_rw_bytes")
                usage["overlay_rw_source"] = overlay.get("overlay_rw_source", "missing")
                if overlay.get("overlay_rw_error"):
                    usage["overlay_rw_error"] = overlay["overlay_rw_error"]
            except Exception:
                usage["overlay_rw_source"] = "error"
                usage["overlay_rw_error"] = "overlay_collect_failed"

            # 第二路: bind mount 目录 (Destination == "/root")，缓存 + 异步后台 du
            try:
                mounts = container.attrs.get('Mounts', []) or []
                bind_root_source = None
                for m in mounts:
                    if m.get('Destination') == '/root' and m.get('Type') == 'bind':
                        bind_root_source = m.get('Source')
                        break
                if bind_root_source:
                    resolved = self.get_bind(bind_root_source)
                    usage["bind_mount_path"] = resolved["bind_mount_path"]
                    usage["bind_mount_bytes"] = resolved["bind_mount_bytes"]
                    usage["bind_mount_source"] = resolved["bind_mount_source"]
            except Exception:
                pass

            rw = usage["overlay_rw_bytes"]
            bm = usage["bind_mount_bytes"]
            if rw is None or (usage["bind_mount_path"] and bm is None):
                usage["total_bytes"] = None
            else:
                usage["total_bytes"] = rw + (bm or 0)

            # 与 Ctrl 侧 `skipped incomplete measurement` 一一对应：这条是那条告警的上游，
            # 两边对不上时（比如这边看着齐全、那边却说 total=None）能立刻看出是传输还是判定问题。
            logger.debug(
                "collect_container: name=%s overlay=%s/%s bind=%s/%s total=%s",
                container_name, usage["overlay_rw_bytes"], usage["overlay_rw_source"],
                usage["bind_mount_bytes"], usage["bind_mount_source"], usage["total_bytes"],
            )

            with self._lock:
                self._container_cache[container_name] = {
                    "usage": usage,
                    "updated_at": datetime.datetime.utcnow(),
                }
        except _docker.errors.NotFound:
            # 容器已消失：不写（对账侧自行清理残留条目）
            return
        except Exception as e:
            logger.warning("disk collect error for %s (will retry): %s", container_name, e)

    def _needs_collect(self, name: str) -> bool:
        with self._lock:
            entry = self._container_cache.get(name)
        if entry is None:
            return True
        age = (datetime.datetime.utcnow() - entry["updated_at"]).total_seconds()
        return age > DISK_SWEEP_TTL_SEC

    def _sweep_loop(self):  # 滚动采集流水线：持续取 TTL 到期的容器，负载恒定
        while True:
            try:
                client = docker.from_env()
                for c in client.containers.list(all=True):
                    if not self._needs_collect(c.name):
                        continue
                    self.collect_container(c.name)
                    time.sleep(DISK_SWEEP_STEP_SLEEP)
            except Exception as e:
                logger.warning("disk sweep failed (will retry): %s", e)
                time.sleep(DISK_SWEEP_STEP_SLEEP * 5)
            time.sleep(DISK_SWEEP_STEP_SLEEP)

    def start(self):
        # 启动先记下 du 解析到哪个可执行文件：PATH 里没有 du、或解析到非 GNU 实现，
        # 都会让 collect_bind 永远失败，而那些失败发生在后台线程里，事后无从追查。
        logger.info("disk cache starting: du=%s du_timeout=%ss bind_ttl=%ss sweep_ttl=%ss",
                    shutil.which("du"), BIND_DU_TIMEOUT_SEC, BIND_CACHE_TTL_SEC, DISK_SWEEP_TTL_SEC)
        threading.Thread(target=self._sweep_loop, daemon=True, name="disk-usage-sweep").start()

    ##################
    # 读缓存

    def snapshot(self) -> dict:
        """读缓存全量快照：{"machine_disk": {...}, "containers": {name: usage}}。

        machine_disk 为宿主机共享段（shutil 轻量实时）；containers 为滚动采集回填值，
        可能略旧（TTL 900s 内），读侧不做任何采集。
        """
        machine = self.collect_machine_disk()
        with self._lock:
            containers = {name: dict(e["usage"]) for name, e in self._container_cache.items()}
        return {"machine_disk": machine, "containers": containers}

    def get_bind(self, bind_path: str) -> dict:
        """读 bind mount 缓存（原 _resolve_bind_disk 语义）。

        返回: {"bind_mount_bytes", "bind_mount_source", "bind_mount_path"}
        source: fresh（TTL 内）/ cached（TTL 内但后台刷新中）/ stale（过期旧值）/ measuring（测量中）
        """
        with self._lock:
            entry = self._bind_cache.get(bind_path)

        if entry and entry.get("bytes") is not None:
            age = (datetime.datetime.utcnow() - entry["updated_at"]).total_seconds()
            if age < BIND_CACHE_TTL_SEC:
                # 新鲜缓存，直接返回
                logger.debug("bind lookup: path=%s bytes=%s source=%s age=%.1fs running=%s",
                             bind_path, entry["bytes"],
                             "fresh" if not entry.get("running") else "cached",
                             age, entry.get("running"))
                return {
                    "bind_mount_bytes": entry["bytes"],
                    "bind_mount_source": "fresh" if not entry.get("running") else "cached",
                    "bind_mount_path": bind_path,
                }
            # 过期: 返回旧值，触发后台刷新
            if not entry.get("running"):
                with self._lock:
                    entry["running"] = True
                threading.Thread(target=self.collect_bind, args=(bind_path,), daemon=True).start()
            logger.debug("bind lookup: path=%s bytes=%s source=stale age=%.1fs running=%s",
                         bind_path, entry["bytes"], age, entry.get("running"))
            return {
                "bind_mount_bytes": entry["bytes"],
                "bind_mount_source": "stale",
                "bind_mount_path": bind_path,
            }

        # 无缓存: 触发后台 du，先返回 None
        if not entry:
            with self._lock:
                self._bind_cache[bind_path] = {"bytes": None, "running": True, "updated_at": datetime.datetime.utcnow()}
            threading.Thread(target=self.collect_bind, args=(bind_path,), daemon=True).start()
            logger.debug("bind lookup: path=%s bytes=None source=measuring age=0.0s running=True (first measure triggered)",
                         bind_path)
            return {
                "bind_mount_bytes": None,
                "bind_mount_source": "measuring",
                "bind_mount_path": bind_path,
            }

        # 正在跑 du（entry 存在但 bytes=None 且 running=True）
        if entry.get("running"):
            age = (datetime.datetime.utcnow() - entry["updated_at"]).total_seconds()
            logger.debug("bind lookup: path=%s bytes=None source=measuring age=%.1fs running=True (du in flight)",
                         bind_path, age)
            return {
                "bind_mount_bytes": None,
                "bind_mount_source": "measuring",
                "bind_mount_path": bind_path,
            }

        # 上一轮 du 失败（entry 存在，bytes=None，running=False），重试
        with self._lock:
            entry["running"] = True
        threading.Thread(target=self.collect_bind, args=(bind_path,), daemon=True).start()
        age = (datetime.datetime.utcnow() - entry["updated_at"]).total_seconds()
        logger.debug("bind lookup: path=%s bytes=None source=measuring age=%.1fs running=True (retry after failed du)",
                     bind_path, age)
        return {
            "bind_mount_bytes": None,
            "bind_mount_source": "measuring",
            "bind_mount_path": bind_path,
        }
