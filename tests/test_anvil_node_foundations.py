"""Anvil Node 基础能力缺口测试。

本文件只承载 complete-anvil-node-foundation-mappings 计划中的 13 条缺口测试，
不修改既有测试目录、夹具或业务实现。
"""

import importlib
import json
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from FuxiYu_NodeKernel import config as config_module
from FuxiYu_NodeKernel import create_app, extensions
from FuxiYu_NodeKernel.network import api as api_module
from FuxiYu_NodeKernel.network import wss as wss_module
from FuxiYu_NodeKernel.schemas.common import (
    ApiErrorResponse,
    EmptyConfig,
    ErrorResponses,
    SuccessResponse,
)

from .conftest import FakeDockerClient


COLLAB_PASSWORD = "Collab#Password9"


@pytest.fixture()
def client(monkeypatch):
    """本文件专用的最小 TestClient 夹具，不改既有测试模块。"""

    monkeypatch.setattr(extensions, "docker_client", FakeDockerClient())
    return TestClient(create_app())


def _patched_service(monkeypatch, name, fn):
    monkeypatch.setattr(api_module, name, fn)


def test_empty_config_accepts_empty_mapping_and_rejects_non_mapping():
    model = EmptyConfig()

    assert EmptyConfig.model_fields == {}
    assert model.model_dump() == {}
    assert EmptyConfig.model_validate({}).model_dump() == {}

    for value in ([], "not-a-mapping", 1):
        with pytest.raises(ValidationError):
            EmptyConfig.model_validate(value)


def test_api_error_response_defaults_and_required_error():
    assert set(ApiErrorResponse.model_fields) == {"success", "error", "error_reason"}

    response = ApiErrorResponse(error="boom")
    assert response.success == 0
    assert response.error == "boom"
    assert response.error_reason is None

    with pytest.raises(ValidationError):
        ApiErrorResponse()
    with pytest.raises(ValidationError):
        ApiErrorResponse(error=123)


def test_success_response_default_and_int_bool_forms():
    assert set(SuccessResponse.model_fields) == {"success"}
    assert SuccessResponse().success == 1
    assert SuccessResponse(success=0).success == 0
    assert SuccessResponse(success=True).success is True
    assert SuccessResponse(success=False).success is False

    for value in ([], {}, object()):
        with pytest.raises(ValidationError):
            SuccessResponse(success=value)


def test_success_marker_is_independent_of_http_status(client, monkeypatch):
    _patched_service(monkeypatch, "add_collaborator", lambda *a, **k: False)
    add_resp = client.post(
        "/api/add_collaborator",
        json={
            "config": {
                "container_name": "c1",
                "user_name": "u1",
                "role": "admin",
                "password": COLLAB_PASSWORD,
            }
        },
    )
    assert add_resp.status_code == 200
    assert add_resp.json()["success"] is False

    _patched_service(monkeypatch, "remove_collaborator", lambda *a: True)
    remove_ok = client.post(
        "/api/remove_collaborator",
        json={"config": {"container_name": "c1", "user_name": "u1"}},
    )
    assert remove_ok.status_code == 200
    assert remove_ok.json()["success"] == 1

    _patched_service(monkeypatch, "remove_collaborator", lambda *a: False)
    remove_failed = client.post(
        "/api/remove_collaborator",
        json={"config": {"container_name": "c1", "user_name": "u1"}},
    )
    assert remove_failed.status_code == 500
    assert remove_failed.json()["success"] == 0


def test_error_responses_declaration_uses_api_error_model():
    assert set(ErrorResponses.INVALID_JSON) == {400}
    assert set(ErrorResponses.INTERNAL_ERROR) == {500}

    for entry in (ErrorResponses.INVALID_JSON[400], ErrorResponses.INTERNAL_ERROR[500]):
        assert entry["model"] is ApiErrorResponse
        assert entry["description"]

    envelope = ApiErrorResponse.model_validate(
        {"success": 0, "error": "invalid json", "error_reason": "invalid_json"}
    )
    assert envelope.success == 0
    assert envelope.error == "invalid json"
    assert envelope.error_reason == "invalid_json"


def test_issue_node_uid_request_requires_uid():
    assert set(wss_module.IssueNodeUidRequest.model_fields) == {"uid"}
    assert wss_module.IssueNodeUidRequest(uid="node-uid").uid == "node-uid"

    with pytest.raises(ValidationError):
        wss_module.IssueNodeUidRequest()
    with pytest.raises(ValidationError):
        wss_module.IssueNodeUidRequest(uid=123)


def test_node_identity_is_frozen_and_identity_file_override(monkeypatch, tmp_path):
    identity = wss_module.NodeIdentity(uid="node-uid")

    assert tuple(field.name for field in fields(wss_module.NodeIdentity)) == ("uid",)
    assert wss_module.NodeIdentity.__dataclass_params__.frozen is True
    with pytest.raises(FrozenInstanceError):
        identity.uid = "other"
    assert not hasattr(identity, "certificate_fingerprint")
    assert "certificate_fingerprint" not in {
        field.name for field in fields(wss_module.NodeIdentity)
    }

    identity_file = tmp_path / "identity.json"
    monkeypatch.delenv("NODE_UID", raising=False)
    monkeypatch.setenv("NODE_IDENTITY_FILE", str(identity_file))

    wss_module.save_node_identity(identity)

    assert identity_file.exists()
    assert json.loads(identity_file.read_text(encoding="utf-8")) == {"uid": "node-uid"}
    assert wss_module.load_node_identity() == identity


