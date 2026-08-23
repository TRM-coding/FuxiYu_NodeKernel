import time
import ssl
import ipaddress

import pytest
from cryptography import x509
from cryptography.x509.oid import ExtensionOID, ExtendedKeyUsageOID
from fastapi.testclient import TestClient

from FuxiYu_NodeKernel import create_app, extensions
from FuxiYu_NodeKernel.network import api as api_module
from FuxiYu_NodeKernel.network import wss as wss_module
from FuxiYu_NodeKernel.services.container_service import CreateContainerReturn

from .conftest import FakeDockerClient


VALID_CFG = {
    "gpu_list": [],
    "cpu_number": 2,
    "memory": 4,
    "shared_memory": 0,
    "name": "c1",
    "port": 2233,
    "image": "ubuntu:22.04",
}


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(extensions, "docker_client", FakeDockerClient())
    app = create_app()
    return TestClient(app)


def _patched_service(monkeypatch, name, fn):
    monkeypatch.setattr(api_module, name, fn)


def test_openapi_contains_container_endpoints(client):
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    paths = resp.json()["paths"]
    assert "/api/create_container" in paths
    assert "/api/check_disk_usage" in paths
    assert "/api/node_identity/enrollment_profile" in paths
    assert "/api/node_identity/issue_uid" in paths


def test_node_identity_enrollment_and_issue_uid(client, monkeypatch, tmp_path):
    monkeypatch.setenv("NODE_TLS_CERT_FILE", str(tmp_path / "node_cert.pem"))
    monkeypatch.setenv("NODE_TLS_KEY_FILE", str(tmp_path / "node_key.pem"))
    monkeypatch.setenv("NODE_IDENTITY_FILE", str(tmp_path / "identity.json"))

    profile_resp = client.get("/api/node_identity/enrollment_profile")
    assert profile_resp.status_code == 200
    profile = profile_resp.json()
    assert profile["uid"] is None
    assert profile["identity_initialized"] is False
    assert "certificate_fingerprint" not in profile

    issue_resp = client.post("/api/node_identity/issue_uid", json={"uid": "node-test-uid"})
    assert issue_resp.status_code == 200
    issued = issue_resp.json()
    assert issued["success"] == 1
    assert issued["uid"] == "node-test-uid"
    assert issued["identity_initialized"] is True
    assert "certificate_fingerprint" not in issued


def test_wss_ssl_context_loads_node_client_certificate(monkeypatch, tmp_path):
    monkeypatch.setenv("NODE_TLS_CERT_FILE", str(tmp_path / "node_cert.pem"))
    monkeypatch.setenv("NODE_TLS_KEY_FILE", str(tmp_path / "node_key.pem"))
    monkeypatch.setenv("NODE_CTRL_TLS_INSECURE", "1")
    monkeypatch.setenv("NODE_WSS_CLIENT_CERT_ENABLED", "1")

    context = wss_module.build_wss_ssl_context()

    assert isinstance(context, ssl.SSLContext)
    assert (tmp_path / "node_cert.pem").exists()
    assert (tmp_path / "node_key.pem").exists()
    assert context.verify_mode == ssl.CERT_NONE


def test_node_self_signed_certificate_is_valid_pin_anchor(monkeypatch, tmp_path):
    monkeypatch.setenv("NODE_TLS_CERT_FILE", str(tmp_path / "node_cert.pem"))
    monkeypatch.setenv("NODE_TLS_KEY_FILE", str(tmp_path / "node_key.pem"))

    files = wss_module.ensure_self_signed_certificate()
    cert = x509.load_pem_x509_certificate(files.cert_file.read_bytes())
    basic = cert.extensions.get_extension_for_oid(ExtensionOID.BASIC_CONSTRAINTS).value
    san = cert.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value
    eku = cert.extensions.get_extension_for_oid(ExtensionOID.EXTENDED_KEY_USAGE).value

    assert basic.ca is True
    assert "localhost" in san.get_values_for_type(x509.DNSName)
    assert ipaddress.ip_address("127.0.0.1") in san.get_values_for_type(x509.IPAddress)
    assert ExtendedKeyUsageOID.SERVER_AUTH in eku
    assert ExtendedKeyUsageOID.CLIENT_AUTH in eku


