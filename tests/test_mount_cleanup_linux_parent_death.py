from __future__ import annotations

import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from FuxiYu_NodeKernel.services.mount_cleanup import MountCleanupManager


pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="Linux PR_SET_PDEATHSIG integration only",
)


def _wait_for(path: Path, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
        time.sleep(0.02)
    return None


def _fake_rm(tmp_path: Path, pidfile: Path) -> Path:
    script = tmp_path / "fake-rm.sh"
    script.write_text(
        "#!/bin/sh\n"
        f"echo $$ > {shlex.quote(str(pidfile))}\n"
        "exec sleep 60\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def _launcher_path() -> Path:
    return Path(__file__).resolve().parents[1] / "services" / "mount_modules" / "cleanup_launcher.py"


def _process_state(pid: int):
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    return stat.split()[2]


def test_sigkill_parent_kills_rm_via_pdeathsig(tmp_path):
    base = tmp_path / "base"
    mount = base / "alice" / "containers" / "c1"
    mount.mkdir(parents=True)
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")
    pidfile = tmp_path / "rm.pid"
    ready = tmp_path / "ready.txt"
    stderr_file = tmp_path / "child.err"
    fake_rm = _fake_rm(tmp_path, pidfile)

    child_code = (
        "import os, time\n"
        "from pathlib import Path\n"
        "from FuxiYu_NodeKernel.services.mount_cleanup import MountCleanupManager\n"
        f"base = {str(base)!r}\n"
        f"mount = {str(mount)!r}\n"
        f"ready = Path({str(ready)!r})\n"
        "manager = MountCleanupManager(rm_path=os.environ['TEST_RM_PATH'], use_launcher=True)\n"
        "manager.start()\n"
        "task_id = manager.start_cleanup(mount)\n"
        "ready.write_text(task_id, encoding='utf-8')\n"
        "time.sleep(60)\n"
    )
    env = dict(os.environ)
    env["NODE_CONTAINERS_BASE"] = str(base)
    env["TEST_RM_PATH"] = str(fake_rm)
    repo = Path(__file__).resolve().parents[1]
    env["PYTHONPATH"] = str(repo.parent)
    with stderr_file.open("w", encoding="utf-8") as err:
        child = subprocess.Popen(
            [sys.executable, "-c", child_code],
            cwd=str(repo),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=err,
        )

    try:
        task_id = _wait_for(ready)
        rm_pid_text = _wait_for(pidfile)
        assert task_id is not None, stderr_file.read_text(encoding="utf-8")
        assert rm_pid_text is not None, stderr_file.read_text(encoding="utf-8")
        rm_pid = int(rm_pid_text)
        assert _process_state(rm_pid) in {"R", "S", "D"}

        os.kill(child.pid, signal.SIGKILL)
        child.wait(timeout=5)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            state = _process_state(rm_pid)
            if state is None or state == "Z":
                break
            time.sleep(0.02)
        assert _process_state(rm_pid) in {None, "Z"}
        assert sentinel.read_text(encoding="utf-8") == "keep"

        restarted = MountCleanupManager(rm_path=fake_rm, use_launcher=True)
        assert restarted.get_status(task_id) is None
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


def test_launcher_parent_mismatch_exits_without_exec_rm(tmp_path):
    sentinel = tmp_path / "sentinel.txt"
    fake_rm = tmp_path / "fake-rm.sh"
    fake_rm.write_text(
        "#!/bin/sh\n"
        f"touch {shlex.quote(str(sentinel))}\n",
        encoding="utf-8",
    )
    fake_rm.chmod(0o755)

    result = subprocess.run(
        [
            sys.executable,
            str(_launcher_path()),
            "--parent-pid",
            "999999",
            "--rm-path",
            str(fake_rm),
            "--path",
            str(tmp_path / "anything"),
        ],
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 121
    assert not sentinel.exists()
