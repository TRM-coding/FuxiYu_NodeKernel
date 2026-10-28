"""Independent regression coverage for the creation/credential mapping change.

The tests use real FastAPI/Pydantic/service paths and fake Docker boundaries only.
``test_restore_mount_base_itself_is_rejected`` covers the restore-source equality
gate, while ``test_restore_valid_historical_subdir_still_recovers`` proves a
normal historical child mount still reuses its original directory.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import threading
import time
from pathlib import Path

import httpx2
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from FuxiYu_NodeKernel import create_app, extensions
from FuxiYu_NodeKernel.constant import ROLE
from FuxiYu_NodeKernel.docker_operates import port_allocator
from FuxiYu_NodeKernel.docker_operates.account_passwords import _set_account_password
from FuxiYu_NodeKernel.docker_operates.status_cache import ContainerStatusCache
from FuxiYu_NodeKernel.network import api as api_module
from FuxiYu_NodeKernel.network import wss as wss_module
from FuxiYu_NodeKernel.schemas.container import (
    ContainerConfig,
    CreateContainerAcceptedResponse,
    CreateContainerMessage,
    CreateContainerResponse,
    ImageBuildConfig,
    RestoreAccountConfig,
)
from FuxiYu_NodeKernel.schemas.container import ContainerConfig as NewContainerConfig
from FuxiYu_NodeKernel.services.container_service import (
    CreateContainerReturn,
    add_collaborator,
    build_image,
    create_container,
)
from FuxiYu_NodeKernel.utils.Container import Container

from .conftest import FakeContainer, FakeContainers, FakeDockerClient, FakeExecAPI, FakeImages
from .password_fakes import (
    PasswordFakeContainer,
    PasswordFakeDockerClient,
    install_password_docker,
)

ROOT_PW = SecretStr("Root#Password9")
PW = SecretStr("Role#Password9")
PUBLIC_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAnvilTestOnly test@example"
PRIVATE_KEY = "-----BEGIN OPENSSH PRIVATE KEY-----\nANVIL-PRIVATE-MATERIAL\n-----END OPENSSH PRIVATE KEY-----"

_PROXY_KEYS = ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "no_proxy", "NO_PROXY")


def _cfg(name: str = "anvil_c", image: str = "ubuntu:22.04") -> dict:
    return {
        "gpu_list": [],
        "cpu_number": 2,
        "memory": 4,
        "shared_memory": 0,
        "name": name,
        "port": 2233,
        "image": image,
    }


def _clear_proxy(monkeypatch) -> None:
    for key in _PROXY_KEYS:
        monkeypatch.delenv(key, raising=False)


def _prepare_base(monkeypatch, tmp_path) -> Path:
    base = tmp_path / "home"
    monkeypatch.setenv("NODE_CONTAINERS_BASE", str(base))
    monkeypatch.setattr(port_allocator, "_system_bound_ports", lambda: set())
    _clear_proxy(monkeypatch)
    return base


def _wait_for(predicate, timeout: float = 4.0, message: str = "condition not met"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError(message)


def _json(value) -> str:
    return json.dumps(value, default=str, ensure_ascii=False)


def _new_cache() -> ContainerStatusCache:
    cache = ContainerStatusCache()
    extensions.status_cache = cache
    return cache


def _json_keys(item: dict) -> set[str]:
    return set(item)


class _RecordedContainer(FakeContainer):
    def __init__(self, name: str = "c1", ports: dict | None = None, **kwargs):
        super().__init__(name=name, **kwargs)
        self.attrs = {
            "State": {"Status": self.status},
            "NetworkSettings": {"Ports": ports or {}},
        }


class _RegisteredContainers(FakeContainers):
    """FakeContainers whose run results are discoverable by containers.get()."""

    def run(self, *args, **kwargs):
        self.run_calls.append((args, kwargs))
        container = _RecordedContainer(name=kwargs.get("name", "c1"))
        self._existing.append(container)
        return container


class _PortContainers(FakeContainers):
    def run(self, *args, **kwargs):
        self.run_calls.append((args, kwargs))
        return _RecordedContainer(
            name=kwargs.get("name", "c1"),
            ports={
                "22/tcp": [{"HostPort": "21000"}],
                "8080/tcp": [{"HostPort": "21001"}],
            },
        )


class _SpyImages:
    def __init__(self):
        self.get_calls: list[str] = []
        self.build_calls: list[dict] = []

    def get(self, tag):
        self.get_calls.append(tag)
        raise AssertionError(f"images.get must not be called: {tag}")

    def build(self, **kwargs):
        self.build_calls.append(kwargs)
        return ([], [])


class _BuildImages:
    def __init__(self):
        self.built: set[str] = set()
        self.get_calls: list[str] = []
        self.build_calls: list[dict] = []
        self.texts: list[str] = []
        self.removed: list[str] = []
        self._path = None

    def get(self, tag):
        self.get_calls.append(tag)
        import docker

        if tag in self.built:
            return object()
        raise docker.errors.ImageNotFound("not built")

    def build(self, **kwargs):
        self.build_calls.append(kwargs)
        self.texts.append((Path(kwargs["path"]) / "Dockerfile").read_text(encoding="utf-8"))
        self.built.add(kwargs["tag"])
        return ([], [])

    def remove(self, tag, **kwargs):
        self.removed.append(tag)


class _EventAPI(FakeExecAPI):
    def __init__(self, events: list):
        super().__init__()
        self.events = events

    def exec_create(self, container_id, cmd, **kwargs):
        self.events.append(("chpasswd", cmd))
        return super().exec_create(container_id, cmd, **kwargs)


class _EventContainer(FakeContainer):
    def __init__(self, name: str = "c1", events: list | None = None):
        super().__init__(name=name)
        self.events = events if events is not None else []

    def exec_run(self, cmd, **kw):
        self.events.append(("exec", cmd))
        return super().exec_run(cmd, **kw)


class _EventContainers(FakeContainers):
    def __init__(self, events: list):
        super().__init__()
        self.events = events

    def run(self, *args, **kwargs):
        self.run_calls.append((args, kwargs))
        return _EventContainer(name=kwargs.get("name", "c1"), events=self.events)


class _BlockingContainers(FakeContainers):
    def __init__(self, entered: threading.Event, release: threading.Event):
        super().__init__()
        self.entered = entered
        self.release = release

    def run(self, *args, **kwargs):
        self.run_calls.append((args, kwargs))
        container = _RecordedContainer(name=kwargs.get("name", "c1"))
        self._existing.append(container)
        self.entered.set()
        if not self.release.wait(5):
            raise RuntimeError("test worker release timed out")
        return container


class _BlockingExecAPI(FakeExecAPI):
    def __init__(
        self,
        entered: threading.Event,
        release: threading.Event,
        *,
        exit_code: int = 0,
    ):
        super().__init__(exit_code=exit_code)
        self.entered = entered
        self.release = release

    def exec_create(self, container_id, cmd, **kwargs):
        self.entered.set()
        if not self.release.wait(5):
            raise RuntimeError("test worker release timed out")
        return super().exec_create(container_id, cmd, **kwargs)


def _create_payload(name: str, **overrides) -> dict:
    payload = {
        "owner_name": "admin",
        "config": _cfg(name),
        "root_password": ROOT_PW.get_secret_value(),
    }
    payload.update(overrides)
    return payload


def _assert_validation_details(resp) -> None:
    details = resp.json()["detail"]
    assert isinstance(details, list)
    for item in details:
        assert set(item) == {"type", "loc", "msg"}


def test_container_config_defaults_and_ge_bounds():
    cfg = ContainerConfig(
        cpu_number=0,
        memory=0,
        shared_memory=0,
        name="c1",
        port=0,
        image="ubuntu:22.04",
    )
    assert cfg.gpu_list == []
    assert cfg.cpu_number == 0
    assert cfg.memory == 0
    assert cfg.shared_memory == 0
    assert cfg.port == 0

    upper = ContainerConfig(
        cpu_number=0,
        memory=0,
        shared_memory=0,
        name="c1",
        port=65535,
        image="ubuntu:22.04",
    )
    assert upper.port == 65535

    for overrides in (
        {"cpu_number": -1},
        {"memory": -1},
        {"shared_memory": -1},
        {"port": 65536},
        {"image": None},
    ):
        args = {
            "gpu_list": [],
            "cpu_number": 0,
            "memory": 0,
            "shared_memory": 0,
            "name": "c1",
            "port": 0,
            "image": "ubuntu:22.04",
        }
        args.update(overrides)
        with pytest.raises(ValidationError):
            ContainerConfig(**args)


def test_image_build_config_defaults_and_empty_build_rejected(monkeypatch):
    model = ImageBuildConfig()
    assert model.dockerfile_text == ""
    assert model.image_tag == ""

    explicit = ImageBuildConfig(
        dockerfile_text="FROM ubuntu:22.04\nRUN echo ok\n",
        image_tag="fuxi/image-1:tag",
    )
    assert explicit.dockerfile_text.startswith("FROM ubuntu")
    assert explicit.image_tag == "fuxi/image-1:tag"

    with pytest.raises(ValidationError):
        ImageBuildConfig(dockerfile_text=123, image_tag="x")
    with pytest.raises(ValidationError):
        ImageBuildConfig(dockerfile_text="FROM x", image_tag=["x"])

    images = _SpyImages()
    containers = FakeContainers()
    monkeypatch.setattr(
        extensions,
        "docker_client",
        type("_Docker", (), {"images": images, "containers": containers})(),
    )

    with pytest.raises(RuntimeError, match="missing dockerfile_text"):
        build_image({"dockerfile_text": "", "image_tag": "fuxi/x:1"})
    with pytest.raises(RuntimeError, match="missing image_tag"):
        build_image({"dockerfile_text": "FROM x", "image_tag": ""})

    assert images.get_calls == []
    assert images.build_calls == []
    assert containers.run_calls == []


def test_restore_account_defaults_and_password_retention():
    account = RestoreAccountConfig(user_name="u1", password=SecretStr("12345678"))
    assert account.role == "collaborator"
    assert isinstance(account.password, SecretStr)
    assert account.password.get_secret_value() == "12345678"
    assert account.password.get_secret_value() not in repr(account)

    long_password = "x" * 128
    long_account = RestoreAccountConfig(
        user_name="u1", password=SecretStr(long_password)
    )
    assert long_account.password.get_secret_value() == long_password

    with pytest.raises(ValidationError):
        RestoreAccountConfig(user_name="u1", role="root", password=PW)
    with pytest.raises(ValidationError):
        RestoreAccountConfig(user_name="u1", role="ADMIN", password=PW)
    with pytest.raises(ValidationError):
        RestoreAccountConfig(role="admin", password=PW)
    with pytest.raises(ValidationError):
        RestoreAccountConfig(user_name="u1", password=123)
    with pytest.raises(ValidationError):
        RestoreAccountConfig(user_name="u1", password=None)


def test_restore_account_password_absent_from_snapshot_wss_cache_and_logs(
    monkeypatch, tmp_path, capsys, caplog
):
    _prepare_base(monkeypatch, tmp_path)
    cache = _new_cache()
    containers = _RegisteredContainers()
    docker = PasswordFakeDockerClient(containers, FakeImages())
    monkeypatch.setattr(extensions, "docker_client", docker)
    app = create_app()
    http = TestClient(app)

    success_name = "restore_secret_success"
    response = http.post(
        "/api/create_container",
        json=_create_payload(
            success_name,
            restore_accounts=[
                {
                    "user_name": "alice",
                    "role": "collaborator",
                    "password": PW.get_secret_value(),
                }
            ],
        ),
    )
    assert response.status_code == 200
    _wait_for(
        lambda: (cache.get_state(success_name).get("last_action") or {}).get("phase")
        == "confirmed",
        message="restore success create did not confirm",
    )

    success_text = response.text + capsys.readouterr().out + caplog.text
    success_blob = _json(
        {
            "states": cache.list_states(),
            "state": cache.get_state(success_name),
            "wss": wss_module.build_status_snapshot(),
        }
    )
    for secret in (ROOT_PW.get_secret_value(), PW.get_secret_value()):
        assert secret not in success_text
        assert secret not in success_blob
    for marker in ("root_password", "credentials", "password"):
        assert marker not in success_blob

    # Failure path: collaborator restoration is rejected after container creation.
    caplog.clear()
    failure_name = "restore_secret_failure"
    monkeypatch.setattr(api_module, "container_exists", lambda name: False)
    monkeypatch.setattr(
        api_module,
        "create_container",
        lambda owner_name, cfg, **kwargs: CreateContainerReturn("cid", cfg.name),
    )
    monkeypatch.setattr(api_module, "add_collaborator", lambda *args, **kwargs: False)
    failed = http.post(
        "/api/create_container",
        json=_create_payload(
            failure_name,
            restore_accounts=[
                {
                    "user_name": "alice",
                    "role": "collaborator",
                    "password": PW.get_secret_value(),
                }
            ],
        ),
    )
    assert failed.status_code == 200
    _wait_for(
        lambda: (cache.get_state(failure_name).get("last_action") or {}).get("phase")
        == "failed",
        message="restore failure create did not fail",
    )
    failure_text = failed.text + capsys.readouterr().out + caplog.text
    failure_blob = _json(
        {
            "states": cache.list_states(),
            "state": cache.get_state(failure_name),
            "wss": wss_module.build_status_snapshot(),
        }
    )
    for secret in (ROOT_PW.get_secret_value(), PW.get_secret_value()):
        assert secret not in failure_text
        assert secret not in failure_blob
    assert "credentials" not in failure_text
    assert cache.get_state(failure_name)["last_action"]["error_reason"] == "create_failed"
    http.close()


def test_restore_account_missing_password_422_not_accepted(monkeypatch, tmp_path):
    _prepare_base(monkeypatch, tmp_path)
    cache = _new_cache()
    containers = _RegisteredContainers()
    monkeypatch.setattr(
        extensions, "docker_client", FakeDockerClient(containers, FakeImages())
    )
    called = []
    monkeypatch.setattr(
        api_module,
        "add_collaborator",
        lambda *args, **kwargs: called.append((args, kwargs)) or True,
    )
    http = TestClient(create_app())
    name = "restore_missing_pw"

    response = http.post(
        "/api/create_container",
        json=_create_payload(
            name,
            restore_accounts=[{"user_name": "alice", "role": "collaborator"}],
        ),
    )

    assert response.status_code == 422
    assert response.headers["Cache-Control"] == "no-store"
    assert "input" not in response.text and "ctx" not in response.text
    assert "alice123" not in response.text
    assert cache.list_states().get(name) is None
    assert containers.run_calls == []
    assert called == []
    http.close()


def test_create_message_optional_field_defaults():
    message = CreateContainerMessage(
        owner_name="admin",
        config=ContainerConfig(**_cfg("c1")),
        root_password=ROOT_PW,
    )
    assert message.public_key is None
    assert message.image_build is None
    assert message.restore_mount_path is None
    assert message.restore_accounts == []

    other = CreateContainerMessage(
        owner_name="admin",
        config=ContainerConfig(**_cfg("c2")),
        root_password=ROOT_PW,
    )
    assert message.restore_accounts is not other.restore_accounts


def test_public_key_installed_without_private_key_material(monkeypatch, tmp_path, capsys, caplog):
    _prepare_base(monkeypatch, tmp_path)
    cache = _new_cache()
    containers = _RegisteredContainers()
    docker = FakeDockerClient(containers, FakeImages())
    monkeypatch.setattr(extensions, "docker_client", docker)
    http = TestClient(create_app())
    name = "public_key_only"

    response = http.post(
        "/api/create_container",
        json=_create_payload(
            name,
            public_key=PUBLIC_KEY,
            private_key=PRIVATE_KEY,
        ),
    )
    assert response.status_code == 200
    _wait_for(
        lambda: (cache.get_state(name).get("last_action") or {}).get("phase")
        == "confirmed",
        message="public key create did not confirm",
    )

    assert len(containers.run_calls) == 1
    run_text = _json({"args": containers.run_calls[0][0], "kwargs": containers.run_calls[0][1]})
    container = containers._existing[0]
    exec_text = _json(container.exec_calls)
    text = run_text + exec_text + response.text + capsys.readouterr().out + caplog.text

    assert PRIVATE_KEY not in text
    expected = base64.b64encode(PUBLIC_KEY.encode("utf-8")).decode("ascii")
    assert expected in exec_text
    assert "authorized_keys" in exec_text
    http.close()


def test_missing_root_password_422_not_accepted(monkeypatch, tmp_path):
    _prepare_base(monkeypatch, tmp_path)
    cache = _new_cache()
    containers = _RegisteredContainers()
    monkeypatch.setattr(
        extensions, "docker_client", FakeDockerClient(containers, FakeImages())
    )
    http = TestClient(create_app())
    name = "missing_root_pw"
    payload = {
        "owner_name": "admin",
        "config": _cfg(name),
    }

    response = http.post("/api/create_container", json=payload)

    assert response.status_code == 422
    assert response.headers["Cache-Control"] == "no-store"
    assert "input" not in response.text and "ctx" not in response.text
    assert "admin123" not in response.text
    assert cache.list_states().get(name) is None
    assert containers.run_calls == []
    http.close()


def test_create_root_password_invalid_422_redacted(
    monkeypatch, tmp_path, capsys, caplog
):
    _prepare_base(monkeypatch, tmp_path)
    cache = _new_cache()
    containers = _RegisteredContainers()
    monkeypatch.setattr(
        extensions, "docker_client", FakeDockerClient(containers, FakeImages())
    )
    http = TestClient(create_app())
    values = [
        "",
        "short",
        "x" * 129,
        "        ",
        "abc:defgh",
        "abc\rdefgh",
        "abc\ndefgh",
        "abc\x00defgh",
        {"value": "Root#Password9"},
    ]

    for index, value in enumerate(values):
        name = f"invalid_root_{index}"
        response = http.post(
            "/api/create_container",
            json={
                "owner_name": "admin",
                "config": _cfg(name),
                "root_password": value,
            },
        )
        assert response.status_code == 422, (value, response.text)
        assert response.headers["Cache-Control"] == "no-store"
        assert "input" not in response.text and "ctx" not in response.text
        assert "url" not in response.text
        _assert_validation_details(response)
        if isinstance(value, str) and value.strip():
            assert value not in response.text
            assert value not in capsys.readouterr().out
            assert value not in caplog.text
        assert cache.list_states().get(name) is None
    assert containers.run_calls == []
    http.close()


def test_create_response_defaults_and_accepted_alias_wire_shape():
    response = CreateContainerResponse(
        container_status="creating",
        container_name="c1",
    )
    assert response.success == 1
    assert response.action_ref is None

    dumped = response.model_dump()
    assert set(dumped) == {
        "success",
        "container_status",
        "container_name",
        "action_ref",
    }

    with pytest.raises(ValidationError):
        CreateContainerResponse(container_status="online", container_name="c1")
    with pytest.raises(ValidationError):
        CreateContainerResponse(container_name="c1")
    with pytest.raises(ValidationError):
        CreateContainerResponse(container_status="creating")
    with pytest.raises(ValidationError):
        CreateContainerResponse(
            container_status="creating",
            container_name="c1",
            action_ref={"node_epoch": "e", "generation": -1, "seq": 1},
        )

    alias = CreateContainerAcceptedResponse(
        container_status="building",
        container_name="c1",
    )
    assert alias.model_dump() == {
        "success": 1,
        "container_status": "building",
        "container_name": "c1",
        "action_ref": None,
    }
    assert CreateContainerAcceptedResponse is CreateContainerResponse


def test_create_response_action_ref_matches_create_generation_and_seq(monkeypatch):
    cache = _new_cache()
    name = "action_ref_c1"
    monkeypatch.setattr(api_module, "container_exists", lambda container_name: False)
    monkeypatch.setattr(
        api_module,
        "create_container",
        lambda owner_name, cfg, **kwargs: CreateContainerReturn("cid", cfg.name),
    )
    http = TestClient(create_app())
    response = http.post("/api/create_container", json=_create_payload(name))
    assert response.status_code == 200
    ref = response.json()["action_ref"]
    _wait_for(
        lambda: (cache.get_state(name).get("last_action") or {}).get("phase")
        == "confirmed",
        message="create action did not confirm",
    )
    state = cache.get_state(name)
    assert ref == state["last_action"]["ref"]
    assert ref["generation"] == 1
    assert ref["seq"] == 1
    http.close()


def test_legacy_container_dto_maps_config_values():
    container = Container(
        gpu_list=[1],
        cpu_number=2,
        memory=4,
        shared_memory=1,
        name="c1",
        image="ubuntu:22.04",
        port=2233,
    )
    assert container.GPU_LIST == [1]
    assert container.CPU_NUMBER == 2
    assert container.MEMORY == 4
    assert container.SHARED_MEMORY == 1
    assert container.NAME == "c1"

    config = container.get_config()
    assert set(config) == {
        "gpu_list",
        "cpu_number",
        "memory",
        "shared_memory",
        "name",
        "port",
        "image",
    }
    assert config["port"] == 2233
    assert config["image"] == "ubuntu:22.04"

    container.set_port(2234)
    assert container.get_config()["port"] == 2234
    with pytest.raises(ValueError):
        container.set_port(1023)
    with pytest.raises(ValueError):
        container.set_port(49152)


def test_legacy_config_info_accepts_values_new_schema_rejects():
    legacy = Container.Config_info(
        gpu_list=[],
        cpu_number=-1,
        memory=-1,
        shared_memory=-1,
        name="c1",
        port=70000,
        image="x",
    )
    assert legacy.cpu_number == -1
    assert legacy.port == 70000

    with pytest.raises(ValidationError):
        NewContainerConfig(
            gpu_list=[],
            cpu_number=-1,
            memory=-1,
            shared_memory=-1,
            name="c1",
            port=70000,
            image="x",
        )

    with pytest.raises(ValidationError):
        Container.Config_info(
            gpu_list=[],
            cpu_number=1,
            memory=1,
            shared_memory=1,
            port=2233,
            image="x",
        )
    with pytest.raises(ValidationError):
        NewContainerConfig(
            gpu_list=[],
            cpu_number=1,
            memory=1,
            shared_memory=1,
            port=2233,
            image="x",
        )


def test_create_container_return_fields_from_docker_facts(monkeypatch, tmp_path):
    _prepare_base(monkeypatch, tmp_path)
    containers = _PortContainers()
    monkeypatch.setattr(
        extensions, "docker_client", FakeDockerClient(containers, FakeImages())
    )

    empty = CreateContainerReturn("cid", "c1")
    assert empty.port is None
    assert empty.port_mappings is None
    assert empty.bind_mount_path is None

    result = create_container(
        "admin",
        Container.Config_info(**_cfg("port_facts_c")),
        root_password=ROOT_PW,
    )
    assert result.container_id == "fakeid_port_facts_c"
    assert result.container_name == "port_facts_c"
    assert result.port == 21000
    assert result.port_mappings == [
        {"container_port": 22, "host_port": 21000, "protocol": "tcp"},
        {"container_port": 8080, "host_port": 21001, "protocol": "tcp"},
    ]


def test_build_image_uses_exact_dockerfile_text_and_new_tag(monkeypatch):
    _clear_proxy(monkeypatch)
    images = _BuildImages()
    monkeypatch.setattr(
        extensions,
        "docker_client",
        type("_Docker", (), {"images": images})(),
    )
    text_v1 = "FROM ubuntu:22.04\nRUN echo v1\n"
    text_v2 = "FROM ubuntu:22.04\nRUN echo v2\n"
    tag_v1 = "fuxi/image-7:20260826T010203Z"
    tag_v2 = "fuxi/image-7:20260826T010204Z"

    assert build_image({"dockerfile_text": text_v1, "image_tag": tag_v1}) == tag_v1
    assert build_image({"dockerfile_text": text_v2, "image_tag": tag_v2}) == tag_v2
    assert build_image({"dockerfile_text": text_v2, "image_tag": tag_v2}) == tag_v2

    assert len(images.build_calls) == 2
    assert images.texts == [text_v1, text_v2]
    assert [call["tag"] for call in images.build_calls] == [tag_v1, tag_v2]
    assert images.removed == []


def test_restore_mount_source_independent_of_image_and_name(monkeypatch, tmp_path):
    base = _prepare_base(monkeypatch, tmp_path)
    restore = base / "admin" / "containers" / "old_name"
    restore.mkdir(parents=True)
    containers = FakeContainers()
    monkeypatch.setattr(
        extensions, "docker_client", FakeDockerClient(containers, FakeImages())
    )

    first = create_container(
        "admin",
        Container.Config_info(**_cfg("new_name_one", "ubuntu:22.04")),
        root_password=ROOT_PW,
        restore_mount_path=str(restore),
    )
    second = create_container(
        "admin",
        Container.Config_info(**_cfg("new_name_two", "debian:12")),
        root_password=ROOT_PW,
        restore_mount_path=str(restore),
    )

    assert len(containers.run_calls) == 2
    assert os.path.samefile(first.bind_mount_path, restore)
    assert os.path.samefile(second.bind_mount_path, restore)
    assert os.path.samefile(containers.run_calls[0][1]["mounts"][0]["Source"], restore)
    assert os.path.samefile(containers.run_calls[1][1]["mounts"][0]["Source"], restore)


@pytest.mark.parametrize(
    ("kind", "new_name"),
    [
        ("exact", "root_exact_c"),
        ("dot", "root_dot_c"),
        ("trailing", "root_trailing_c"),
        ("symlink", "root_symlink_c"),
        ("legacy", "root_legacy_c"),
    ],
)
def test_restore_mount_base_itself_is_rejected(monkeypatch, tmp_path, kind, new_name):
    base = _prepare_base(monkeypatch, tmp_path)
    mount_root = base / "shared" / "containers"
    mount_root.mkdir(parents=True)

    if kind == "legacy":
        current_root = mount_root / "admin" / "containers" / "old_data"
        current_root.mkdir(parents=True)
        restore_path = str(current_root)
    else:
        current_root = mount_root
        if kind == "exact":
            restore_path = str(current_root)
        elif kind == "dot":
            restore_path = str(current_root) + os.sep + "."
        elif kind == "trailing":
            restore_path = str(current_root) + os.sep
        else:
            alias = tmp_path / "containers_root_alias"
            os.symlink(current_root, alias, target_is_directory=True)
            restore_path = str(alias)

    monkeypatch.setenv("NODE_CONTAINERS_BASE", str(current_root))
    containers = FakeContainers()
    monkeypatch.setattr(
        extensions, "docker_client", FakeDockerClient(containers, FakeImages())
    )

    with pytest.raises(
        RuntimeError, match="restore mount path equals containers base"
    ):
        create_container(
            "admin",
            Container.Config_info(**_cfg(new_name)),
            root_password=ROOT_PW,
            restore_mount_path=restore_path,
        )

    assert containers.run_calls == []
    assert not (
        current_root / "admin" / "containers" / new_name
    ).exists()


def test_restore_valid_historical_subdir_still_recovers(monkeypatch, tmp_path):
    base = _prepare_base(monkeypatch, tmp_path)
    mount_root = base / "shared" / "containers"
    historical = mount_root / "admin" / "containers" / "old_data"
    historical.mkdir(parents=True)
    monkeypatch.setenv("NODE_CONTAINERS_BASE", str(mount_root))
    new_name = "recovered_new_c"
    containers = FakeContainers()
    monkeypatch.setattr(
        extensions, "docker_client", FakeDockerClient(containers, FakeImages())
    )

    result = create_container(
        "admin",
        Container.Config_info(**_cfg(new_name)),
        root_password=ROOT_PW,
        restore_mount_path=str(historical),
    )

    assert len(containers.run_calls) == 1
    assert os.path.samefile(result.bind_mount_path, historical)
    assert os.path.samefile(
        containers.run_calls[0][1]["mounts"][0]["Source"], historical
    )
    assert not (mount_root / "admin" / "containers" / new_name).exists()


def test_restore_mount_path_requires_containers_segment_and_existing_dir(
    monkeypatch, tmp_path
):
    base = _prepare_base(monkeypatch, tmp_path)

    def _client():
        return FakeDockerClient(FakeContainers(), FakeImages())

    no_segment = base / "admin" / "data" / "c1"
    no_segment.mkdir(parents=True)
    client = _client()
    monkeypatch.setattr(extensions, "docker_client", client)
    with pytest.raises(RuntimeError, match="without containers segment"):
        create_container(
            "admin",
            Container.Config_info(**_cfg("no_segment_c")),
            root_password=ROOT_PW,
            restore_mount_path=str(no_segment),
        )
    assert client.containers.run_calls == []

    missing = base / "admin" / "containers" / "missing"
    client = _client()
    monkeypatch.setattr(extensions, "docker_client", client)
    with pytest.raises(RuntimeError, match="does not exist"):
        create_container(
            "admin",
            Container.Config_info(**_cfg("missing_dir_c")),
            root_password=ROOT_PW,
            restore_mount_path=str(missing),
        )
    assert client.containers.run_calls == []

    link_parent = base / "admin" / "containers"
    link_parent.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = link_parent / "escape"
    os.symlink(outside, link, target_is_directory=True)
    client = _client()
    monkeypatch.setattr(extensions, "docker_client", client)
    with pytest.raises(RuntimeError, match="outside containers base"):
        create_container(
            "admin",
            Container.Config_info(**_cfg("symlink_c")),
            root_password=ROOT_PW,
            restore_mount_path=str(link),
        )
    assert client.containers.run_calls == []

    valid = base / "admin" / "containers" / "valid"
    valid.mkdir(parents=True)
    client = _client()
    monkeypatch.setattr(extensions, "docker_client", client)
    result = create_container(
        "admin",
        Container.Config_info(**_cfg("valid_restore_c")),
        root_password=ROOT_PW,
        restore_mount_path=str(valid),
    )
    assert len(client.containers.run_calls) == 1
    assert os.path.samefile(result.bind_mount_path, valid)
    assert os.path.samefile(
        client.containers.run_calls[0][1]["mounts"][0]["Source"], valid
    )


def test_occupied_name_rejected_without_run_or_mount_change(monkeypatch, tmp_path):
    base = _prepare_base(monkeypatch, tmp_path)
    restore = base / "admin" / "containers" / "old_c"
    restore.mkdir(parents=True)
    existing = FakeContainer(name="taken_c")
    containers = FakeContainers([existing])
    monkeypatch.setattr(
        extensions, "docker_client", FakeDockerClient(containers, FakeImages())
    )

    with pytest.raises(RuntimeError) as excinfo:
        create_container(
            "admin",
            Container.Config_info(**_cfg("taken_c")),
            root_password=ROOT_PW,
            restore_mount_path=str(restore),
        )

    message = str(excinfo.value)
    assert "container taken_c already exists" in message
    assert "taken_c_" not in message.replace("taken_c already exists", "")
    assert containers.run_calls == []


def test_root_password_set_before_sshd_gate(monkeypatch, tmp_path):
    _prepare_base(monkeypatch, tmp_path)
    events: list = []
    containers = _EventContainers(events)
    docker = FakeDockerClient(containers, FakeImages())
    docker.api = _EventAPI(events)
    monkeypatch.setattr(extensions, "docker_client", docker)

    create_container(
        "admin",
        Container.Config_info(**_cfg("order_c")),
        root_password=ROOT_PW,
    )

    chpasswd_index = next(
        index
        for index, event in enumerate(events)
        if event[0] == "chpasswd" and event[1] == ["chpasswd"]
    )
    sshd_index = next(
        index
        for index, event in enumerate(events)
        if event[0] == "exec" and "/usr/sbin/sshd" in _json(event[1])
    )
    assert chpasswd_index < sshd_index
    assert docker.api.started[0]["socket"].sent == b"root:Root#Password9\n"


def test_create_password_failure_logs_redacted_without_fallback(
    monkeypatch, tmp_path, capsys, caplog
):
    _prepare_base(monkeypatch, tmp_path)
    cache = _new_cache()
    docker = PasswordFakeDockerClient(FakeContainers(), FakeImages(), exit_code=1)
    monkeypatch.setattr(extensions, "docker_client", docker)
    http = TestClient(create_app())
    name = "create_pw_failure"

    response = http.post("/api/create_container", json=_create_payload(name))
    assert response.status_code == 200
    _wait_for(
        lambda: (cache.get_state(name).get("last_action") or {}).get("phase")
        == "failed",
        message="create password failure did not fail",
    )
    state = cache.get_state(name)
    assert state["last_action"]["error_reason"] == "create_failed"
    assert len(docker.api.created) == 1
    assert docker.api.created[0]["cmd"] == ["chpasswd"]

    text = response.text + capsys.readouterr().out + caplog.text
    assert ROOT_PW.get_secret_value() not in text
    assert "admin123" not in text
    assert "owner123" not in text
    http.close()


def test_create_response_exact_fields_no_credentials(monkeypatch):
    _new_cache()
    monkeypatch.setattr(api_module, "container_exists", lambda name: False)
    monkeypatch.setattr(
        api_module,
        "create_container",
        lambda owner_name, cfg, **kwargs: CreateContainerReturn("cid", cfg.name),
    )
    http = TestClient(create_app())
    name = "exact_fields_c"

    response = http.post("/api/create_container", json=_create_payload(name))

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "success",
        "container_status",
        "container_name",
        "action_ref",
    }
    assert "root_password" not in response.text
    assert "password" not in response.text
    assert "credentials" not in response.text
    assert response.headers["Cache-Control"] == "no-store"
    http.close()


def test_create_logs_carry_no_password_or_credential_entry(
    monkeypatch, tmp_path, caplog
):
    _prepare_base(monkeypatch, tmp_path)
    cache = _new_cache()
    containers = _RegisteredContainers()
    docker = PasswordFakeDockerClient(containers, FakeImages())
    monkeypatch.setattr(extensions, "docker_client", docker)
    caplog.set_level(0)
    http = TestClient(create_app())
    name = "create_logs_c"

    response = http.post("/api/create_container", json=_create_payload(name))
    assert response.status_code == 200
    _wait_for(
        lambda: (cache.get_state(name).get("last_action") or {}).get("phase")
        == "confirmed",
        message="create logs did not confirm",
    )

    text = caplog.text
    assert "create_container called" in text
    assert "create_container background started" in text
    assert "create_container service complete" in text
    assert ROOT_PW.get_secret_value() not in text
    assert "root_password" not in text
    assert "credentials" not in text
    assert "password=" not in text
    assert "chpasswd" not in text
    http.close()


def test_add_collaborator_logs_no_echo_or_chpasswd_command(monkeypatch, capsys, caplog):
    container = PasswordFakeContainer("c1", user_exists=True)
    client = PasswordFakeDockerClient(FakeContainers([container]), FakeImages())
    monkeypatch.setattr(extensions, "docker_client", client)

    assert add_collaborator("c1", "u1", ROLE.ADMIN, password=PW) is True

    text = capsys.readouterr().out + caplog.text
    assert PW.get_secret_value() not in text
    assert "chpasswd" not in text
    assert "echo" not in text
    assert "u1:Role#Password9" not in text
    assert client.api.started[0]["socket"].sent == b"u1:Role#Password9\n"


def test_root_handover_no_new_password_audit(monkeypatch, capsys, caplog):
    container = PasswordFakeContainer("c1", user_exists=True)
    client = PasswordFakeDockerClient(FakeContainers([container]), FakeImages())
    monkeypatch.setattr(extensions, "docker_client", client)
    http = TestClient(create_app())

    first = http.post(
        "/api/update_role",
        json={
            "config": {
                "container_name": "c1",
                "user_name": "old_root",
                "updated_role": "admin",
                "password": PW.get_secret_value(),
            }
        },
    )
    second = http.post(
        "/api/update_role",
        json={
            "config": {
                "container_name": "c1",
                "user_name": "target",
                "updated_role": "root",
                "root_password": ROOT_PW.get_secret_value(),
            }
        },
    )

    assert first.status_code == 200 and first.json()["success"] is True
    assert second.status_code == 200 and second.json()["success"] is True
    text = capsys.readouterr().out + caplog.text
    assert "password=" not in text
    assert "ADD_COLLABORATOR" not in text
    assert "UPDATE_COLLABORATOR_ROLE" not in text
    assert PW.get_secret_value() not in text
    assert ROOT_PW.get_secret_value() not in text
    http.close()


def test_sync_password_routes_survive_asgi_disconnect(monkeypatch):
    """ASGI request cancellation does not cancel an entered sync chpasswd.

    The request task is cancelled while the real app is in a sync service thread.
    A test-only observer calls the original service and signals when it returns;
    no full service replacement is used. The worker's release and the finished
    event are both in finally paths so a failed assertion cannot leak a thread.
    """

    cases = [
        (
            "/api/add_collaborator",
            {
                "config": {
                    "container_name": "c1",
                    "user_name": "u1",
                    "role": "admin",
                    "password": PW.get_secret_value(),
                }
            },
            b"u1:Role#Password9\n",
            "add_collaborator",
        ),
        (
            "/api/update_role",
            {
                "config": {
                    "container_name": "c1",
                    "user_name": "target",
                    "updated_role": "root",
                    "root_password": ROOT_PW.get_secret_value(),
                }
            },
            b"root:Root#Password9\n",
            "update_role",
        ),
        (
            "/api/reset_container_password",
            {
                "config": {
                    "container_name": "c1",
                    "user_name": "root",
                    "password": PW.get_secret_value(),
                }
            },
            b"root:Role#Password9\n",
            "reset_container_password",
        ),
    ]

    # Observe real service completion without replacing its logic. Each wrapper
    # calls the original imported service and sets its own finished event.
    service_events = {
        name: threading.Event()
        for name in ("add_collaborator", "update_role", "reset_container_password")
    }
    for service_name, event in service_events.items():
        original = getattr(api_module, service_name)

        def _observed(original=original, event=event):
            def wrapped(*args, **kwargs):
                try:
                    return original(*args, **kwargs)
                finally:
                    event.set()

            return wrapped

        monkeypatch.setattr(api_module, service_name, _observed())

    async def run_case(path, payload, expected_stdin, service_name):
        entered = threading.Event()
        release = threading.Event()
        finished = service_events[service_name]
        finished.clear()
        container = PasswordFakeContainer("c1", user_exists=True)
        docker = PasswordFakeDockerClient(FakeContainers([container]), FakeImages())
        blocking_api = _BlockingExecAPI(entered, release)
        docker.api = blocking_api
        monkeypatch.setattr(extensions, "docker_client", docker)
        _new_cache()
        app = create_app()
        transport = httpx2.ASGITransport(app=app)
        http = httpx2.AsyncClient(transport=transport, base_url="http://test")
        task = asyncio.create_task(http.post(path, json=payload))
        try:
            assert await asyncio.to_thread(entered.wait, 3), f"service not entered: {path}"
            task.cancel()
            release.set()
            assert await asyncio.to_thread(finished.wait, 3), f"service not finished: {path}"
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            release.set()
            if not task.done():
                task.cancel()
            with contextlib.suppress(BaseException):
                await task
            await http.aclose()

        assert len(blocking_api.created) == 1, path
        assert blocking_api.created[0]["cmd"] == ["chpasswd"], path
        assert blocking_api.started[0]["socket"].sent == expected_stdin, path

    for path, payload, expected_stdin, service_name in cases:
        asyncio.run(run_case(path, payload, expected_stdin, service_name))

    # Failure path: reset raises RuntimeError -> 500, not a fabricated success.
    async def run_failure():
        entered = threading.Event()
        release = threading.Event()
        finished = service_events["reset_container_password"]
        finished.clear()
        container = PasswordFakeContainer("c1", user_exists=True)
        docker = PasswordFakeDockerClient(FakeContainers([container]), FakeImages())
        blocking_api = _BlockingExecAPI(entered, release, exit_code=1)
        docker.api = blocking_api
        monkeypatch.setattr(extensions, "docker_client", docker)
        _new_cache()
        app = create_app()
        sent: list[dict] = []

        async def captured_app(scope, receive, send):
            async def capture(message):
                sent.append(message)
                await send(message)

            await app(scope, receive, capture)

        transport = httpx2.ASGITransport(app=captured_app)
        http = httpx2.AsyncClient(transport=transport, base_url="http://test")
        task = asyncio.create_task(
            http.post(
                "/api/reset_container_password",
                json={
                    "config": {
                        "container_name": "c1",
                        "user_name": "root",
                        "password": PW.get_secret_value(),
                    }
                },
            )
        )
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            task.cancel()
            release.set()
            assert await asyncio.to_thread(finished.wait, 3)
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            release.set()
            if not task.done():
                task.cancel()
            with contextlib.suppress(BaseException):
                await task
            await http.aclose()

        assert len(blocking_api.created) == 1
        statuses = [
            message["status"]
            for message in sent
            if message.get("type") == "http.response.start"
        ]
        assert 200 not in statuses
        body = "".join(
            message.get("body", b"").decode("utf-8", "replace")
            for message in sent
            if message.get("type") == "http.response.body"
        )
        assert '"success":true' not in body
        assert PW.get_secret_value() not in body

        # Separately prove the chosen failure shape: RuntimeError -> 500, not
        # the legitimate 200 + success:false path used when a service returns False.
        container2 = PasswordFakeContainer("c1", user_exists=True)
        docker2 = PasswordFakeDockerClient(
            FakeContainers([container2]), FakeImages(), exit_code=1
        )
        monkeypatch.setattr(extensions, "docker_client", docker2)
        _new_cache()
        app2 = create_app()
        http2 = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app2), base_url="http://test"
        )
        try:
            failed = await http2.post(
                "/api/reset_container_password",
                json={
                    "config": {
                        "container_name": "c1",
                        "user_name": "root",
                        "password": PW.get_secret_value(),
                    }
                },
            )
            assert failed.status_code == 500
            assert failed.json()["error_reason"] == "reset_failed"
            assert failed.json()["success"] == 0
        finally:
            await http2.aclose()

    asyncio.run(run_failure())


def test_create_disconnect_keeps_background_password_step(monkeypatch, tmp_path):
    """Accepted create continues after the ASGI client is closed."""

    _prepare_base(monkeypatch, tmp_path)
    cache = _new_cache()
    entered = threading.Event()
    release = threading.Event()
    containers = _BlockingContainers(entered, release)
    docker = PasswordFakeDockerClient(containers, FakeImages())
    monkeypatch.setattr(extensions, "docker_client", docker)
    name = "disconnect_create_c"

    async def run():
        app = create_app()
        transport = httpx2.ASGITransport(app=app)
        http = httpx2.AsyncClient(transport=transport, base_url="http://test")
        task = asyncio.create_task(
            http.post("/api/create_container", json=_create_payload(name))
        )
        assert await asyncio.to_thread(entered.wait, 3)
        response = await task
        assert response.status_code == 200
        await http.aclose()
        release.set()
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            if (cache.get_state(name).get("last_action") or {}).get("phase") == "confirmed":
                break
            await asyncio.sleep(0.01)
        assert cache.get_state(name)["last_action"]["phase"] == "confirmed"

    asyncio.run(run())

    assert len(containers.run_calls) == 1
    assert len(docker.api.created) == 1
    assert docker.api.started[0]["socket"].sent == b"root:Root#Password9\n"
    assert len(containers.run_calls) == 1


def test_password_routes_sibling_missing_422_redacted(monkeypatch, tmp_path):
    _prepare_base(monkeypatch, tmp_path)
    cache = _new_cache()
    containers = _RegisteredContainers()
    monkeypatch.setattr(
        extensions, "docker_client", FakeDockerClient(containers, FakeImages())
    )
    http = TestClient(create_app())

    cases = [
        (
            "/api/create_container",
            {
                "owner_name": "admin",
                "root_password": ROOT_PW.get_secret_value(),
                "config": {
                    "gpu_list": [],
                    "cpu_number": 2,
                    "memory": 4,
                    "shared_memory": 0,
                    "port": 2233,
                    "image": "ubuntu:22.04",
                },
            },
            ROOT_PW,
        ),
        (
            "/api/add_collaborator",
            {
                "config": {
                    "user_name": "u1",
                    "role": "admin",
                    "password": PW.get_secret_value(),
                }
            },
            PW,
        ),
        (
            "/api/update_role",
            {
                "config": {
                    "user_name": "target",
                    "updated_role": "root",
                    "root_password": ROOT_PW.get_secret_value(),
                }
            },
            ROOT_PW,
        ),
        (
            "/api/reset_container_password",
            {
                "config": {
                    "user_name": "root",
                    "password": PW.get_secret_value(),
                }
            },
            PW,
        ),
    ]

    for path, payload, secret in cases:
        response = http.post(path, json=payload)
        assert response.status_code == 422, (path, response.text)
        assert response.headers["Cache-Control"] == "no-store"
        assert "input" not in response.text and "ctx" not in response.text
        assert "url" not in response.text
        assert secret.get_secret_value() not in response.text
        _assert_validation_details(response)

    assert containers.run_calls == []
    http.close()


def test_chpasswd_failure_does_not_retry(monkeypatch):
    container = PasswordFakeContainer("c1")
    client = install_password_docker(monkeypatch, container, exit_code=1)

    with pytest.raises(RuntimeError, match="chpasswd failed"):
        _set_account_password(container, "u1", PW)

    assert len(client.api.created) == 1
    assert client.api.created[0]["cmd"] == ["chpasswd"]
    assert PW.get_secret_value() not in str(client.api.created[0])