def test_create_container_success(client, monkeypatch):
    calls = []

    def _stub(owner_name, cfg, public_key=None):
        calls.append((owner_name, cfg, public_key))
        return CreateContainerReturn("cid123", cfg.name)

    _patched_service(monkeypatch, "container_exists", lambda name: False)
    _patched_service(monkeypatch, "create_container", _stub)

    payload = {"owner_name": "admin", "config": VALID_CFG}
    resp = client.post("/api/create_container", json=payload)

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] == 1
    assert body["container_status"] == "creating"
    time.sleep(0.1)
    assert len(calls) == 1
    assert calls[0][0] == "admin"
    assert calls[0][1].name == "c1"


def test_create_container_existing_returns_409(client, monkeypatch):
    _patched_service(monkeypatch, "container_exists", lambda name: True)
    payload = {"owner_name": "admin", "config": VALID_CFG}
    resp = client.post("/api/create_container", json=payload)
    assert resp.status_code == 409
    assert resp.json()["error_reason"] == "container_exists"


def test_create_container_invalid_config_422(client):
    bad_cfg = {**VALID_CFG, "port": "not-a-port"}
    payload = {"owner_name": "admin", "config": bad_cfg}
    resp = client.post("/api/create_container", json=payload)
    assert resp.status_code == 422


def test_remove_container_success(client, monkeypatch):
    _patched_service(monkeypatch, "remove_container", lambda name: 0)
    resp = client.post("/api/remove_container", json={"config": {"container_name": "c1"}})
    assert resp.status_code == 200
    assert resp.json()["success"] == 1


def test_remove_container_not_found_404(client, monkeypatch):
    _patched_service(monkeypatch, "remove_container", lambda name: 1)
    resp = client.post("/api/remove_container", json={"config": {"container_name": "ghost"}})
    assert resp.status_code == 404
    assert resp.json()["error_reason"] == "not_found"


def test_remove_container_missing_name_400(client):
    resp = client.post("/api/remove_container", json={"config": {}})
    assert resp.status_code == 400
    assert resp.json()["error_reason"] == "missing_container_name"


def test_container_status_online(client, monkeypatch):
    _patched_service(
        monkeypatch,
        "list_container_status",
        lambda: {"c1": {"source": "cache", "status": "online", "cache_updated_at": "2026-01-01T00:00:00"}},
    )
    resp = client.post("/api/container_status", json={"config": {"container_name": "c1"}})
    assert resp.status_code == 200
    assert resp.json()["container_status"] == "online"


def test_container_status_pending(client, monkeypatch):
    _patched_service(monkeypatch, "list_container_status", lambda: {"c1": {"source": "pending", "status": "starting"}})
    resp = client.post("/api/container_status", json={"config": {"container_name": "c1"}})
    assert resp.status_code == 200
    assert resp.json()["container_status"] == "starting"


def test_container_status_miss_unknown(client, monkeypatch):
    _patched_service(monkeypatch, "list_container_status", lambda: {})
    resp = client.post("/api/container_status", json={"config": {"container_name": "ghost"}})
    assert resp.status_code == 200
    assert resp.json()["container_status"] == "unknown"


def test_machine_status_online(client):
    resp = client.post("/api/machine_status", json={"config": {}})
    assert resp.status_code == 200
    assert resp.json()["machine_status"] == "online"


def test_add_collaborator_success(client, monkeypatch):
    _patched_service(monkeypatch, "add_collaborator", lambda *a: True)
    payload = {"config": {"container_name": "c1", "user_name": "u1", "role": "admin"}}
    resp = client.post("/api/add_collaborator", json=payload)
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert resp.json()["decrypted_message"] == payload


def test_add_collaborator_invalid_role_422(client):
    payload = {"config": {"container_name": "c1", "user_name": "u1", "role": "hacker"}}
    resp = client.post("/api/add_collaborator", json=payload)
    assert resp.status_code == 422


def test_remove_collaborator_success(client, monkeypatch):
    _patched_service(monkeypatch, "remove_collaborator", lambda *a: True)
    payload = {"config": {"container_name": "c1", "user_name": "u1"}}
    resp = client.post("/api/remove_collaborator", json=payload)
    assert resp.status_code == 200
    assert resp.json()["success"] == 1


def test_update_role_success(client, monkeypatch):
    _patched_service(monkeypatch, "update_role", lambda *a: True)
    payload = {"config": {"container_name": "c1", "user_name": "u1", "updated_role": "root"}}
    resp = client.post("/api/update_role", json=payload)
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert resp.json()["decrypted_message"] == payload


def test_update_role_invalid_role_422(client):
    payload = {"config": {"container_name": "c1", "user_name": "u1", "updated_role": "emperor"}}
    resp = client.post("/api/update_role", json=payload)
    assert resp.status_code == 422


