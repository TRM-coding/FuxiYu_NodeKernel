import sys
import os
import ssl
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

# 加载仓库根目录 .env（三仓库统一网络键名）
load_dotenv(Path(__file__).resolve().parent / ".env", override=True)

# 将父目录添加到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from FuxiYu_NodeKernel import create_app  # noqa: E402
from FuxiYu_NodeKernel.config import NetConfig  # noqa: E402
from FuxiYu_NodeKernel.network.wss import ensure_ctrl_ca_trust_file, ensure_self_signed_certificate  # noqa: E402

if __name__ == '__main__':
    cert_files = ensure_self_signed_certificate()
    ssl_kwargs = {
        "ssl_certfile": str(cert_files.cert_file),
        "ssl_keyfile": str(cert_files.key_file),
    }
    # mTLS：校验调用者（Ctrl）客户端证书 —— check_keys 双向验签语义的 TLS 落点。
    # Ctrl 证书路径（部署时人工拷贝 Ctrl CA/证书到 Node），配置后开启 REQUIRED。
    ctrl_ca = ensure_ctrl_ca_trust_file(os.getenv("NODE_CTRL_CA_FILE"))
    if ctrl_ca and ctrl_ca.exists():
        ssl_kwargs["ssl_ca_certs"] = str(ctrl_ca)
        ssl_kwargs["ssl_cert_reqs"] = ssl.CERT_REQUIRED
    uvicorn.run(
        create_app('development'),
        host='0.0.0.0',
        port=NetConfig.NODE_PORT,
        **ssl_kwargs,
    )
