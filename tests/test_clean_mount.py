"""clean_mount 服务层安全测试（安全审查回归集）。

三重校验：realpath 归一化 → 必须位于 NODE_CONTAINERS_BASE 下 → 解析后仍含 /containers/ 段。
覆盖审查场景：base 外路径、../ 逃逸、符号链接跳出 base、伪装段名；
以及 rm 失败必须抛错（不假成功）。
"""
import os
import subprocess
from types import SimpleNamespace

import pytest

import FuxiYu_NodeKernel.services.container_service as cs
from FuxiYu_NodeKernel.services.container_service import clean_mount


def _install_fake_rm(monkeypatch, returncode=0, stdout="", stderr=""):
    """拦截 subprocess.run，记录删除调用并返回可编程 returncode + 输出。"""
    calls = []

    def fake_run(cmd, timeout=None, check=False, capture_output=False, text=False, errors=None):
        calls.append({
            "cmd": list(cmd), "timeout": timeout, "check": check,
            "capture_output": capture_output, "text": text,
        })
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(cs.subprocess, "run", fake_run)
    return calls


@pytest.fixture()
def containers_base(tmp_path, monkeypatch):
    base = tmp_path / "fuxi-base"
    base.mkdir()
    monkeypatch.setenv("NODE_CONTAINERS_BASE", str(base))
    return base


def test_accepts_legitimate_container_mount_dir(containers_base, monkeypatch):
    """合法容器挂载目录（base 下且含 /containers/ 段）→ 执行 rm，返回 True。"""
    calls = _install_fake_rm(monkeypatch)
    mount = containers_base / "alice" / "containers" / "c1"
    mount.mkdir(parents=True)

    assert clean_mount(str(mount)) is True
    assert len(calls) == 1
    assert calls[0]["cmd"] == ["rm", "-rf", os.path.realpath(str(mount))]
    assert calls[0]["timeout"] == 30
    assert calls[0]["check"] is False
    assert calls[0]["capture_output"] is True, "rm 的输出必须被捕获——失败时要带上 stderr"


def test_rejects_traversal_paths(containers_base, monkeypatch):
    """相对真实 base 构造的穿越/越权样本，全部拒绝且不执行 rm。"""
    base = containers_base
    attacks = [
        "/etc",  # base 外绝对路径
        str(base.parent / "secret"),  # base 兄弟目录
        f"{base}/a/containers/../../target",  # ../ 逃逸出 containers 段（审查原样本同构）
        f"{base}/alice/containers/c1/../../../outside",  # 深逃逸
        f"{base}_evil/containers/c1",  # 伪装前缀（base_evil 不是 base/ 子路径）
    ]
    calls = _install_fake_rm(monkeypatch)
    for attack in attacks:
        with pytest.raises(ValueError, match="invalid mount_path"):
            clean_mount(attack)
    assert calls == [], "被拒路径不得执行 rm"


def test_rejects_symlink_escaping_base(containers_base, monkeypatch):
    """合法目录被换成指向 base 外的符号链接 → realpath 展开后前缀校验失败。"""
    target = containers_base.parent / "secret"
    target.mkdir()
    (containers_base / "alice").mkdir(parents=True, exist_ok=True)
    link = containers_base / "alice" / "containers"
    try:
        os.symlink(str(target), str(link), target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink not permitted in this environment")

    calls = _install_fake_rm(monkeypatch)
    with pytest.raises(ValueError, match="invalid mount_path"):
        clean_mount(str(link))
    assert calls == []


def test_rm_failure_raises(containers_base, monkeypatch):
    """rm 非 0 退出（权限/IO 失败）→ 抛 RuntimeError，不让调用方误判清理成功。"""
    calls = _install_fake_rm(monkeypatch, returncode=1)
    mount = containers_base / "alice" / "containers" / "c1"
    mount.mkdir(parents=True)

    with pytest.raises(RuntimeError, match="rm -rf failed"):
        clean_mount(str(mount))
    assert len(calls) == 1


def test_rm_failure_surfaces_stderr(containers_base, monkeypatch):
    """rm 的 stderr 必须进错误信息。

    回归锁：此前 `subprocess.run` 没带 capture_output，stderr 被丢掉，端点只回一句
    `rm -rf failed (rc=1)`——分不清是权限、只读文件系统还是路径不对。2026-09 实测踩到：
    容器内以 root 写进挂载目录的东西在宿主上是 root:root（`.cache` 还是 0700），Node 以
    非 root 运行时 rm 报的 `Permission denied` 一个字都看不到，只能靠人去翻目录。
    """
    _install_fake_rm(
        monkeypatch, returncode=1,
        stderr="rm: cannot remove '/base/alice/containers/c1/.cache/f': Permission denied\n",
    )
    mount = containers_base / "alice" / "containers" / "c1"
    mount.mkdir(parents=True)

    with pytest.raises(RuntimeError) as exc:
        clean_mount(str(mount))

    message = str(exc.value)
    assert "Permission denied" in message
    assert os.path.realpath(str(mount)) in message, "路径要留着，便于人去找残留"
    assert "--- rm output ---" in message


def test_rm_failure_truncates_huge_stderr(containers_base, monkeypatch):
    """stderr 要有上界，而且截断必须写明省了多少行（静默截断等于骗人）。"""
    _install_fake_rm(
        monkeypatch, returncode=1,
        stderr="".join(f"rm: cannot remove '/x/f{i}': Permission denied\n" for i in range(50)),
    )
    mount = containers_base / "alice" / "containers" / "c1"
    mount.mkdir(parents=True)

    with pytest.raises(RuntimeError) as exc:
        clean_mount(str(mount))

    message = str(exc.value)
    assert "其余 40 行已省略" in message
    assert message.count("Permission denied") == 10, "只保留前 10 行"
    assert "f49" not in message, "第 11 行之后的内容不进错误信息"
