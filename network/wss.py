import asyncio
import datetime as _dt
import ipaddress
import json
import logging
import os
import socket
import ssl
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from cryptography.x509.oid import ExtendedKeyUsageOID
from pydantic import BaseModel

from ..config import NetConfig
from ..services.container_service import (
    list_container_status,
    list_disk_usage,
    list_last_ssh,
    list_sys_snapshot,
    static_sys_snapshot,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/node_identity", tags=["node_identity"])

_TRUE_ENV_VALUES = {"1", "true", "yes", "on"}


class IssueNodeUidRequest(BaseModel):
    """Ctrl 首连确认后下发给 Node 的身份牌。"""

    uid: str


@dataclass(frozen=True)
class NodeIdentity:
    """Node 连接 Ctrl WSS 时使用的身份牌。

    uid 是 Ctrl 首连颁发的应用层身份；证书指纹由 Ctrl 从 TLS 层直接计算。
    """

    uid: str


@dataclass(frozen=True)
class NodeCertificateFiles:
    """Node 对外提供 HTTPS/WSS 能力时使用的本机证书文件。"""

    cert_file: Path
    key_file: Path


def _identity_file() -> Path:
    """返回本机持久化身份牌文件路径。"""

    default_path = Path(__file__).resolve().parents[1] / ".node_identity.json"
    return Path(os.getenv("NODE_IDENTITY_FILE", str(default_path)))


def _certificate_files() -> NodeCertificateFiles:
    """返回 Node 自签证书与私钥路径。

    证书默认放在 NodeKernel/certs 下；部署时可以用环境变量覆盖。
    """

    base_dir = Path(__file__).resolve().parents[1] / "certs"
    cert_file = Path(os.getenv("NODE_TLS_CERT_FILE", str(base_dir / "node_cert.pem")))
    key_file = Path(os.getenv("NODE_TLS_KEY_FILE", str(base_dir / "node_key.pem")))
    return NodeCertificateFiles(cert_file=cert_file, key_file=key_file)


def _truthy_env(name: str, default: str = "0") -> bool:
    """读取布尔型环境变量，兼容部署脚本里的常见写法。"""

    return os.getenv(name, default).lower() in _TRUE_ENV_VALUES


def _normalise_fingerprint(value: str | None) -> str | None:
    """统一证书指纹格式，便于和 TLS 层计算结果比较。"""

    if not value:
        return None
    return value.replace(":", "").strip().lower()


def _sha256_fingerprint_der(cert_der: bytes) -> str:
    """计算 DER 证书 SHA-256 指纹；用于校验 Ctrl 服务端证书 pin。"""

    digest = hashes.Hash(hashes.SHA256())
    digest.update(cert_der)
    return digest.finalize().hex()


def _node_certificate_alt_names() -> list[x509.GeneralName]:
    """生成 Node 自签证书 SAN，保证 ctrl 用 IP/DNS 访问时能通过主机名校验。"""

    names: list[x509.GeneralName] = [
        x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
    ]
    hostname = socket.gethostname()
    if hostname:
        names.append(x509.DNSName(hostname))

    extra = os.getenv("NODE_CERT_ALT_NAMES", "")
    for raw in [item.strip() for item in extra.split(",") if item.strip()]:
        try:
            names.append(x509.IPAddress(ipaddress.ip_address(raw)))
        except ValueError:
            names.append(x509.DNSName(raw))
    return names


def _certificate_matches_node_defaults(cert_file: Path, names: list[x509.GeneralName]) -> bool:
    """检查既有默认证书是否可同时做 TLS 证书和 TOFU pin 信任锚。"""

    try:
        cert = x509.load_pem_x509_certificate(cert_file.read_bytes())
        basic = cert.extensions.get_extension_for_class(x509.BasicConstraints).value
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except Exception:
        return False

    if not basic.ca:
        return False

    for name in names:
        try:
            if isinstance(name, x509.DNSName) and name.value not in san.get_values_for_type(x509.DNSName):
                return False
            if isinstance(name, x509.IPAddress) and name.value not in san.get_values_for_type(x509.IPAddress):
                return False
        except Exception:
            return False
    return True


def ensure_self_signed_certificate() -> NodeCertificateFiles:
    """确保 Node 有一套本机自签证书。

    证书只用于 HTTPS/WSS 的 TLS 握手；Ctrl 会从 TLS 层计算对端证书指纹。
    """

    files = _certificate_files()
    if files.cert_file.exists() and files.key_file.exists():
        if os.getenv("NODE_TLS_CERT_FILE") or os.getenv("NODE_TLS_KEY_FILE"):
            return files
        if _certificate_matches_node_defaults(files.cert_file, _node_certificate_alt_names()):
            return files
        logger.warning("node default TLS certificate is not usable as current TOFU pin anchor; regenerating %s", files.cert_file)

    files.cert_file.parent.mkdir(parents=True, exist_ok=True)
    files.key_file.parent.mkdir(parents=True, exist_ok=True)

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, os.getenv("NODE_CERT_COMMON_NAME", "FuxiYu NodeKernel")),
        ]
    )
    now = _dt.datetime.now(_dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _dt.timedelta(minutes=1))
        .not_valid_after(now + _dt.timedelta(days=int(os.getenv("NODE_CERT_VALID_DAYS", "3650"))))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH]),
            critical=False,
        )
        .add_extension(x509.SubjectAlternativeName(_node_certificate_alt_names()), critical=False)
        .sign(private_key, hashes.SHA256())
    )

    files.key_file.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    files.cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return files