def test_node_certificate_files_are_paths_and_frozen(monkeypatch, tmp_path):
    cert_file = tmp_path / "node_cert.pem"
    key_file = tmp_path / "node_key.pem"
    monkeypatch.setenv("NODE_TLS_CERT_FILE", str(cert_file))
    monkeypatch.setenv("NODE_TLS_KEY_FILE", str(key_file))

    files = wss_module.ensure_self_signed_certificate()

    assert tuple(field.name for field in fields(wss_module.NodeCertificateFiles)) == (
        "cert_file",
        "key_file",
    )
    assert wss_module.NodeCertificateFiles.__dataclass_params__.frozen is True
    assert isinstance(files.cert_file, Path)
    assert isinstance(files.key_file, Path)
    assert files.cert_file == cert_file
    assert files.key_file == key_file
    assert cert_file.exists() and key_file.exists()
    assert cert_file.read_text(encoding="utf-8").startswith("-----BEGIN CERTIFICATE-----")
    assert "BEGIN PRIVATE KEY" in key_file.read_text(encoding="utf-8")
    assert not hasattr(files, "certificate_pem")
    assert not hasattr(files, "private_key")

    with pytest.raises(FrozenInstanceError):
        files.cert_file = tmp_path / "other.pem"


def test_enrollment_profile_contains_static_hardware_and_issued_uid(
    client, monkeypatch, tmp_path
):
    monkeypatch.setenv("NODE_TLS_CERT_FILE", str(tmp_path / "node_cert.pem"))
    monkeypatch.setenv("NODE_TLS_KEY_FILE", str(tmp_path / "node_key.pem"))
    monkeypatch.setenv("NODE_IDENTITY_FILE", str(tmp_path / "identity.json"))
    monkeypatch.delenv("NODE_UID", raising=False)

    profile_resp = client.get("/api/node_identity/enrollment_profile")
    assert profile_resp.status_code == 200
    profile = profile_resp.json()
    assert profile["uid"] is None
    assert profile["identity_initialized"] is False
    assert isinstance(profile["hardware"], dict)
    assert set(profile["hardware"]) == set(wss_module.static_sys_snapshot())
    assert isinstance(profile["hardware"]["cpu"], dict)
    assert isinstance(profile["hardware"]["memory"], dict)
    assert isinstance(profile["hardware"]["gpu"], list)
    assert isinstance(profile["hardware"]["disk"], dict)
    assert "certificate_fingerprint" not in profile

    issue_resp = client.post(
        "/api/node_identity/issue_uid", json={"uid": "node-test-uid"}
    )
    assert issue_resp.status_code == 200
    issued = issue_resp.json()
    assert issued["success"] == 1
    assert issued["uid"] == "node-test-uid"
    assert issued["identity_initialized"] is True
    assert "certificate_fingerprint" not in issued

    after = client.get("/api/node_identity/enrollment_profile").json()
    assert after["uid"] == "node-test-uid"
    assert after["identity_initialized"] is True
    assert isinstance(after["hardware"], dict)
    assert set(after["hardware"]) == set(wss_module.static_sys_snapshot())
    assert "certificate_fingerprint" not in after


def test_net_config_declares_only_node_port(monkeypatch):
    try:
        with monkeypatch.context() as local:
            local.delenv("NODE_PORT", raising=False)
            importlib.reload(config_module)

            names = [name for name in vars(config_module.NetConfig) if name.isupper()]
            assert names == ["NODE_PORT"]
            assert isinstance(config_module.NetConfig.NODE_PORT, int)
            assert 1 <= config_module.NetConfig.NODE_PORT <= 65535
            assert not any("CTRL" in name or "HOST" in name for name in names)
    finally:
        importlib.reload(config_module)


def test_port_config_default_range_constants(monkeypatch):
    try:
        with monkeypatch.context() as local:
            local.delenv("NODE_PORT_RANGE_START", raising=False)
            local.delenv("NODE_PORT_RANGE_END", raising=False)
            importlib.reload(config_module)

            start = config_module.PortConfig.NODE_PORT_RANGE_START
            end = config_module.PortConfig.NODE_PORT_RANGE_END
            assert start == 20000
            assert end == 29999
            assert start < end
    finally:
        importlib.reload(config_module)


def test_key_config_declares_paths_without_secret_material():
    names = ("PUBLIC_KEY_PATH", "PRIVATE_KEY_PATH", "PUBLIC_KEY_CONTROL")
    for name in names:
        value = getattr(config_module.KeyConfig, name)
        assert isinstance(value, str)
        assert value.strip()
        assert "BEGIN" not in value
        assert "PRIVATE KEY" not in value


def test_app_config_inherits_key_config_and_env_overrides(monkeypatch, tmp_path):
    public_key = tmp_path / "public_test.pem"
    private_key = tmp_path / "private_test.pem"
    secret = "test-only-secret-not-real"

    try:
        with monkeypatch.context() as local:
            local.setenv("PUBLIC_KEY_PATH", str(public_key))
            local.setenv("PRIVATE_KEY_PATH", str(private_key))
            local.setenv("SECRET_KEY", secret)
            importlib.reload(config_module)

            app_config = config_module.AppConfig
            key_config = config_module.KeyConfig
            assert issubclass(app_config, key_config)
            assert "PUBLIC_KEY_PATH" in vars(app_config)
            assert "PRIVATE_KEY_PATH" in vars(app_config)
            assert "SECRET_KEY" in vars(app_config)
            assert app_config.PUBLIC_KEY_PATH == str(public_key)
            assert app_config.PRIVATE_KEY_PATH == str(private_key)
            assert app_config.SECRET_KEY == secret
            assert app_config.PUBLIC_KEY_PATH != key_config.PUBLIC_KEY_PATH
            assert app_config.PRIVATE_KEY_PATH != key_config.PRIVATE_KEY_PATH
            assert app_config.PUBLIC_KEY_CONTROL == key_config.PUBLIC_KEY_CONTROL
    finally:
        importlib.reload(config_module)
