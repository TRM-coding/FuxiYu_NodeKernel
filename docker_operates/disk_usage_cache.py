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

import docker

logger = logging.getLogger(__name__)

# bind mount 缓存 TTL（秒）：15 分钟
BIND_CACHE_TTL_SEC = 900


class DiskUsageCache:
    def __init__(self):
        self._bind_cache = {}  # bind_path -> {"bytes": int|None, "running": bool, "updated_at": datetime}
        self._lock = threading.Lock()

    ##################
    # 采集侧

    def collect_bind(self, bind_path: str) -> None:
        """后台线程体：跑 du -sb，完成后回填缓存；失败标记 running=False（下次请求重试）。"""
        try:
            r = subprocess.run(
                ["du", "-sb", bind_path],
                capture_output=True, text=True, timeout=300,  # 大目录最多等 5 分钟
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
                return
        except subprocess.TimeoutExpired:
            pass
        except Exception:
            pass
        # 失败: 标记 running=False，下次请求会重试
        with self._lock:
            entry = self._bind_cache.get(bind_path)
            if entry:
                entry["running"] = False

    def collect_overlay_rw(self, container_name: str) -> int | None:
        """overlay2 可写层：attrs SizeRw，<=0 时 df 兜底。返回字节数或 None。"""
        import docker as _docker
        try:
            from .. import extensions
            if extensions.docker_client is None:
                extensions.init_docker()
            container = extensions.docker_client.containers.get(container_name)
            size_rw = (container.attrs.get('SizeRw') or 0)
            if size_rw <= 0:
                try:
                    df = extensions.docker_client.df()
                    for c_df in df.get('Containers', []) or []:
                        names = c_df.get('Names', []) or []
                        if f"/{container_name}" in names:
                            size_rw = c_df.get('SizeRw', 0) or 0
                            break
                except Exception:
                    size_rw = 0
            return int(size_rw)
        except _docker.errors.NotFound:
            return None
        except Exception:
            return None

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

    ##################
    # 读缓存
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
            return {
                "bind_mount_bytes": None,
                "bind_mount_source": "measuring",
                "bind_mount_path": bind_path,
            }

        # 正在跑 du（entry 存在但 bytes=None 且 running=True）
        if entry.get("running"):
            return {
                "bind_mount_bytes": None,
                "bind_mount_source": "measuring",
                "bind_mount_path": bind_path,
            }

        # 上一轮 du 失败（entry 存在，bytes=None，running=False），重试
        with self._lock:
            entry["running"] = True
        threading.Thread(target=self.collect_bind, args=(bind_path,), daemon=True).start()
        return {
            "bind_mount_bytes": None,
            "bind_mount_source": "measuring",
            "bind_mount_path": bind_path,
        }

    def get_container_usage(self, container_name: str) -> dict:
        """组装单容器磁盘用量（machine_disk + overlay + bind），不抛异常。"""
        result = {
            "machine_disk": {"total_gb": 0.0, "used_gb": 0.0, "free_gb": 0.0, "percent": 0.0},
            "container": {
                "container_name": container_name,
                "overlay_rw_bytes": None,
                "bind_mount_bytes": None,
                "bind_mount_path": None,
                "bind_mount_source": "none",
                "total_bytes": 0,
            },
        }

        # --- 宿主机磁盘（实时，轻量）---
        result["machine_disk"] = self.collect_machine_disk()

        # --- 容器 ---
        import docker as _docker
        from .. import extensions
        try:
            if extensions.docker_client is None:
                extensions.init_docker()
            container = extensions.docker_client.containers.get(container_name)
        except _docker.errors.NotFound:
            result["container"]["error"] = "container_not_found"
            return result
        except Exception as e:
            result["container"]["error"] = f"docker_access_failed: {e}"
            return result

        # 第一路: overlay2 可写层（实时 attrs）
        try:
            size_rw = self.collect_overlay_rw(container_name)
            if size_rw is None:
                raise ValueError("overlay collect failed")
            result["container"]["overlay_rw_bytes"] = size_rw
        except Exception as e:
            result["container"]["overlay_rw_bytes"] = None
            result["container"]["overlay_rw_error"] = str(e)

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
                result["container"]["bind_mount_path"] = resolved["bind_mount_path"]
                result["container"]["bind_mount_bytes"] = resolved["bind_mount_bytes"]
                result["container"]["bind_mount_source"] = resolved["bind_mount_source"]
            else:
                result["container"]["bind_mount_bytes"] = None
                result["container"]["bind_mount_error"] = "no_bind_mount_for_root"
        except Exception as e:
            result["container"]["bind_mount_bytes"] = None
            result["container"]["bind_mount_error"] = str(e)

        # 总和
        rw = result["container"]["overlay_rw_bytes"] or 0
        bm = result["container"]["bind_mount_bytes"] or 0
        result["container"]["total_bytes"] = rw + bm

        def _h(b):
            return f"{b/1024/1024:.0f}M" if b >= 1024*1024 else f"{b/1024:.0f}K" if b >= 1024 else f"{b}B"
        src = result["container"].get("bind_mount_source", "none")
        logger.info("[disk-check] %s overlay=%s bind=%s bind_src=%s total=%s",
                    container_name, _h(rw), _h(bm), src, _h(rw + bm))
        return result
