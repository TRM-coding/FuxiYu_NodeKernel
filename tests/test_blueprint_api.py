"""Node API 蓝图单元测试（①）。

不依赖 docker daemon：docker_client 用 FakeDockerClient，服务层函数 monkeypatch。
密码学走真实密钥对 —— 覆盖"验签 → 解密 → 派发 → 响应"的消息层闭环。

WSS 迁移说明：HTTP 入口会换成 WS 消息处理器，
但"验签→派发→状态跟踪"的断言逻辑可平移复用；迁移时改入口不改这些语义。
"""
import base64
import time

import pytest

from FuxiYu_NodeKernel import create_app, extensions
from FuxiYu_NodeKernel import blueprints
from FuxiYu_NodeKernel.services.container_service import CreateContainerReturn

from .conftest import (
    FakeContainer,
    FakeContainers,
    FakeDockerClient,
    configure_absolute_key_paths,
    encrypted_body,
)

# Config_info 全字段（无默认值，缺一不可）
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
    configure_absolute_key_paths(monkeypatch)
    monkeypatch.setattr(extensions, "docker_client", FakeDockerClient())
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def _patched_service(monkeypatch, name, fn):
    monkeypatch.setattr(blueprints, name, fn)


# ── 验签/格式类 ──────────────────────────────────────────────────────────


def test_invalid_json_400(client):
    resp = client.post("/api/create_container", json=None)
    assert resp.status_code == 400


def test_invalid_signature_401(client):
    body = {
        "message": base64.b64encode(b"not encrypted").decode(),
        "signature": base64.b64encode(b"x" * 256).decode(),
    }
    resp = client.post("/api/create_container", json=body)
    assert resp.status_code == 401
    assert resp.get_json()["error_reason"] == "invalid_signature"


# ── create_container ─────────────────────────────────────────────────────


def test_create_container_success(client, monkeypatch):
    calls = []

    def _stub(owner_name, cfg, public_key=None):
        calls.append((owner_name, cfg, public_key))
        return CreateContainerReturn("cid123", cfg.name)

    _patched_service(monkeypatch, "create_container", _stub)

    payload = {"owner_name": "admin", "config": VALID_CFG}
    resp = client.post("/api/create_container", json=encrypted_body(payload))

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] == 1
    assert body["container_status"] == "creating"
    # 等后台线程调用 stub（防 monkeypatch 提前撤销的竞态）
    time.sleep(0.1)
    assert len(calls) == 1
    assert calls[0][0] == "admin"
    assert calls[0][1].name == "c1"


def test_create_container_invalid_config_400(client):
    bad_cfg = {**VALID_CFG, "port": "not-a-port"}
    payload = {"owner_name": "admin", "config": bad_cfg}
    resp = client.post("/api/create_container", json=encrypted_body(payload))
    assert resp.status_code == 400
    assert resp.get_json()["error_reason"] == "invalid_config"


# ── remove_container ─────────────────────────────────────────────────────


def test_remove_container_success(client, monkeypatch):
    _patched_service(monkeypatch, "remove_container", lambda name: 0)
    payload = {"config": {"container_name": "c1"}}
    resp = client.post("/api/remove_container", json=encrypted_body(payload))
    assert resp.status_code == 200
    assert resp.get_json()["success"] == 1


def test_remove_container_not_found_404(client, monkeypatch):
    _patched_service(monkeypatch, "remove_container", lambda name: 1)
    payload = {"config": {"container_name": "ghost"}}
    resp = client.post("/api/remove_container", json=encrypted_body(payload))
    assert resp.status_code == 404
    assert resp.get_json()["error_reason"] == "not_found"


def test_remove_container_missing_name_400(client):
    resp = client.post("/api/remove_container", json=encrypted_body({"config": {}}))
    assert resp.status_code == 400
    assert resp.get_json()["error_reason"] == "missing_container_name"


# ── container_status ─────────────────────────────────────────────────────


def test_container_status_online(client, monkeypatch):
    running = FakeContainer("c1", status="running", exec_exit_code=0)
    monkeypatch.setattr(extensions, "docker_client", FakeDockerClient(FakeContainers([running])))
    payload = {"config": {"container_name": "c1"}}
    resp = client.post("/api/container_status", json=encrypted_body(payload))
    assert resp.status_code == 200
    assert resp.get_json()["container_status"] == "online"