def load_node_identity() -> NodeIdentity | None:
    """读取 Node 身份牌。

    优先读取环境变量，方便容器化部署；否则读取本地持久化文件。
    身份牌不存在时 WSS 推送保持空闲，等待后续接入流程写入。
    """

    uid = os.getenv("NODE_UID")
    if uid:
        return NodeIdentity(uid=uid)

    path = _identity_file()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("failed to read node identity file %s: %s", path, e)
        return None

    uid = data.get("uid")
    if not uid:
        return None
    return NodeIdentity(uid=uid)


def save_node_identity(identity: NodeIdentity) -> None:
    """保存 Ctrl 首连颁发的 Node 身份牌。"""

    path = _identity_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"uid": identity.uid},
            ensure_ascii=True,
            indent=2,
        ),
        encoding="utf-8",
    )


def save_ctrl_issued_uid(uid: str) -> NodeIdentity:
    """保存 Ctrl 首连颁发的 UID。

    Node 不保存也不回传证书指纹；Ctrl 以 TLS 层计算结果作为 pin 依据。
    """

    ensure_self_signed_certificate()
    identity = NodeIdentity(uid=uid)
    save_node_identity(identity)
    return identity


def build_enrollment_profile() -> dict[str, Any]:
    """返回 Ctrl 首连登记 Node 时需要读取的接入资料。

    这个函数不返回证书指纹。Ctrl 必须从 TLS 层直接计算 Node 证书 SHA-256 指纹。
    hardware 为静态硬件快照（sys_snapshot 协议），供 Ctrl 注册建档与漂移检测。
    """

    ensure_self_signed_certificate()
    identity = load_node_identity()
    return {
        "uid": identity.uid if identity else None,
        "identity_initialized": identity is not None,
        "wss_enabled": os.getenv("NODE_WSS_ENABLED", "0").lower() in {"1", "true", "yes", "on"},
        "hardware": static_sys_snapshot(),
    }


@router.get("/enrollment_profile")
def enrollment_profile_api() -> dict[str, Any]:
    """Ctrl 首连 Node 时读取的登记资料。

    该接口只暴露 UID 状态；Node 证书指纹必须由 Ctrl 从 TLS 层计算。
    """

    return build_enrollment_profile()


@router.post("/issue_uid")
def issue_uid_api(message: IssueNodeUidRequest) -> dict[str, Any]:
    """保存 Ctrl 颁发的 UID，并返回当前 Node 身份状态。"""

    identity = save_ctrl_issued_uid(message.uid)
    return {
        "success": 1,
        "uid": identity.uid,
        "identity_initialized": True,
    }


def build_status_snapshot() -> dict[str, Any]:
    """构造容器状态快照帧。"""

    return {"type": "snapshot", "topic": "container_status", "payload": list_container_status()}


def build_last_ssh_snapshot() -> dict[str, Any]:
    """构造最后 SSH 时间快照帧。"""

    return {"type": "snapshot", "topic": "last_ssh", "payload": list_last_ssh()}


def build_disk_usage_snapshot() -> dict[str, Any]:
    """构造磁盘使用量快照帧。"""

    return {"type": "snapshot", "topic": "disk_usage", "payload": list_disk_usage()}


def build_sys_snapshot() -> dict[str, Any]:
    """构造宿主机系统快照帧（静态硬件 + 动态指标）。"""

    return {"type": "snapshot", "topic": "sys_snapshot", "payload": list_sys_snapshot()}


def build_snapshot_batch(identity: NodeIdentity) -> dict[str, Any]:
    """组合一次 WSS 推送批次。

    四个 list 快照共用 service 层读面，WSS 只负责传输。
    """

    return {
        "type": "snapshot_batch",
        "node_uid": identity.uid,
        "payload": [
            build_status_snapshot(),
            build_last_ssh_snapshot(),
            build_disk_usage_snapshot(),
            build_sys_snapshot(),
        ],
    }


def ctrl_wss_url(identity: NodeIdentity) -> str:
    """生成 Node 主动连接 Ctrl 的 WSS 地址。"""

    configured = os.getenv("NODE_CTRL_WSS_URL")
    if configured:
        return configured
    scheme = os.getenv("NODE_CTRL_WSS_SCHEME", "wss")
    return (
        f"{scheme}://{NetConfig.CTRL_IP}:{NetConfig.CTRL_PORT}/ws/node"
        f"?uid={identity.uid}"
    )


def expected_ctrl_certificate_fingerprint() -> str | None:
    """返回 Node 侧配置的 Ctrl 证书指纹。

    该值可作为没有 CA 文件时的轻量 pin；有 CA 文件时也可做额外防线。
    指纹来源应由部署侧人工写入，不由 Ctrl 在线下发。
    """

    return _normalise_fingerprint(os.getenv("NODE_CTRL_CERT_FINGERPRINT"))


