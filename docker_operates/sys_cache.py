# docker_operates/sys_cache.py（Node 侧）
"""宿主机系统快照缓存：采集与读取分离（与 status/disk/last_ssh 同构）。

sys_snapshot = 静态硬件（hostname/platform/cpu cores/内存总量/GPU 枚举/磁盘总量，
用于注册建档与漂移检测）+ 动态指标（CPU 使用率/内存占用/磁盘占用，管理面板与告警评估）。

psutil 采集（Linux 宿主机）：
- CPU 核数/使用率：psutil.cpu_count / psutil.cpu_percent
- 内存：psutil.virtual_memory
- GPU 枚举：nvidia-smi 子进程（无 GPU/无命令 → []），字段保留 vendor 便于扩展 AMD/Intel
- 磁盘：复用 disk_usage_cache.collect_machine_disk（shutil）

采集侧（collect）：后台循环按 TTL 回填缓存；
读取侧（get/snapshot）：只读缓存；静态快照（collect_static）供首连 enrollment_profile 用。
"""
import datetime
import logging
import os
import platform
import subprocess
import threading

import psutil

logger = logging.getLogger(__name__)

# 动态指标采集 TTL（秒）：管理面板展示粒度足够
SYS_SNAPSHOT_TTL_SEC = 60
# 静态硬件采集缓存时长（秒）：硬件几乎不变，避免每次首连重采
STATIC_TTL_SEC = 3600


def _cpu_info() -> dict:
    """CPU 信息：核数 + 当前使用率。"""

    try:
        usage = psutil.cpu_percent(interval=0.1)
        return {
            "cores": psutil.cpu_count(logical=True) or os.cpu_count() or 0,
            "physical_cores": psutil.cpu_count(logical=False),
            "usage_percent": round(float(usage), 1),
        }
    except Exception:
        return {"cores": os.cpu_count() or 0, "physical_cores": None, "usage_percent": None}


def _memory_info() -> dict:
    """内存：psutil.virtual_memory → GB + 使用率。"""

    try:
        mem = psutil.virtual_memory()
        return {
            "total_gb": round(mem.total / (1024 ** 3), 1),
            "used_gb": round(mem.used / (1024 ** 3), 1),
            "available_gb": round(mem.available / (1024 ** 3), 1),
            "usage_percent": round(float(mem.percent), 1),
        }
    except Exception:
        return {}


def _gpu_info() -> list[dict]:
    """GPU 枚举：nvidia-smi 查询。

    当前主路径是 NVIDIA；返回结构带 vendor 字段，后续可平滑扩展 rocm-smi/Intel。
    无 GPU 或无命令时返回 []，不影响 Node 启动。
    """
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return []
        gpus = []
        for line in r.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 3:
                continue
            try:
                idx = int(parts[0])
                mem_gb = round(float(parts[2]) / 1024, 1)
            except ValueError:
                continue
            gpus.append({"vendor": "nvidia", "index": idx, "name": parts[1], "memory_gb": mem_gb})
        return gpus
    except Exception:
        return []


class SysSnapshotCache:
    def __init__(self):
        self._snapshot = None          # 最近一次完整快照（含动态）
        self._static = None            # 静态硬件快照（低频重采）
        self._static_at = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    ##################
    # 采集侧

    def collect(self) -> dict:
        """全量采集（静态 + 动态）并回填缓存。供后台循环与首连兜底调用。"""
        snap = {
            "hostname": platform.node(),
            "platform": platform.platform(),
            "cpu": _cpu_info(),
            "memory": _memory_info(),
            "gpu": _gpu_info(),
            "disk": self._collect_disk(),
            "collected_at": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S'),
        }
        with self._lock:
            self._snapshot = snap
            # 静态字段同步维护（重采周期内保持稳定）
            if self._static is None or self._static_at is None or \
               (datetime.datetime.utcnow() - self._static_at).total_seconds() > STATIC_TTL_SEC:
                self._static = self._extract_static(snap)
                self._static_at = datetime.datetime.utcnow()
        return snap

    @staticmethod
    def _collect_disk() -> dict:
        """磁盘：复用 disk_usage_cache 的宿主机磁盘采集（shutil，一次调用）。"""
        try:
            from .. import extensions
            return extensions.disk_usage_cache.collect_machine_disk()
        except Exception as e:
            return {"error": str(e)}

    def collect_static(self) -> dict:
        """静态硬件快照（首连 enrollment_profile 用）：缓存未过期直接返回，否则采集一次。"""
        with self._lock:
            if self._static is not None and self._static_at is not None and \
               (datetime.datetime.utcnow() - self._static_at).total_seconds() <= STATIC_TTL_SEC:
                return dict(self._static)
        snap = self.collect()
        return self._extract_static(snap)

    @staticmethod
    def _extract_static(snap: dict) -> dict:
        return {
            "hostname": snap.get("hostname"),
            "platform": snap.get("platform"),
            "cpu": {"cores": (snap.get("cpu") or {}).get("cores", 0)},
            "memory": {"total_gb": (snap.get("memory") or {}).get("total_gb")},
            "gpu": snap.get("gpu", []),
            "disk": {"total_gb": (snap.get("disk") or {}).get("total_gb")},
        }

    ##################
    # 读取侧

    def get(self) -> dict | None:
        """只读最近一次完整快照；无采集 → None。"""
        with self._lock:
            return dict(self._snapshot) if self._snapshot else None

    def snapshot(self) -> dict | None:
        """list_* 读面别名（与 status/disk 读面一致）。"""
        return self.get()

    def static(self) -> dict | None:
        """只读静态快照（不触发采集）。"""
        with self._lock:
            return dict(self._static) if self._static else None

    ##################
    # 生命周期

    def start(self):
        """后台循环：按 TTL 全量采集。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()

        def _loop():
            while not self._stop.is_set():
                try:
                    self.collect()
                except Exception as e:
                    logger.warning("sys snapshot collect failed (will retry): %s", e)
                self._stop.wait(SYS_SNAPSHOT_TTL_SEC)

        self._thread = threading.Thread(target=_loop, daemon=True, name="sys-snapshot")
        self._thread.start()

    def stop(self):
        self._stop.set()
