# docker_operates/last_ssh_cache.py（Node 侧）
"""SSH 登录时间缓存：采集与读取分离。

与 status_cache/disk_usage_cache 同构的「采集 & 读缓存」模式：
- 采集侧（collect / _sweep_loop）：滚动流水线，TTL 节流下逐个 exec 采集，
  回填缓存。SSH 登录时间在容器内部（wtmp / auth.log），docker 事件观测不到，
  采集只能 exec_run——所以采集天然是轮询，这里做滚动节流而不是消除 exec。
- 读取侧（get）：只读缓存，miss 时返回 None（Ctrl 侧「not found 不覆盖旧值」，
  保持 DB 旧值，与迁移前行为一致）。

采集节流不影响正确性：Ctrl 侧清退判定是"天"级粒度，5 分钟 TTL 余量两个数量级。
"""
import datetime
import logging
import threading
import time

import docker

logger = logging.getLogger(__name__)

# 读取侧新鲜度判定 / 采集侧重采间隔（秒）：5 分钟
LAST_SSH_TTL_SEC = 300
# 滚动流水线步进（秒）：每容器之间错开 exec，避免突发波峰
SWEEP_STEP_SLEEP = 2

# 容器内查询脚本：优先 `last`（权威登录会话），回退 sshd 日志。
# TZ=UTC 强制 last 输出 UTC 时间，Ctrl 侧全程 UTC 无需转换。
_SSH_QUERY_CMD = r"""
if command -v last >/dev/null 2>&1; then
  v="$(TZ=UTC last -w -i 2>/dev/null | awk '$1!="wtmp" && $1!="reboot" && $1!="btmp" && $1!="runlevel" {print; exit}')"
  if [ -n "$v" ]; then
    echo "$v"
    exit 0
  fi
fi

if [ -f /var/log/auth.log ]; then
  line="$(grep -E 'sshd.*(Accepted|session opened)' /var/log/auth.log | tail -n 1)"
elif [ -f /var/log/secure ]; then
  line="$(grep -E 'sshd.*(Accepted|session opened)' /var/log/secure | tail -n 1)"
else
  line=""
fi
echo "$line"
"""


class LastSshCache:
    def __init__(self):
        # name -> {"value": str|None, "updated_at": datetime}
        # value=None 表示「采集过、确认无登录记录」；无条目 = 从未采集（miss）
        self._cache = {}
        self._lock = threading.Lock()

    ##################
    # 采集侧

    def collect(self, container_name: str) -> None:
        """采集线程体：exec 查询容器内登录时间，回填缓存。

        非运行态容器跳过（exec 会 409），不采不写——保持旧值/miss，
        Ctrl 侧收 None 后继续用 DB 旧值，与迁移前语义一致。
        exec 失败同样不写（保留旧值，下轮 sweep 重试）。
        """
        try:
            from .. import extensions
            if extensions.docker_client is None:
                extensions.init_docker()
            container = extensions.docker_client.containers.get(container_name)

            # 容器未运行则跳过 exec_run，避免等待 Docker 返回 409 耗时
            try:
                state = (container.attrs.get('State') or {}).get('Status', '')
            except Exception:
                state = ''
            if str(state).lower() != 'running':
                return

            result = container.exec_run(["/bin/sh", "-c", _SSH_QUERY_CMD], user="root")
            output = result.output.decode("utf-8", errors="ignore").strip()
            if hasattr(result, "exit_code") and result.exit_code != 0:
                logger.warning("last-ssh collect failed for %s: exit=%s, output=%s",
                               container_name, result.exit_code, output)
                return
            with self._lock:
                self._cache[container_name] = {
                    "value": output or None,
                    "updated_at": datetime.datetime.utcnow(),
                }
        except docker.errors.NotFound:
            # 容器已消失：不写（Ctrl 侧维持 DB 旧值，由对账/清退处理）
            return
        except Exception as e:
            logger.warning("last-ssh collect error for %s (will retry): %s", container_name, e)

    def _needs_collect(self, name: str) -> bool:
        with self._lock:
            entry = self._cache.get(name)
        if entry is None:
            return True
        age = (datetime.datetime.utcnow() - entry["updated_at"]).total_seconds()
        return age > LAST_SSH_TTL_SEC

    def _sweep_loop(self):  # 滚动采集流水线：持续取 TTL 到期的运行容器，负载恒定
        while True:
            try:
                client = docker.from_env()
                for c in client.containers.list(filters={"status": "running"}):
                    if not self._needs_collect(c.name):
                        continue
                    self.collect(c.name)
                    time.sleep(SWEEP_STEP_SLEEP)
            except Exception as e:
                logger.warning("last-ssh sweep failed (will retry): %s", e)
                time.sleep(SWEEP_STEP_SLEEP * 5)
            time.sleep(SWEEP_STEP_SLEEP)

    def start(self):
        threading.Thread(target=self._sweep_loop, daemon=True, name="last-ssh-sweep").start()

    ##################
    # 读缓存

    def get(self, container_name: str) -> dict:
        """读取侧：只读缓存，不做任何 IO。

        返回: {"last_ssh_connect_time": str|None, "source": "fresh"|"stale"|"miss"}
        - fresh: TTL 内采集值（端点 200）
        - stale: TTL 外旧值（值本身仍是上次真实采集，Ctrl 幂等 upsert 无害）
        - miss: 从未采集（含非运行态跳过），端点 404 → Ctrl 保持 DB 旧值
        """
        with self._lock:
            entry = self._cache.get(container_name)
        if entry is None:
            return {"last_ssh_connect_time": None, "source": "miss"}
        age = (datetime.datetime.utcnow() - entry["updated_at"]).total_seconds()
        source = "fresh" if age <= LAST_SSH_TTL_SEC else "stale"
        return {"last_ssh_connect_time": entry["value"], "source": source}

    def snapshot(self) -> dict:
        with self._lock:
            return {name: dict(e) for name, e in self._cache.items()}