def build_wss_ssl_context() -> ssl.SSLContext:
    """构造 Node -> Ctrl WSS 的 TLS 上下文。

    方案一要求 Node 主动连接 Ctrl WSS 时带上自己的 Node 证书/私钥，
    Ctrl 从 TLS 层校验该证书是否已 pin。Node 侧则通过 Ctrl CA 文件、
    Ctrl 证书文件或显式指纹 pin 校验 Ctrl 身份。
    """

    ctrl_ca_file = os.getenv("NODE_CTRL_CA_FILE") or os.getenv("NODE_CTRL_CERT_FILE")
    expected_fingerprint = expected_ctrl_certificate_fingerprint()
    tls_insecure = _truthy_env("NODE_CTRL_TLS_INSECURE", "0")

    if ctrl_ca_file:
        context = ssl.create_default_context(cafile=ctrl_ca_file)
    else:
        context = ssl.create_default_context()

    if tls_insecure or (expected_fingerprint and not ctrl_ca_file):
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

    if _truthy_env("NODE_WSS_CLIENT_CERT_ENABLED", "1"):
        files = ensure_self_signed_certificate()
        context.load_cert_chain(certfile=str(files.cert_file), keyfile=str(files.key_file))

    return context


def verify_ctrl_peer_certificate(websocket, expected_fingerprint: str | None = None) -> None:
    """连接建立后校验 Ctrl 服务端证书指纹。

    这是 CA 校验之外的可选 pin 校验；当 Node 只配置了
    NODE_CTRL_CERT_FINGERPRINT 且没有 CA 文件时，它就是主要身份校验。
    """

    expected = _normalise_fingerprint(expected_fingerprint)
    if expected is None:
        return

    ssl_object = websocket.transport.get_extra_info("ssl_object")
    if ssl_object is None:
        raise ssl.SSLError("Ctrl WSS peer certificate is not available")

    cert_der = ssl_object.getpeercert(binary_form=True)
    if not cert_der:
        raise ssl.SSLError("Ctrl WSS peer certificate is empty")

    actual = _sha256_fingerprint_der(cert_der)
    if actual != expected:
        raise ssl.SSLError("Ctrl WSS certificate fingerprint mismatch")


async def push_snapshots_forever(stop_event: threading.Event, interval_seconds: float = 5.0) -> None:
    """持续向 Ctrl 推送状态快照。

    缺少 websockets 依赖时不报错退出，避免影响 HTTP 操作通道启动。
    身份牌在循环内重读：Ctrl 运行中注册（issue_uid 写 identity 文件）后自动生效，无需重启。
    """

    try:
        import websockets
    except ImportError:
        logger.warning("websockets package is not installed; WSS pusher is disabled")
        return

    while not stop_event.is_set():
        identity = load_node_identity()
        if identity is None:
            logger.info("node identity is not available yet; retrying")
            await asyncio.sleep(min(interval_seconds, 5.0))
            continue

        url = ctrl_wss_url(identity)
        ssl_context = build_wss_ssl_context() if url.startswith("wss://") else None
        expected_fingerprint = expected_ctrl_certificate_fingerprint()
        try:
            async with websockets.connect(url, ssl=ssl_context) as websocket:
                verify_ctrl_peer_certificate(websocket, expected_fingerprint)
                logger.info("connected to Ctrl WSS: %s", url)
                while not stop_event.is_set():
                    # 幽灵容器感知：先发消失 delete 帧，再发快照
                    from .. import extensions
                    for name in extensions.status_cache.take_deleted():
                        await websocket.send(
                            json.dumps({"type": "delete", "container_name": name}, ensure_ascii=True))
                    await websocket.send(json.dumps(build_snapshot_batch(identity), ensure_ascii=True))
                    await asyncio.sleep(interval_seconds)
        except Exception as e:
            logger.warning("Ctrl WSS push loop error: %s", e)
            await asyncio.sleep(min(interval_seconds, 5.0))


def start_wss_pusher(stop_event: threading.Event) -> threading.Thread | None:
    """按配置启动 WSS 推送线程。

    默认关闭，设置 NODE_WSS_ENABLED=1 后才会主动连接 Ctrl。
    """

    enabled = os.getenv("NODE_WSS_ENABLED", "0").lower() in {"1", "true", "yes", "on"}
    if not enabled:
        logger.info("NODE_WSS_ENABLED is off; WSS pusher not started")
        return None

    interval = float(os.getenv("NODE_WSS_PUSH_INTERVAL", "5"))

    def _run():
        asyncio.run(push_snapshots_forever(stop_event, interval))

    thread = threading.Thread(target=_run, name="node-wss-pusher", daemon=True)
    thread.start()
    return thread


def wait_for_thread_stop(thread: threading.Thread | None, timeout: float = 3.0) -> None:
    """应用关闭时等待 WSS 推送线程退出。"""

    if thread is None:
        return
    deadline = time.time() + timeout
    remaining = deadline - time.time()
    if remaining > 0:
        thread.join(remaining)