def test_start_container_success(client, monkeypatch):
    _patched_service(monkeypatch, "start_container", lambda name: True)
    resp = client.post("/api/start_container", json={"config": {"container_name": "c1"}})
    assert resp.status_code == 200
    assert resp.json()["container_status"] == "starting"
    time.sleep(0.1)
    assert extensions.status_cache.get_state("c1")["status"] == "online"


def test_stop_container_success(client, monkeypatch):
    _patched_service(monkeypatch, "stop_container", lambda name: True)
    resp = client.post("/api/stop_container", json={"config": {"container_name": "c1"}})
    assert resp.status_code == 200
    assert resp.json()["container_status"] == "stopping"
    time.sleep(0.1)
    assert extensions.status_cache.get_state("c1")["status"] == "offline"


def test_restart_container_success(client, monkeypatch):
    _patched_service(monkeypatch, "restart_container", lambda name: True)
    resp = client.post("/api/restart_container", json={"config": {"container_name": "c_restart"}})
    assert resp.status_code == 200
    assert resp.json()["container_status"] == "restarting"
    time.sleep(0.1)
    state = extensions.status_cache.get_state("c_restart")
    assert state["status"] == "restarting"
    assert extensions.status_cache.get("c_restart")["ready_check"] is True


def test_restart_container_waits_for_sshd_probe_before_online(client, monkeypatch):
    _patched_service(monkeypatch, "restart_container", lambda name: True)
    monkeypatch.setattr(extensions.status_cache, "_probe_sshd", lambda name: True)

    resp = client.post("/api/restart_container", json={"config": {"container_name": "c_restart_probe"}})

    assert resp.status_code == 200
    time.sleep(0.1)
    for name, entry in list(extensions.status_cache.snapshot().items()):
        if entry.get("ready_check") and extensions.status_cache._probe_sshd(name):
            extensions.status_cache.update(name, "online")
    assert extensions.status_cache.get_state("c_restart_probe")["status"] == "online"


def test_pause_container_success(client, monkeypatch):
    _patched_service(monkeypatch, "pause_container", lambda name, action: True)
    payload = {"config": {"container_name": "c1", "action": "pause"}}
    resp = client.post("/api/pause_container", json=payload)
    assert resp.status_code == 200
    assert resp.json()["container_status"] == "pausing"
    time.sleep(0.1)
    assert extensions.status_cache.get_state("c1")["status"] == "paused"


def test_unpause_container_success(client, monkeypatch):
    _patched_service(monkeypatch, "pause_container", lambda name, action: True)
    payload = {"config": {"container_name": "c1", "action": "unpause"}}
    resp = client.post("/api/pause_container", json=payload)
    assert resp.status_code == 200
    assert resp.json()["container_status"] == "unpausing"
    time.sleep(0.1)
    assert extensions.status_cache.get_state("c1")["status"] == "online"


def test_container_last_ssh_time_success(client, monkeypatch):
    _patched_service(
        monkeypatch,
        "list_last_ssh",
        lambda: {"c1": {"last_ssh_connect_time": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00"}},
    )
    resp = client.post("/api/container_last_ssh_time", json={"config": {"container_name": "c1"}})
    assert resp.status_code == 200
    assert resp.json()["last_ssh_connect_time"] == "2026-01-01T00:00:00"


def test_container_last_ssh_time_not_collected_returns_404(client, monkeypatch):
    _patched_service(monkeypatch, "list_last_ssh", lambda: {})
    resp = client.post("/api/container_last_ssh_time", json={"config": {"container_name": "c1"}})
    assert resp.status_code == 404


def test_check_disk_usage_success(client, monkeypatch):
    _patched_service(
        monkeypatch,
        "list_disk_usage",
        lambda: {
            "machine_disk": {"total_gb": 100, "used_gb": 20, "free_gb": 80, "percent": 20},
            "containers": {"c1": {"container_name": "c1", "total_bytes": 123}},
        },
    )
    resp = client.post("/api/check_disk_usage", json={"config": {"container_name": "c1"}})
    assert resp.status_code == 200
    assert resp.json()["container"]["total_bytes"] == 123


def test_clean_mount_success(client, monkeypatch):
    calls = []
    _patched_service(monkeypatch, "clean_mount", lambda path: calls.append(path) or True)
    resp = client.post("/api/clean_mount", json={"config": {"mount_path": "/home/u/containers/c1"}})
    assert resp.status_code == 200
    assert resp.json()["success"] == 1
    assert calls == ["/home/u/containers/c1"]
