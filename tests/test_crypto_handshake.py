"""密码学握手测试（②）。

两条线：
1. 自洽：单侧 encrypt+sign → get_verified_msg 还原，篡改被拒
2. 跨端：Ctrl 加密签名 → Node 解密验签（真实生产方向）及反向

WSS 迁移后本文件不动：加密/签名是消息层协议，与传输层无关。
"""
import base64
import json
import sys
from pathlib import Path

import pytest

NODE_ROOT = Path(__file__).resolve().parents[1]
CTRL_ROOT = NODE_ROOT.parent / "FuxiYu_CtrKernel"

from FuxiYu_NodeKernel.utils import CheckKeys as node_ck  # noqa: E402
from .conftest import configure_absolute_key_paths  # noqa: E402

if str(NODE_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(NODE_ROOT.parent))

ctrl_ck = pytest.importorskip("FuxiYu_CtrKernel.utils.CheckKeys", reason="Ctrl 仓库不在本机，跳过跨端握手测试")

PAYLOAD = {
    "owner_name": "admin",
    "config": {
        "gpu_list": [],
        "cpu_number": 2,
        "memory": 4,
        "swap_memory": 0,
        "name": "c1",
        "port": 2233,
        "image": "ubuntu:22.04",
    },
}


@pytest.fixture()
def key_paths(monkeypatch):
    """两边密钥路径都指向各自仓库的真实 key 文件。"""
    configure_absolute_key_paths(monkeypatch)
    monkeypatch.setattr(ctrl_ck.KeyConfig, "PRIVATE_KEY_PATH", str(CTRL_ROOT / "private_A.pem"))
    monkeypatch.setattr(ctrl_ck.KeyConfig, "PUBLIC_KEY_PATH", str(CTRL_ROOT / "public_A.pem"))


def _encrypt_sign(ck, payload: dict) -> dict:
    raw = json.dumps(payload)
    return {
        "message": base64.b64encode(ck.encryption(raw)).decode(),
        "signature": base64.b64encode(ck.signature(raw)).decode(),
    }


def test_node_self_roundtrip(key_paths):
    assert node_ck.get_verified_msg(_encrypt_sign(node_ck, PAYLOAD)) == PAYLOAD


def test_ctrl_self_roundtrip(key_paths):
    assert ctrl_ck.get_verified_msg(_encrypt_sign(ctrl_ck, PAYLOAD)) == PAYLOAD


def test_ctrl_to_node_roundtrip(key_paths):
    """生产方向：Ctrl 加密签名 → Node 解密验签。"""
    assert node_ck.get_verified_msg(_encrypt_sign(ctrl_ck, PAYLOAD)) == PAYLOAD


def test_node_to_ctrl_roundtrip(key_paths):
    assert ctrl_ck.get_verified_msg(_encrypt_sign(node_ck, PAYLOAD)) == PAYLOAD


def test_tampered_signature_rejected(key_paths):
    msg = _encrypt_sign(node_ck, PAYLOAD)
    msg["signature"] = base64.b64encode(b"x" * 256).decode()
    assert node_ck.get_verified_msg(msg) == {}


def test_tampered_ciphertext_rejected(key_paths):
    msg = _encrypt_sign(node_ck, PAYLOAD)
    raw = bytearray(base64.b64decode(msg["message"]))
    raw[-1] ^= 0xFF
    msg["message"] = base64.b64encode(bytes(raw)).decode()
    assert node_ck.get_verified_msg(msg) == {}


def test_missing_fields_rejected(key_paths):
    assert node_ck.get_verified_msg({"message": None, "signature": None}) == {}