def test_container_status_not_found_404(client):
    payload = {"config": {"container_name": "ghost"}}
    resp = client.post("/api/container_status", json=encrypted_body(payload))
    assert resp.status_code == 404
    assert resp.get_json()["error_reason"] == "not_found"


# ── machine_status ───────────────────────────────────────────────────────


def test_machine_status_online(client):
    # 注意：不能发空 dict —— get_verified_msg 对"验证成功的空 dict"和"验证失败"返回同一个 {}，
    # 端点会误判 401。真实 Ctrl 流量总是带 config，用真实形状。
    resp = client.post("/api/machine_status", json=encrypted_body({"config": {}}))
    assert resp.status_code == 200
    assert resp.get_json()["machine_status"] == "online"


# ── collaborator / role ──────────────────────────────────────────────────


def test_add_collaborator_success(client, monkeypatch):
    _patched_service(monkeypatch, "add_collaborator", lambda *a: True)
    payload = {"config": {"container_name": "c1", "user_name": "u1", "role": "admin"}}
    resp = client.post("/api/add_collaborator", json=encrypted_body(payload))
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    # Node 回显解密后的消息 —— 链路级 roundtrip 断言锚点
    assert body["decrypted_message"] == payload


def test_add_collaborator_invalid_role_400(client):
    payload = {"config": {"container_name": "c1", "user_name": "u1", "role": "hacker"}}
    resp = client.post("/api/add_collaborator", json=encrypted_body(payload))
    assert resp.status_code == 400
    assert resp.get_json()["error_reason"] == "invalid_role"


def test_remove_collaborator_success(client, monkeypatch):
    _patched_service(monkeypatch, "remove_collaborator", lambda *a: True)
    payload = {"config": {"container_name": "c1", "user_name": "u1"}}
    resp = client.post("/api/remove_collaborator", json=encrypted_body(payload))
    assert resp.status_code == 200
    assert resp.get_json()["success"] == 1


def test_update_role_success(client, monkeypatch):
    _patched_service(monkeypatch, "update_role", lambda *a: True)
    payload = {"config": {"container_name": "c1", "user_name": "u1", "updated_role": "root"}}
    resp = client.post("/api/update_role", json=encrypted_body(payload))
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert body["decrypted_message"] == payload


def test_update_role_invalid_role_400(client):
    payload = {"config": {"container_name": "c1", "user_name": "u1", "updated_role": "emperor"}}
    resp = client.post("/api/update_role", json=encrypted_body(payload))
    assert resp.status_code == 400


# ── start / stop / restart（异步派发 + 状态跟踪）─────────────────────────


def test_start_container_success(client, monkeypatch):
    _patched_service(monkeypatch, "start_container", lambda name: True)
    payload = {"config": {"container_name": "c1"}}
    resp = client.post("/api/start_container", json=encrypted_body(payload))
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] == 1
    assert body["container_status"] == "starting"
    time.sleep(0.1)
    assert blueprints._get_action_status("c1")["status"] == "online"


def test_stop_container_success(client, monkeypatch):
    _patched_service(monkeypatch, "stop_container", lambda name: True)
    payload = {"config": {"container_name": "c1"}}
    resp = client.post("/api/stop_container", json=encrypted_body(payload))
    assert resp.status_code == 200
    assert resp.get_json()["container_status"] == "stoping"
    time.sleep(0.1)
    assert blueprints._get_action_status("c1")["status"] == "offline"


def test_restart_container_success(client, monkeypatch):
    _patched_service(monkeypatch, "restart_container", lambda name: True)
    payload = {"config": {"container_name": "c1"}}
    resp = client.post("/api/restart_container", json=encrypted_body(payload))
    assert resp.status_code == 200
    assert resp.get_json()["container_status"] == "stoping"
    time.sleep(0.1)
    assert blueprints._get_action_status("c1")["status"] == "online"


# ── container_last_ssh_time ──────────────────────────────────────────────


def test_container_last_ssh_time_success(client, monkeypatch):
    _patched_service(monkeypatch, "get_last_ssh_connect_time", lambda name: "2026-01-01T00:00:00")
    payload = {"config": {"container_name": "c1"}}
    resp = client.post("/api/container_last_ssh_time", json=encrypted_body(payload))
    assert resp.status_code == 200
    assert resp.get_json()["last_ssh_connect_time"] == "2026-01-01T00:00:00"
