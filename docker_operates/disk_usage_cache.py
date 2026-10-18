# docker_operates/disk_usage_cache.py（Node 侧）
"""磁盘用量缓存：轻量路径核对 + 重型 du 采集与读取分离。

业务路径是线路上的 ``bind_mount_path``。Docker Source 与
``/proc/<pid>/root/root`` 的目录对象 ``(st_dev, st_ino)`` 只在 Node 内部用于
定位真实宿主目录和调试，不进入 HTTP/WSS，不作为恢复/长期资格/冻结/删除/
清理门禁，也不作为测量有效性的前置。

线路只保留两个新增字段：``mount_path_status`` 与真实 ``measured_at``。
旧版的 Source/核对时间、测量状态/测量路径、epoch/seq 等协议不在这里出现。
读取侧只读缓存，不执行 du，也不刷新 ``measured_at``。
"""
import datetime
import logging
import os
import shutil
import subprocess
import threading
import time

import docker

from .docker_fact import fact_from_container

logger = logging.getLogger(__name__)

BIND_CACHE_TTL_SEC = 900
MEASUREMENT_MAX_AGE_SEC = BIND_CACHE_TTL_SEC
BIND_DU_TIMEOUT_SEC = 600
DISK_SWEEP_TTL_SEC = 900
DISK_SWEEP_STEP_SLEEP = 2
MOUNT_PATH_INTERVAL = 60
CLOCK_SKEW_SEC = 120

SOURCE_FRESH = "fresh"
SOURCE_CACHED = "cached"
SOURCE_STALE = "stale"
SOURCE_MEASURING = "measuring"
SOURCE_NONE = "none"


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _utc_z(value: datetime.datetime | None = None) -> str:
    if value is None:
        value = _utc_now()
    return value.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc(value: str | None) -> datetime.datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.astimezone(datetime.timezone.utc)


def _norm_path(path: str | None) -> str | None:
    if not path:
        return None
    try:
        return os.path.normcase(os.path.normpath(os.path.abspath(os.fspath(path))))
    except Exception:
        return None


def _same_path(a: str | None, b: str | None) -> bool:
    na, nb = _norm_path(a), _norm_path(b)
    return na is not None and nb is not None and na == nb


