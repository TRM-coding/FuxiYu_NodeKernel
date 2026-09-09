from FuxiYu_NodeKernel import extensions
from FuxiYu_NodeKernel.services import container_service

from .conftest import FakeContainer, FakeContainers


class FakeDockerClientWithInspect:
    def __init__(self, container, size_rw):
        self.containers = FakeContainers([container])
        self.api = self
        self.size_rw = size_rw
        self.inspect_calls = []
        self.df_called = False

    def inspect_container(self, container_id, size=False):
        self.inspect_calls.append((container_id, size))
        return {"SizeRw": self.size_rw}

    def _url(self, path, *args):
        return path.format(*args)

    def _get(self, url, params=None):
        self.inspect_calls.append((url, params))
        return {"url": url, "params": params}

    def _result(self, response, json=False):
        return {"SizeRw": self.size_rw}

    def df(self):
        self.df_called = True
        raise AssertionError("docker df should not be used for single-container disk usage")


def test_get_disk_usage_uses_single_container_inspect_for_overlay(monkeypatch):
    container = FakeContainer("c1")
    container.attrs.update({"Mounts": []})
    client = FakeDockerClientWithInspect(container, size_rw=12345)
    monkeypatch.setattr(extensions, "docker_client", client)

    usage = container_service.get_disk_usage("c1")

    assert usage["container"]["overlay_rw_bytes"] == 12345
    assert client.inspect_calls == [
        (f"/containers/{container.id}/json", {"size": 1}),
    ]
    assert client.df_called is False


def test_get_disk_usage_returns_unknown_total_while_bind_is_measuring(monkeypatch):
    container = FakeContainer("c1")
    container.attrs.update({
        "SizeRw": 100,
        "Mounts": [{"Type": "bind", "Source": "/tmp/c1", "Destination": "/root"}],
    })
    monkeypatch.setattr(extensions, "docker_client", FakeDockerClientWithInspect(container, size_rw=0))
    monkeypatch.setattr(
        container_service,
        "_resolve_bind_disk",
        lambda _path: {
            "bind_mount_bytes": None,
            "bind_mount_source": "measuring",
            "bind_mount_path": "/tmp/c1",
        },
    )

    usage = container_service.get_disk_usage("c1")

    assert usage["container"]["bind_mount_bytes"] is None
    assert usage["container"]["total_bytes"] is None
