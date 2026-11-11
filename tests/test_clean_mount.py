"""clean_mount service regression tests after the launcher migration.

The legacy synchronous endpoint still uses the same whitelist, 30-second wait
limit, rm argv, bounded stderr and failure semantics. The process factory is
injected so the tests do not delete host paths.
"""
import os
import subprocess

import pytest

import FuxiYu_NodeKernel.services.container_service as cs  # noqa: F401  (module-level seam)
from FuxiYu_NodeKernel.services.container_service import clean_mount
from FuxiYu_NodeKernel.services.mount_cleanup import MountCleanupManager
from FuxiYu_NodeKernel import extensions

from .mount_cleanup_fakes import FakeProcessFactory


def _install_manager(tmp_path, monkeypatch, **process_kwargs):
    base = tmp_path / "fuxi-base"
    base.mkdir()
    monkeypatch.setenv("NODE_CONTAINERS_BASE", str(base))
    factory = FakeProcessFactory(**process_kwargs)
    manager = MountCleanupManager(
        use_launcher=False,
        rm_path="rm",
        process_factory=factory,
    )
    monkeypatch.setattr(extensions, "mount_cleanup", manager)
    return base, factory, manager


@pytest.fixture()
def containers_base(tmp_path, monkeypatch):
    base, factory, _ = _install_manager(tmp_path, monkeypatch)
    return base, factory


def test_accepts_legitimate_container_mount_dir(containers_base, monkeypatch):
    """Legacy sync uses realpath, rm argv, 30s waiting and captured stderr."""
    base, factory = containers_base
    mount = base / "alice" / "containers" / "c1"
    mount.mkdir(parents=True)

    assert clean_mount(str(mount)) is True
    assert len(factory.calls) == 1
    call = factory.calls[0]
    assert call["command"][0] == "rm"
    assert call["command"][1:] == ["-rf", os.path.realpath(str(mount))]
    assert "shell" not in call["kwargs"]
    assert call["kwargs"]["stdout"] == subprocess.PIPE
    assert call["kwargs"]["stderr"] == subprocess.PIPE
    assert factory.processes[0].communicate_timeouts == [30.0]


def test_rejects_traversal_paths(containers_base):
    base, factory = containers_base
    attacks = [
        "/etc",
        str(base.parent / "secret"),
        f"{base}/a/containers/../../target",
        f"{base}/alice/containers/c1/../../../outside",
        f"{base}_evil/containers/c1",
    ]
    for attack in attacks:
        with pytest.raises(ValueError, match="invalid mount_path"):
            clean_mount(attack)
    assert factory.calls == []


def test_rejects_symlink_escaping_base(containers_base):
    base, factory = containers_base
    target = base.parent / "secret"
    target.mkdir()
    (base / "alice").mkdir(parents=True, exist_ok=True)
    link = base / "alice" / "containers"
    try:
        os.symlink(str(target), str(link), target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink not permitted in this environment")

    with pytest.raises(ValueError, match="invalid mount_path"):
        clean_mount(str(link))
    assert factory.calls == []


def test_rm_failure_raises(tmp_path, monkeypatch):
    base, factory, _ = _install_manager(
        tmp_path, monkeypatch, returncode=1, stderr="permission denied"
    )
    mount = base / "alice" / "containers" / "c1"
    mount.mkdir(parents=True)

    with pytest.raises(RuntimeError, match="rm -rf failed"):
        clean_mount(str(mount))
    assert len(factory.calls) == 1
    assert factory.processes[0].communicate_timeouts == [30.0]


def test_rm_failure_surfaces_stderr(tmp_path, monkeypatch):
    stderr = "rm: cannot remove '/base/alice/containers/c1/.cache/f': Permission denied\n"
    base, factory, _ = _install_manager(
        tmp_path, monkeypatch, returncode=1, stderr=stderr
    )
    mount = base / "alice" / "containers" / "c1"
    mount.mkdir(parents=True)

    with pytest.raises(RuntimeError) as exc:
        clean_mount(str(mount))

    message = str(exc.value)
    assert "Permission denied" in message
    assert os.path.realpath(str(mount)) in message
    assert "--- rm output ---" in message


def test_rm_failure_truncates_huge_stderr(tmp_path, monkeypatch):
    stderr = "".join(
        f"rm: cannot remove '/x/f{i}': Permission denied\n" for i in range(50)
    )
    base, factory, _ = _install_manager(
        tmp_path, monkeypatch, returncode=1, stderr=stderr
    )
    mount = base / "alice" / "containers" / "c1"
    mount.mkdir(parents=True)

    with pytest.raises(RuntimeError) as exc:
        clean_mount(str(mount))

    message = str(exc.value)
    assert "其余 40 行已省略" in message
    assert message.count("Permission denied") == 10
    assert "f49" not in message
