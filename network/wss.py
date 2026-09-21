import asyncio
import datetime as _dt
import ipaddress
import json
import logging
import os
import shutil
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from fastapi import APIRouter, WebSocket
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from cryptography.x509.oid import ExtendedKeyUsageOID
from pydantic import BaseModel

from ..services.container_service import (
    list_container_status,
    list_disk_usage,
    list_last_ssh,
    list_sys_snapshot,
    static_sys_snapshot,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/node_identity", tags=["node_identity"])
ctrl_link_router = APIRouter(tags=["ctrl_link"])

# Ctrl 主动拨入的快照端点；与操作通道共用同一个 HTTPS 监听、同一张 Node 证书。
CTRL_LINK_PATH = "/ws/ctrl"
_NODE_ROOT = Path(__file__).resolve().parents[1]


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

    default_path = _NODE_ROOT / ".node_identity.json"
    return Path(os.getenv("NODE_IDENTITY_FILE", str(default_path)))


def _certificate_files() -> NodeCertificateFiles:
    """返回 Node 自签证书与私钥路径。

    证书默认放在 NodeKernel/certs 下；部署时可以用环境变量覆盖。
    """

    base_dir = _NODE_ROOT / "certs"
    cert_file = Path(os.getenv("NODE_TLS_CERT_FILE", str(base_dir / "node_cert.pem")))
    key_file = Path(os.getenv("NODE_TLS_KEY_FILE", str(base_dir / "node_key.pem")))
    return NodeCertificateFiles(cert_file=cert_file, key_file=key_file)


def _resolve_node_path(value: str | None, default: Path | None = None) -> Path | None:
    """Resolve Node-local config paths from the project root."""

    if value:
        path = Path(value)
        return path if path.is_absolute() else _NODE_ROOT / path
    return default


def _default_ctrl_ca_file() -> Path:
    """Default trust anchor used by Node to verify Ctrl."""

    return _NODE_ROOT / "certs" / "ctrl_ca.pem"


def _candidate_local_ctrl_ca_files() -> list[Path]:
    """Local monorepo candidates for Ctrl public CA.

    This only copies the public CA certificate. The CA private key never leaves
    Ctrl.
    """

    return [
        _NODE_ROOT.parent / "FuxiYu_CtrKernel" / "certs" / "ctrl_ca.pem",
    ]


def ensure_ctrl_ca_trust_file(configured_path: str | None = None) -> Path | None:
    """Ensure Node has a Ctrl CA trust file when local source is available.

    Cross-host deployment still requires placing ctrl_ca.pem on Node. In the
    local monorepo case, this bootstraps the public CA into Node/certs so WSS
    and HTTPS mTLS can both use the same trust anchor without disabling TLS
    verification.
    """

    target = _resolve_node_path(configured_path, _default_ctrl_ca_file())
    if target is None:
        return None
    if target.exists():
        return target

    for source in _candidate_local_ctrl_ca_files():
        if not source.exists() or source.resolve() == target.resolve():
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            logger.info("bootstrapped Ctrl CA trust file: source=%s target=%s", source, target)
            return target
        except Exception as e:
            logger.warning("failed to bootstrap Ctrl CA trust file: source=%s target=%s error=%s", source, target, e)
            return None

    logger.warning("Ctrl CA trust file is missing: expected=%s", target)
    return None


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
        "snapshot_endpoint": CTRL_LINK_PATH,
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
    """构造容器状态快照帧。

    采集异常（docker 卡死，collect_error 置位）→ 发显式 collect_error 形状，
    Ctrl 侧将该机器全部容器置 FAILED（数据通路对账契约 C1）；正常 → 全量列表。
    """

    from .. import extensions

    collect_error = extensions.status_cache.get_collect_error()
    if collect_error:
        logger.warning(
            "build_status_snapshot: collect_error=%s (sending error shape)",
            collect_error,
        )
        return {"type": "snapshot", "topic": "container_status", "payload": {"collect_error": collect_error}}

    payload = list_container_status()
    logger.debug(
        "build_status_snapshot: containers=%s statuses=%s",
        len(payload),
        {name: item.get("status") for name, item in payload.items()},
    )
    return {"type": "snapshot", "topic": "container_status", "payload": payload}


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


############################################################
# Ctrl 链路端点（Ctrl 主动拨入）
############################################################

def _snapshot_push_interval() -> float:
    """快照推送周期（秒）；Ctrl 断线重连的节奏也由它决定。"""

    return float(os.getenv("NODE_WSS_PUSH_INTERVAL", "5"))


def _resolve_link_uid(websocket) -> str | None:
    """读取 Ctrl 在连接查询参数里出示的 uid。"""

    scope = getattr(websocket, "scope", {}) or {}
    query = parse_qs(scope.get("query_string", b"").decode("utf-8", errors="ignore"))
    return (query.get("uid") or [None])[0]


async def _wait_for_next_tick(websocket, interval: float) -> bool:
    """等到下一个推送周期；对端提前断开则立即返回 True。

    Ctrl 在这条通道上只收不发，所以 receive 的唯一用途是感知断开——
    没有它，handler 会在 Ctrl 消失后继续空转到本周期结束才由 send 失败退出。
    """

    tick = asyncio.create_task(asyncio.sleep(interval))
    watch = asyncio.create_task(websocket.receive())
    try:
        done, _ = await asyncio.wait({tick, watch}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        tick.cancel()
        watch.cancel()
        await asyncio.gather(tick, watch, return_exceptions=True)
    return watch in done


async def _push_snapshot_frames(websocket, identity: NodeIdentity) -> None:
    """按周期推送幽灵容器删帧与快照批次，直到连接断开。"""

    from .. import extensions

    interval = _snapshot_push_interval()
    while True:
        # 幽灵容器感知：先发消失 delete 帧，再发快照
        for name in extensions.status_cache.take_deleted():
            await websocket.send_text(json.dumps({"type": "delete", "container_name": name}, ensure_ascii=True))
        await websocket.send_text(json.dumps(build_snapshot_batch(identity), ensure_ascii=True))
        if await _wait_for_next_tick(websocket, interval):
            logger.info("ctrl link closed by peer: uid=%s", identity.uid)
            return


async def handle_ctrl_ws(websocket) -> None:
    """Ctrl 拨入的快照推送端点门户。

    Ctrl 是拨出方并持有 pin，Node 侧只校验 uid 与本机身份牌一致。
    身份牌未就绪时不开推送循环——Ctrl 注册（issue_uid）后会带 uid 重拨。
    """

    identity = load_node_identity()
    if identity is None:
        logger.warning("ctrl link rejected: node identity is not initialized")
        await websocket.close(code=4404)
        return
    uid = _resolve_link_uid(websocket)
    if not uid or uid != identity.uid:
        logger.warning("ctrl link rejected: uid mismatch (got %r)", uid)
        await websocket.close(code=4403)
        return
    await websocket.accept()
    logger.info("ctrl link accepted: uid=%s", uid)
    try:
        await _push_snapshot_frames(websocket, identity)
    except Exception as exc:
        # 对端正常断开走 _push_snapshot_frames 的返回路径；走到这里都是意外，
        # 所以要栈——否则只剩一句无上下文的字符串。
        logger.warning("ctrl link closed: uid=%s: %s", uid, exc, exc_info=True)


@ctrl_link_router.websocket(CTRL_LINK_PATH)
async def ws_ctrl(websocket: WebSocket):
    await handle_ctrl_ws(websocket)