class DiskUsageCache:
    def __init__(self):
        # normalized business path -> measurement entry
        self._bind_cache = {}
        # name -> {"usage": {...}, "updated_at": datetime}
        self._container_cache = {}
        # name -> path diagnostics / verification token
        self._path_state = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # 路径核对内部工具
    # ------------------------------------------------------------------
    @staticmethod
    def _containers_base() -> str:
        return os.path.realpath(os.getenv("NODE_CONTAINERS_BASE", "/home"))

    def _allowed_path(self, path: str | None) -> bool:
        if not path:
            return False
        try:
            real = os.path.realpath(path)
            base = self._containers_base()
        except Exception:
            return False
        real_n = os.path.normcase(real)
        base_n = os.path.normcase(base)
        if real_n != base_n and not real_n.startswith(base_n + os.sep):
            return False
        return "containers" in [part.lower() for part in os.path.normpath(real).split(os.sep)]

    @staticmethod
    def _dir_identity(path: str):
        st = os.stat(path)
        return (st.st_dev, st.st_ino)

    def _candidate_parents(self, source_path: str | None, existing: str | None, last_confirmed: str | None):
        parents = []
        seen = set()

        def add(path):
            if not path:
                return
            parent = os.path.dirname(path)
            normalized = _norm_path(parent)
            if normalized is None or normalized in seen:
                return
            seen.add(normalized)
            parents.append(parent)

        for path in (source_path, existing, last_confirmed):
            if path:
                add(path)
        return [p for p in parents if self._allowed_path(p) and not os.path.islink(p)]

    def _bounded_matches(
        self,
        source_path: str | None,
        existing: str | None,
        last_confirmed: str | None,
        actual_identity,
    ) -> tuple[list[str], list[str]]:
        """只在允许父目录直接子项/已有路径内查找 actual；不递归、不遍历 symlink。"""
        matches: list[str] = []
        visited: set[str] = set()
        inspected_roots: list[str] = []

        def inspect(path: str):
            key = _norm_path(path)
            if key is None or key in visited:
                return
            visited.add(key)
            inspected_roots.append(path)
            if not self._allowed_path(path) or os.path.islink(path):
                return
            try:
                if self._dir_identity(path) == actual_identity:
                    matches.append(path)
            except Exception:
                return

        # 已有业务路径/最后确认路径本身先参与匹配。
        for path in (existing, last_confirmed):
            if path and self._allowed_path(path):
                inspect(path)

        for parent in self._candidate_parents(source_path, existing, last_confirmed):
            try:
                with os.scandir(parent) as iterator:
                    entries = list(iterator)
            except Exception:
                continue
            for entry in entries:
                try:
                    if entry.is_symlink():
                        continue
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                except Exception:
                    continue
                inspect(entry.path)
        return matches, inspected_roots

    def _verify_from_container(self, name: str, container) -> dict:
        attrs = getattr(container, "attrs", None) or {}
        state = attrs.get("State") or {}
        raw_status = str(state.get("Status") or getattr(container, "status", "") or "").lower()
        docker_id = getattr(container, "id", None)
        with self._lock:
            prior = dict(self._path_state.get(name) or {})
        existing = prior.get("bind_mount_path")
        last_confirmed = prior.get("last_confirmed_path")
        source_path = prior.get("source_path")

        def result(status, bind_path, *, reason=None, pid=None):
            return {
                "status": status,
                "bind_mount_path": bind_path,
                "source_path": source_path,
                "docker_id": docker_id,
                "pid": pid,
                "reason": reason,
            }

        if "Mounts" not in attrs:
            return result("unresolved", existing, reason="mounts_unreadable", pid=state.get("Pid"))

        mounts = attrs.get("Mounts")
        if not isinstance(mounts, list) or any(not isinstance(mount, dict) for mount in mounts):
            # Mounts 存在但不可读/形状损坏时不能推断 no_bind，只保留诊断。
            return result("unresolved", existing, reason="mounts_unreadable", pid=state.get("Pid"))
        root_bind = None
        for mount in mounts:
            if mount.get("Destination") == "/root" and mount.get("Type") == "bind":
                root_bind = mount
                break
        if root_bind is None:
            # 只有成功读取 Mounts 后才确认 no_bind；inspect 失败不会到这里。
            return result("no_bind", None, pid=state.get("Pid"))

        source_path = root_bind.get("Source") or source_path
        if raw_status in {"exited", "created", "restarting", "dead", "removing"}:
            return result("not_running", existing, reason="no_stable_pid", pid=None)
        try:
            pid = int(state.get("Pid") or 0)
        except (TypeError, ValueError):
            pid = 0
        if pid <= 0:
            return result("not_running", existing, reason="no_stable_pid", pid=None)

        actual_path = f"/proc/{pid}/root/root"
        try:
            actual_identity = self._dir_identity(actual_path)
        except Exception as e:
            logger.info("disk mount actual unreadable: name=%s pid=%s err=%s", name, pid, e)
            return result("unresolved", existing, reason="actual_unreadable", pid=pid)

        # 1) Source 可解析、在允许根内且与 actual 一致；/proc 临时路径绝不返回。
        source_is_proc = str(source_path or "").replace("\\", "/").startswith("/proc/")
        if (
            source_path
            and not source_is_proc
            and self._allowed_path(source_path)
            and os.path.isdir(source_path)
            and not os.path.islink(source_path)
        ):
            try:
                if self._dir_identity(source_path) == actual_identity:
                    return result("resolved", source_path, pid=pid)
            except Exception:
                pass

        # 2) Source 缺失/错位：在允许父目录直接子项内唯一定位。
        matches, inspected = self._bounded_matches(
            source_path,
            existing,
            last_confirmed,
            actual_identity,
        )
        logger.debug(
            "disk mount bounded search: name=%s source=%s existing=%s matches=%s inspected=%s",
            name,
            source_path,
            existing,
            matches,
            inspected[:20],
        )
        unique = []
        seen = set()
        for path in matches:
            key = _norm_path(path)
            if key not in seen:
                seen.add(key)
                unique.append(path)
        if len(unique) == 1:
            return result("resolved", unique[0], pid=pid)
        if len(unique) > 1:
            return result("unresolved", existing, reason="ambiguous_candidates", pid=pid)
        return result("unresolved", existing, reason="no_candidate", pid=pid)

    @staticmethod
    def _active_identity(container) -> dict | None:
        try:
            reload = getattr(container, "reload", None)
            if callable(reload):
                reload()
            fact = fact_from_container(container)
            return {
                "docker_id": fact.docker_id,
                "pid": fact.pid,
                "started_at": fact.started_at,
                "status": fact.status,
            }
        except Exception:
            return None

    def _fresh_active_identity(self, name: str, client=None) -> dict | None:
        """按名称新鲜获取当前 Docker 对象/PID，供发布前复核。"""
        try:
            client = client or _docker_client()
            container = client.containers.get(name)
            return self._active_identity(container)
        except Exception as e:
            logger.info("disk path fresh active check failed: name=%s err=%s", name, e)
            return None

    @staticmethod
    def _same_active_identity(start: dict | None, current: dict | None) -> bool:
        if not start or not current:
            return False
        if start.get("docker_id") != current.get("docker_id"):
            return False
        if start.get("pid") != current.get("pid"):
            return False
        start_started = start.get("started_at")
        current_started = current.get("started_at")
        if start_started and current_started and start_started != current_started:
            return False
        return True

    def _update_unresolved_state(self, name: str, check_seq: int, reason: str) -> dict | None:
        with self._lock:
            state = self._path_state.setdefault(name, {})
            if state.get("check_seq") != check_seq:
                return None
            state["mount_path_status"] = "unresolved"
            logger.info("disk path unresolved: name=%s reason=%s", name, reason)
            return {
                "status": "unresolved",
                "bind_mount_path": state.get("bind_mount_path"),
                "source_path": state.get("source_path"),
                "docker_id": state.get("docker_id"),
                "pid": state.get("pid"),
                "reason": reason,
                "path_version": state.get("path_version") or 0,
            }

    def verify_mount_path(self, name: str, container=None, *, client=None) -> dict | None:
        """一次轻量路径核对；发布前按名复核当前 DockerID/PID，旧核对晚回丢弃。"""
        with self._lock:
            state = self._path_state.setdefault(name, {})
            state["check_seq"] = int(state.get("check_seq") or 0) + 1
            check_seq = state["check_seq"]
            prior_version = int(state.get("path_version") or 0)

        if container is None:
            try:
                client = client or _docker_client()
                container = client.containers.get(name)
                reload = getattr(container, "reload", None)
                if callable(reload):
                    reload()
            except Exception as e:
                logger.info("disk path inspect failed: name=%s err=%s", name, e)
                return self._update_unresolved_state(name, check_seq, "inspect_failed")

        # 核对开始时的活跃对象/进程身份；文件系统候选定位期间可能被外部换代。
        start_identity = self._active_identity(container)
        if start_identity is None:
            logger.info("disk path result dropped (start identity unavailable): name=%s", name)
            return self._update_unresolved_state(name, check_seq, "identity_unreadable")

        verification = self._verify_from_container(name, container)

        # 发布前按名新鲜复核：Docker 同名换代或同 ID 新 PID 时旧结果必须丢弃。
        fresh_identity = self._fresh_active_identity(name, client=client)
        if not self._same_active_identity(start_identity, fresh_identity):
            logger.info(
                "disk path result dropped (active object/process changed): name=%s start=%s fresh=%s",
                name,
                start_identity,
                fresh_identity,
            )
            return None

        path_changed = False
        with self._lock:
            state = self._path_state.setdefault(name, {})
            # 旧定位晚回：fresh 复核后又出现新核对 → 再 CAS 一次。
            if state.get("check_seq") != check_seq:
                logger.info("disk path result dropped (newer check): name=%s", name)
                return None
            observed_docker_id = verification.get("docker_id")
            if observed_docker_id:
                state["docker_id"] = observed_docker_id
            state["pid"] = verification.get("pid")
            old_business = state.get("bind_mount_path")
            old_status = state.get("mount_path_status")
            state["mount_path_status"] = verification["status"]
            source = verification.get("source_path")
            if source:
                state["source_path"] = source
            elif verification["status"] == "no_bind":
                state["source_path"] = None

            if verification["status"] == "resolved":
                new_business = verification["bind_mount_path"]
                state["bind_mount_path"] = new_business
                state["last_confirmed_path"] = new_business
                path_changed = not _same_path(old_business, new_business)
                if path_changed:
                    state["path_version"] = int(state.get("path_version") or 0) + 1
                    self._invalidate_usage_locked(name, new_business, verification["status"])
            elif verification["status"] == "no_bind":
                path_changed = old_business is not None
                if path_changed:
                    state["path_version"] = int(state.get("path_version") or 0) + 1
                    self._invalidate_usage_locked(name, None, "no_bind")
                state["bind_mount_path"] = None
            else:
                # unresolved/not_running 保留已有/最后确认业务路径。
                state["bind_mount_path"] = old_business
                if old_status != verification["status"]:
                    self._refresh_usage_path_status_locked(name, verification["status"])

            verification["bind_mount_path"] = state.get("bind_mount_path")
            verification["path_version"] = state.get("path_version") or 0

        if verification["status"] == "resolved" and verification.get("bind_mount_path"):
            self._ensure_bind_measure(
                verification["bind_mount_path"],
                name,
                force=path_changed or int(verification.get("path_version") or 0) != prior_version,
            )
        return verification

    def _invalidate_usage_locked(self, name: str, path: str | None, status: str) -> None:
        """路径变化/清空时不得把旧路径 bytes 贴到新路径；不刷新真实测量时间。"""
        entry = self._container_cache.get(name)
        if entry is None:
            return
        usage = dict(entry.get("usage") or {})
        usage["bind_mount_path"] = path
        usage["mount_path_status"] = status
        usage["bind_mount_bytes"] = None
        usage["total_bytes"] = None
        usage["bind_mount_source"] = SOURCE_NONE if path is None else SOURCE_MEASURING
        usage["measured_at"] = None
        # 路径诊断不是测量失败：no_bind/路径变化都不得写成 du 错误。
        usage["error"] = None
        entry["usage"] = usage

    def _refresh_usage_path_status_locked(self, name: str, status: str) -> None:
        entry = self._container_cache.get(name)
        if entry is None:
            return
        usage = dict(entry.get("usage") or {})
        usage["mount_path_status"] = status
        entry["usage"] = usage

    # ------------------------------------------------------------------
    # 测量缓存
    # ------------------------------------------------------------------
    def _bind_entry_locked(self, path: str) -> dict:
        entry = self._bind_cache.get(path)
        if entry is None:
            entry = {
                "bytes": None,
                "status": "unverified",
                "reason": None,
                "measured_at": None,
                "running": False,
                "request_id": 0,
                "updated_at": None,
            }
            self._bind_cache[path] = entry
        return entry

    def _measurement_age(self, entry: dict) -> float | None:
        measured_at = _parse_utc(entry.get("measured_at"))
        if measured_at is None:
            return None
        return (_utc_now() - measured_at).total_seconds()

    def _ensure_bind_measure(self, path: str, container_name: str | None = None, *, force: bool = False) -> None:
        normalized = _norm_path(path)
        if not normalized:
            return
        with self._lock:
            entry = self._bind_entry_locked(normalized)
            if entry.get("running"):
                return
            if not force and entry.get("status") == "ok":
                age = self._measurement_age(entry)
                if age is not None and age < BIND_CACHE_TTL_SEC:
                    return
            entry["request_id"] = int(entry.get("request_id") or 0) + 1
            request_id = entry["request_id"]
            entry["running"] = True
            entry["status"] = "measuring"
            entry["reason"] = None
        threading.Thread(
            target=self.collect_bind,
            args=(normalized, container_name, request_id),
            daemon=True,
            name=f"disk-bind-{container_name or 'unknown'}",
        ).start()

    def collect_bind(self, bind_path: str, container_name: str | None = None, request_id: int | None = None) -> None:
        """后台线程体：跑 du -sb，完成后按请求序号回填。失败不当 0。"""
        who = container_name or "-"
        normalized = _norm_path(bind_path)
        if not normalized:
            return
        if request_id is None:
            with self._lock:
                entry = self._bind_entry_locked(normalized)
                if not entry.get("running"):
                    entry["request_id"] = int(entry.get("request_id") or 0) + 1
                    entry["running"] = True
                    entry["status"] = "measuring"
                request_id = entry["request_id"]
        started = time.monotonic()
        result = {
            "bytes": None,
            "status": "error",
            "reason": None,
            "measured_at": None,
        }
        try:
            r = subprocess.run(
                ["du", "-sb", normalized],
                capture_output=True,
                text=True,
                timeout=BIND_DU_TIMEOUT_SEC,
            )
            out = (r.stdout or "").strip()
            if r.returncode != 0:
                result["reason"] = "non_zero_exit"
                logger.warning(
                    "bind du non-zero: container=%s path=%s rc=%s stderr=%r",
                    who,
                    normalized,
                    r.returncode,
                    (r.stderr or "").strip()[:300],
                )
            elif not out:
                result["reason"] = "empty_output"
                logger.warning("bind du empty stdout: container=%s path=%s", who, normalized)
            else:
                try:
                    size = int(out.split()[0])
                except (ValueError, IndexError):
                    result["reason"] = "parse_error"
                    logger.warning("bind du unparsable output: container=%s path=%s out=%r", who, normalized, out[:120])
                else:
                    result["bytes"] = size
                    result["status"] = "ok"
                    result["measured_at"] = _utc_z()
                    logger.debug(
                        "bind du ok: container=%s path=%s bytes=%s elapsed=%.2fs",
                        who,
                        normalized,
                        size,
                        time.monotonic() - started,
                    )
        except subprocess.TimeoutExpired:
            result["reason"] = "timeout"
            logger.warning("bind du timeout: container=%s path=%s timeout=%ss", who, normalized, BIND_DU_TIMEOUT_SEC)
        except FileNotFoundError as e:
            result["reason"] = "du_unavailable"
            logger.warning("bind du unavailable: container=%s path=%s err=%r", who, normalized, e)
        except PermissionError as e:
            result["reason"] = "permission_denied"
            logger.warning("bind du permission denied: container=%s path=%s err=%r", who, normalized, e)
        except subprocess.CalledProcessError as e:
            result["reason"] = "non_zero_exit"
            logger.warning("bind du failed: container=%s path=%s err=%r", who, normalized, e)
        except Exception as e:
            result["reason"] = "du_failed"
            logger.warning("bind du failed: container=%s path=%s err=%r", who, normalized, e)

        with self._lock:
            entry = self._bind_entry_locked(normalized)
            if entry.get("request_id") != request_id:
                logger.info("bind du result dropped (superseded request): path=%s", normalized)
                return
            entry["running"] = False
            entry["updated_at"] = _utc_now()
            if result["status"] == "ok":
                entry["bytes"] = result["bytes"]
                entry["status"] = "ok"
                entry["reason"] = None
                entry["measured_at"] = result["measured_at"]
            else:
                # 失败不更新成功 bytes/measured_at；最后成功值只在内部留作诊断。
                entry["status"] = "error"
                entry["reason"] = result["reason"]

    def _measurement_for_path(self, name: str, path: str, *, trigger: bool = True) -> dict:
        """读取/按需触发某业务路径的 du；只返回当前成功样本。"""
        normalized = _norm_path(path)
        if not normalized:
            return {
                "bind_mount_bytes": None,
                "bind_mount_source": SOURCE_NONE,
                "bind_mount_path": path,
                "measured_at": None,
                "error": "no_business_path",
            }
        with self._lock:
            entry = self._bind_entry_locked(normalized)
            running = bool(entry.get("running"))
            status = entry.get("status") or "unverified"
            bytes_ = entry.get("bytes")
            measured_at = entry.get("measured_at")
            reason = entry.get("reason")
            age = self._measurement_age(entry)
        previous_status = status
        if not running and trigger and (status != "ok" or age is None or age >= BIND_CACHE_TTL_SEC):
            self._ensure_bind_measure(normalized, name)
            running = True

        if previous_status == "error":
            # 一次失败必须是当前事实，不能被“已触发重试”掩盖；重试结果下一次采集再发布。
            return {
                "bind_mount_bytes": None,
                "bind_mount_source": SOURCE_NONE,
                "bind_mount_path": path,
                "measured_at": None,
                "error": reason or "du_failed",
            }
        if running:
            return {
                "bind_mount_bytes": None,
                "bind_mount_source": SOURCE_MEASURING,
                "bind_mount_path": path,
                "measured_at": None,
                "error": None,
            }
        if status == "ok" and age is not None and age < BIND_CACHE_TTL_SEC:
            return {
                "bind_mount_bytes": bytes_,
                "bind_mount_source": SOURCE_FRESH,
                "bind_mount_path": path,
                "measured_at": measured_at,
                "error": None,
            }
        if status == "ok":
            return {
                "bind_mount_bytes": None,
                "bind_mount_source": SOURCE_STALE,
                "bind_mount_path": path,
                "measured_at": None,
                "error": "measurement_expired",
            }
        if status == "error":
            return {
                "bind_mount_bytes": None,
                "bind_mount_source": SOURCE_NONE,
                "bind_mount_path": path,
                "measured_at": None,
                "error": reason or "du_failed",
            }
        return {
            "bind_mount_bytes": None,
            "bind_mount_source": SOURCE_MEASURING if trigger else SOURCE_NONE,
            "bind_mount_path": path,
            "measured_at": None,
            "error": None,
        }

    def collect_overlay_rw(self, container_name: str) -> dict:
        import docker as _docker
        try:
            client = _docker_client()
            container = client.containers.get(container_name)
            size_rw = container.attrs.get("SizeRw")
            if size_rw is not None:
                return {"overlay_rw_bytes": int(size_rw or 0), "overlay_rw_source": "attrs"}
            try:
                api = client.api
                res = api._get(api._url("/containers/{0}/json", container.id), params={"size": 1})
                detail = api._result(res, True)
                inspect_size_rw = detail.get("SizeRw")
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

    def _compose_usage(
        self,
        name: str,
        container,
        verification: dict,
        overlay: dict,
        checked_at: datetime.datetime,
    ) -> dict:
        status = verification.get("status")
        bind_path = verification.get("bind_mount_path")
        overlay_bytes = overlay.get("overlay_rw_bytes")
        overlay_at = checked_at

        usage = {
            "container_name": name,
            "overlay_rw_bytes": overlay_bytes,
            "bind_mount_bytes": None,
            "bind_mount_path": bind_path,
            "mount_path_status": status,
            "bind_mount_source": SOURCE_NONE,
            "total_bytes": None,
            "error": None,
            "measured_at": None,
        }
        if overlay.get("overlay_rw_error"):
            usage["error"] = overlay["overlay_rw_error"]

        if status == "no_bind":
            usage["bind_mount_path"] = None
            usage["bind_mount_source"] = SOURCE_NONE
            if overlay_bytes is None:
                usage["error"] = overlay.get("overlay_rw_error") or "overlay_missing"
            else:
                usage["total_bytes"] = int(overlay_bytes)
                usage["measured_at"] = _utc_z(overlay_at)
                usage["error"] = None
            return usage

        if not bind_path:
            usage["bind_mount_path"] = None
            usage["error"] = usage.get("error") or "no_business_path"
            return usage

        measurement = self._measurement_for_path(name, bind_path)
        usage["bind_mount_bytes"] = measurement["bind_mount_bytes"]
        usage["bind_mount_source"] = measurement["bind_mount_source"]
        usage["measured_at"] = measurement["measured_at"]
        if measurement.get("error"):
            usage["error"] = measurement["error"]
        if overlay_bytes is None:
            usage["bind_mount_bytes"] = None
            usage["total_bytes"] = None
            usage["measured_at"] = None
            usage["error"] = overlay.get("overlay_rw_error") or "overlay_missing"
            return usage
        if measurement["bind_mount_bytes"] is None:
            usage["total_bytes"] = None
            usage["measured_at"] = None
            return usage

        bind_at = _parse_utc(measurement.get("measured_at"))
        if bind_at is None:
            usage["total_bytes"] = None
            usage["bind_mount_bytes"] = None
            usage["measured_at"] = None
            usage["error"] = "measurement_unverified"
            return usage
        earlier = bind_at if bind_at < overlay_at else overlay_at
        usage["total_bytes"] = int(overlay_bytes) + int(measurement["bind_mount_bytes"])
        usage["measured_at"] = _utc_z(earlier)
        usage["error"] = None
        return usage

    def _usage_measurement_valid(self, usage: dict, now: datetime.datetime) -> bool:
        if usage.get("overlay_rw_bytes") is None:
            return False
        measured_at = _parse_utc(usage.get("measured_at"))
        if measured_at is None:
            return False
        if measured_at > now + datetime.timedelta(seconds=CLOCK_SKEW_SEC):
            return False
        if (now - measured_at).total_seconds() > MEASUREMENT_MAX_AGE_SEC:
            return False
        total = usage.get("total_bytes")
        if total is None:
            return False
        if usage.get("mount_path_status") == "no_bind":
            if usage.get("bind_mount_path") is not None or usage.get("bind_mount_bytes") is not None:
                return False
            return int(total) == int(usage["overlay_rw_bytes"])
        bind_path = usage.get("bind_mount_path")
        bind_bytes = usage.get("bind_mount_bytes")
        if not bind_path or bind_bytes is None:
            return False
        if int(total) != int(usage["overlay_rw_bytes"]) + int(bind_bytes):
            return False
        return True

    def _effective_usage_for_read(self, raw: dict, now: datetime.datetime | None = None) -> dict:
        """读面只做有效期判断；不触发 du，不改变 measured_at。"""
        effective = dict(raw)
        now = now or _utc_now()
        if self._usage_measurement_valid(effective, now):
            return effective
        measured_at = _parse_utc(effective.get("measured_at"))
        if measured_at is not None and measured_at > now + datetime.timedelta(seconds=CLOCK_SKEW_SEC):
            effective["error"] = "measurement_clock_skew"
        elif measured_at is not None and (now - measured_at).total_seconds() > MEASUREMENT_MAX_AGE_SEC:
            effective["error"] = "measurement_expired"
            effective["bind_mount_source"] = SOURCE_STALE
        elif effective.get("total_bytes") is not None:
            effective["error"] = effective.get("error") or "measurement_invalid"
        effective["total_bytes"] = None
        # 没有当前有效组合时，不得用旧 bind 字节冒充当前值。
        effective["bind_mount_bytes"] = None
        return effective

    def collect_container(self, container_name: str) -> None:
        """滚动采集线程体：路径核对 + overlay + 按业务路径 bind du → 回填。"""
        import docker as _docker
        try:
            client = _docker_client()
            container = client.containers.get(container_name)
            reload = getattr(container, "reload", None)
            if callable(reload):
                reload()
            verification = self.verify_mount_path(container_name, container=container, client=client)
            if verification is None:
                return
            with self._lock:
                state_after_verify = dict(self._path_state.get(container_name) or {})

            try:
                size_rw = container.attrs.get("SizeRw")
            except Exception:
                size_rw = None
            if size_rw is not None:
                overlay = {"overlay_rw_bytes": int(size_rw or 0), "overlay_rw_source": "attrs"}
            else:
                overlay = self.collect_overlay_rw(container_name)

            checked_at = _utc_now()
            usage = self._compose_usage(container_name, container, verification, overlay, checked_at)

            with self._lock:
                state = self._path_state.get(container_name) or {}
                current_path = state.get("bind_mount_path")
                verified_path = verification.get("bind_mount_path")
                same_path = (current_path is None and verified_path is None) or _same_path(
                    current_path, verified_path
                )
                # 采集期间路径已变化/核对已换代：旧样本不得挂到新业务路径。
                if (state.get("path_version") or 0) != (state_after_verify.get("path_version") or 0) or not same_path:
                    usage["bind_mount_path"] = current_path
                    usage["mount_path_status"] = state.get("mount_path_status") or "unresolved"
                    usage["bind_mount_bytes"] = None
                    usage["bind_mount_source"] = SOURCE_NONE if current_path is None else SOURCE_MEASURING
                    usage["total_bytes"] = None
                    usage["measured_at"] = None
                    usage["error"] = None
                self._container_cache[container_name] = {"usage": usage, "updated_at": checked_at}
            logger.debug(
                "collect_container: name=%s path=%s path_status=%s overlay=%s bind=%s/%s total=%s error=%s",
                container_name,
                usage.get("bind_mount_path"),
                usage.get("mount_path_status"),
                usage.get("overlay_rw_bytes"),
                usage.get("bind_mount_bytes"),
                usage.get("bind_mount_source"),
                usage.get("total_bytes"),
                usage.get("error"),
            )
        except _docker.errors.NotFound:
            return
        except Exception as e:
            logger.warning("disk collect error for %s (will retry): %s", container_name, e)

    def _needs_collect(self, name: str) -> bool:
        with self._lock:
            entry = self._container_cache.get(name)
        if entry is None:
            return True
        age = (_utc_now() - entry["updated_at"]).total_seconds()
        return age > DISK_SWEEP_TTL_SEC

    def _sweep_loop(self):
        while True:
            try:
                client = _docker_client()
                for c in client.containers.list(all=True):
                    if not self._needs_collect(c.name):
                        continue
                    self.collect_container(c.name)
                    time.sleep(DISK_SWEEP_STEP_SLEEP)
            except Exception as e:
                logger.warning("disk sweep failed (will retry): %s", e)
                time.sleep(DISK_SWEEP_STEP_SLEEP * 5)
            time.sleep(DISK_SWEEP_STEP_SLEEP)

    def _mount_loop(self):
        while True:
            time.sleep(MOUNT_PATH_INTERVAL)
            try:
                client = _docker_client()
                for c in client.containers.list(all=True):
                    self.verify_mount_path(c.name)
            except Exception as e:
                logger.warning("disk mount verify loop failed (will retry): %s", e)

    def start(self):
        logger.info(
            "disk cache starting: du=%s du_timeout=%ss bind_ttl=%ss sweep_ttl=%ss",
            shutil.which("du"),
            BIND_DU_TIMEOUT_SEC,
            BIND_CACHE_TTL_SEC,
            DISK_SWEEP_TTL_SEC,
        )
        threading.Thread(target=self._sweep_loop, daemon=True, name="disk-usage-sweep").start()
        threading.Thread(target=self._mount_loop, daemon=True, name="disk-mount-verify").start()

    # ------------------------------------------------------------------
    # 读缓存
    # ------------------------------------------------------------------
    def snapshot(self) -> dict:
        """只读快照；路径变更/过期样本不把旧 bind 字节贴到当前路径。"""
        machine = self.collect_machine_disk()
        now = _utc_now()
        with self._lock:
            containers = {}
            for name, entry in self._container_cache.items():
                raw = dict(entry.get("usage") or {})
                state = self._path_state.get(name) or {}
                current_path = state.get("bind_mount_path")
                current_status = state.get("mount_path_status") or "unresolved"
                cached_path = raw.get("bind_mount_path")
                if not ((current_path is None and cached_path is None) or _same_path(current_path, cached_path)):
                    raw["bind_mount_path"] = current_path
                    raw["mount_path_status"] = current_status
                    raw["bind_mount_bytes"] = None
                    raw["bind_mount_source"] = SOURCE_NONE if current_path is None else SOURCE_MEASURING
                    raw["total_bytes"] = None
                    raw["measured_at"] = None
                    raw["error"] = None
                else:
                    raw["mount_path_status"] = current_status
                effective = self._effective_usage_for_read(raw, now)
                containers[name] = effective
        return {"machine_disk": machine, "containers": containers}

    def get_bind(self, bind_path: str, container_name: str | None = None) -> dict:
        """读 bind 测量（兼容旧接口）；读取会触发缺失/过期测量但不改变读取时间。"""
        result = self._measurement_for_path(container_name or "-", bind_path)
        return {
            "bind_mount_bytes": result["bind_mount_bytes"],
            "bind_mount_source": result["bind_mount_source"],
            "bind_mount_path": result["bind_mount_path"],
            "measured_at": result["measured_at"],
            "error": result["error"],
        }


def _docker_client():
    from .. import extensions

    if extensions.docker_client is None:
        extensions.init_docker()
    return extensions.docker_client
