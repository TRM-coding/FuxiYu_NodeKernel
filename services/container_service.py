# 与他们相关的参数有必要被严格验证和过滤，或者改用更安全的方式（如直接传递参数列表而不是 shell 命令字符串）

from ..constant import *
from ..utils.Container import Container
from .. import extensions
# from ..constant import *
from typing import TypedDict
# from ..utils.Container import Container
import base64
# from ..extensions import docker_client
import docker
from docker.types import Mount
import os
from typing import NamedTuple
from ..utils import sanitizer as _sanitizer
from ..docker_operates.port_mappings import extract_port_info
import subprocess
import threading
import time
import logging
from datetime import datetime
import shutil
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)






def _build_spec_value(build, key: str, default=None):
    if build is None:
        return default
    if hasattr(build, key):
        return getattr(build, key)
    if isinstance(build, dict):
        return build.get(key, default)
    return default


# 代理注入（构建期与运行期）只取这两个键；读的时候大小写都认，写出去统一成小写。
#
# ⚠ **刻意不含 `no_proxy`**：它进到构建里几乎只会帮倒忙。实测（2026-09）：某台机器上
# `archive.ubuntu.com` 解析到内网地址，而 `NO_PROXY` 里写着 `10.0.0.0/8,192.168.0.0/16`
# ——于是 apt 绕开代理直连，被校园网拦下，报的却是 `Clearsigned file isn't valid, got
# 'NOSPLIT'`，一路查不出原因。构建里的请求本来就该走代理出去；真要放行某个内部地址，
# 在模板的 dockerfile_body 里显式写 `ENV no_proxy=...`，别让进程级的 NO_PROXY 偷偷生效。
# 运行期同理：容器里的请求也该走代理出去，理由和踩过的坑是同一个。
_PROXY_ENV_KEYS = ("http_proxy", "https_proxy")


def _clean_proxy_value(value: str) -> str:
    """只接受干净的代理 URL——它要被**直接拼进 Dockerfile 文本**，所以必须挡掉
    空格、换行、引号、反引号、`$` 这些能在 Dockerfile 里变出第二条指令的字符。"""
    value = (value or "").strip()
    if value.startswith(("http://", "https://")) and not any(
        c in value for c in " \t\n\r'\"`$"
    ):
        return value
    return ""


def _inject_build_proxy(dockerfile_text: str) -> str:
    """把本机配置的代理以 `ARG` 形式写进 `FROM` 之后；没配就**原样返回**。

    ★ 为什么不用 docker-py 的 `buildargs`：源码里可查——它把参数塞进 **URL 的 query**
    （`params.update({'buildargs': json.dumps(buildargs)})`），而 CLI / BuildKit 走的是
    **body**。某些 daemon 的构建路径不读 query，于是出现"手动 `docker build --build-arg`
    就通、平台走 SDK 就不通"，而且两侧日志长得一模一样，差异完全不可见（2026-09 实测，
    为此绕了很久）。`use_config_proxy=True` 走的是同一条 query 路径，同样不可靠。

    ★ 为什么是 `ARG` 而不是 `ENV`：`ARG` 只在构建期存在，**不落进运行中的容器**
    （实测：构建完 `docker run … echo $http_proxy` 是空的）。`ENV` 会把代理地址烤进
    每一个容器——代理是构建期的环境，不是镜像的内容。

    ★ 为什么由 Node 注入：**代理是机器的事实**（同一份模板，有的机器要代理、有的直连正常），
    而 Ctrl 的设置是全局的。放本机 .env 里，一台机器一个样，不会波及别的机器。

    ★ 位置只能是 `FROM` 之后：Dockerfile 里 `FROM` 之前只允许注释与 `ARG`，做不了别的；
    而注入的 ARG 必须赶在平台注入段那次 `apt-get` 之前生效。
    """
    args = []
    for name in _PROXY_ENV_KEYS:
        value = _clean_proxy_value(
            os.environ.get(name) or os.environ.get(name.upper()) or ""
        )
        if value:
            args.append(f"ARG {name}={value}")
    if not args:
        return dockerfile_text

    snippet = (
        "# fuxi: 本机构建代理（见 container_service._inject_build_proxy）\n"
        + "\n".join(args)
    )
    lines = dockerfile_text.splitlines()
    for idx, line in enumerate(lines):
        if line.strip().upper().startswith("FROM "):
            lines.insert(idx + 1, snippet)
            return "\n".join(lines)
    return dockerfile_text


def _runtime_proxy_env() -> dict[str, str]:
    """本机给**容器内**用的代理环境变量（大小写各一份）；没配就是空 dict。

    与构建期同一个来源（Node 进程的 .env）——代理是机器的事实。两处的差别只在
    "送到哪里"：构建期写进 Dockerfile 的 `ARG`，运行期写进容器。

    ★ 为什么运行期也得给：学生 SSH 进去之后的 apt / pip / git / curl 出外网走的就是它。
    2026-09 学生报"容器内网络不通"，根因就是这段在 create_container 瘦身时跟着
    "容器内装 sshd"一起被删掉了（38de262）——那段注入不只服务于装包，它同时是
    容器出外网的唯一入口。
    """
    env: dict[str, str] = {}
    for name in _PROXY_ENV_KEYS:
        value = _clean_proxy_value(
            os.environ.get(name) or os.environ.get(name.upper()) or ""
        )
        if value:
            env[name] = value
            env[name.upper()] = value
    return env


def _runtime_proxy_setup_command(proxy_env: dict[str, str]) -> str:
    """把代理落到容器文件系统：`/etc/environment`（SSH 会话靠 PAM 读它）+ apt 配置。

    ★ 为什么非写 `/etc/environment` 不可：`docker run -e` 那套环境变量**进不了 SSH 会话**
    ——sshd 会清空环境另起一套，只从 PAM（`pam_env` 读 `/etc/environment`）等来源取值。
    学生是 SSH 进去用的，这个文件才是他们真正吃到代理的地方（两边都写：`-e` 覆盖
    容器主进程与 `docker exec`，`/etc/environment` 覆盖 SSH 会话）。

    ★ 为什么是**合并**而不是覆盖：旧实现用 `>` 直接覆盖，会把镜像自带的 PATH 一起干掉
    ——2026-09 在学生的容器里实测看到 `/etc/environment` 只剩一行 PATH，那行是镜像的；
    覆盖式写入会让 SSH 会话连 PATH 都没有。这里先删掉自己写的代理行再追加，幂等。

    ★ apt 配置只在 apt 系镜像上写（`/etc/apt/apt.conf.d` 存在时），其它基底不塞垃圾文件。
    """
    lines = "".join(f"{key}={value}\\n" for key, value in proxy_env.items())
    http_url = proxy_env.get("http_proxy") or proxy_env.get("https_proxy") or ""
    apt = ""
    if http_url:
        apt = (
            "if [ -d /etc/apt/apt.conf.d ]; then "
            f"printf 'Acquire::http::Proxy \"{http_url}\";\\n"
            f"Acquire::https::Proxy \"{http_url}\";\\n' > /etc/apt/apt.conf.d/99proxy; "
            "fi"
        )
    return (
        "touch /etc/environment; "
        "sed -i -E '/^[[:space:]]*(http_proxy|https_proxy|HTTP_PROXY|HTTPS_PROXY)=/d' "
        "/etc/environment; "
        f"printf '{lines}' >> /etc/environment; "
        + apt
    )


def _build_log_tail(buildlog, limit: int = 20, max_chars: int = 2000) -> str:
    """把 docker build 的输出流压成**末尾若干行**的纯文本，供失败时上报。

    只取末尾：真正的原因（apt 的报错、找不到的包、网络故障）总在最后几行，而完整日志
    可能有几千行，整段塞进 failed_detail 反而没人看。

    存在的理由（2026-09 实测）：`apt-get update` 在容器里失败、而整层仍然退出 0（见平台注入
    片段的断言），构建报"成功"，镜像里却没有 openssh。当时能拿到的只有一句
    `returned a non-zero code: 100`，完全看不出 apt 到底报了什么，只能从上层症状一路倒推。
    """
    lines: list[str] = []
    for chunk in buildlog or []:
        if isinstance(chunk, dict):
            text = chunk.get("stream") or chunk.get("error") or ""
        elif isinstance(chunk, (bytes, bytearray)):
            # 个别版本/路径下不做 JSON 解码，给的是裸字节；一并兜住
            text = chunk.decode("utf-8", errors="replace")
        else:
            text = str(chunk)
        for line in str(text).splitlines():
            line = line.rstrip()
            if line:
                lines.append(line)
    return "\n".join(lines[-limit:])[-max_chars:]


def build_image(build) -> str:
    """按 Ctrl 发来的最终 Dockerfile 临时构建镜像。

    build 阶段只负责让 image_tag 在本机 Docker 中可用；命中同名 tag
    直接返回，不产生容器对象，也不写容器状态 cache。
    """

    dockerfile_text = _build_spec_value(build, "dockerfile_text", "") or ""
    image_tag = _build_spec_value(build, "image_tag", "") or ""
    if not dockerfile_text.strip():
        raise RuntimeError("missing dockerfile_text for image build")
    if not image_tag.strip():
        raise RuntimeError("missing image_tag for image build")

    if extensions.docker_client is None:
        extensions.init_docker()

    try:
        extensions.docker_client.images.get(image_tag)
        logger.info("Image build cache hit: tag=%s", image_tag)
        return image_tag
    except docker.errors.ImageNotFound:
        logger.info("Image build cache miss: tag=%s", image_tag)

    dockerfile_text = _inject_build_proxy(dockerfile_text)

    with tempfile.TemporaryDirectory(prefix="fuxi-build-") as tmpdir:
        tmp_path = Path(tmpdir)
        (tmp_path / "Dockerfile").write_text(dockerfile_text, encoding="utf-8")
        # 把"这次构建有没有代理"写进日志：这台机器出不了外网时，apt 的报错长得一样
        # （都是 NOSPLIT / not signed），光看报错分不清"没配代理"还是"配了没生效"。
        # 有这一行，两种情况的日志第一眼就不同（2026-09 实测踩过这个坑）。
        logger.info(
            "Building image tag=%s in tmp=%s build_proxy=%s",
            image_tag, tmpdir,
            _clean_proxy_value(
                os.environ.get("http_proxy") or os.environ.get("HTTP_PROXY") or ""
            ) or "（本进程没有代理环境变量）",
        )
        try:
            # **不要传 decode=True**：`ImageCollection.build` 自己就会把响应流过一遍
            # `json_stream`，块已经是 dict；再传 decode 会让底层先解一次、上层又对 dict 调
            # `.decode()`，报 `'dict' object has no attribute 'decode'`（2026-09 实测）。
            _, buildlog = extensions.docker_client.images.build(
                path=tmpdir,
                dockerfile="Dockerfile",
                tag=image_tag,
                rm=True,
                forcerm=True,
            )
        except Exception as e:
            # **把 docker build 的原始输出带上**：只报一句 "returned a non-zero code: 100"
            # 的话，调用方根本看不出 apt 报了什么（2026-09 实测，为此绕了一大圈）。
            # 属性名是 `build_log`（带下划线）——docker-py 的 BuildError 把日志存这儿，
            # 不是 `buildlog`。写错的代价是"一条日志都拿不到"，所以这条实测过（见测试）。
            tail = _build_log_tail(getattr(e, "build_log", None))
            if tail:
                logger.error("image build failed: tag=%s\n--- docker build output (tail) ---\n%s",
                             image_tag, tail)
                raise RuntimeError(
                    f"{e}\n--- docker build output (tail) ---\n{tail}"
                ) from e
            raise
    return image_tag


#Return API Definition
####################################################
class CreateContainerReturn(NamedTuple):
    container_id:str
    container_name:str
    port: int | None = None
    port_mappings: list | None = None
    bind_mount_path: str | None = None

class RemoveContinaerReturn:
    SUCCESS=0
    NOTFOUND=1
    FAILED=2
####################################################



#Function Implementation
####################################################

# 将owner_name作为root，创建port新容器
def create_container(
    owner_name: str,
    config: Container.Config_info,
    public_key: str | None = None,
    restore_mount_path: str | None = None,
) -> CreateContainerReturn:
    if extensions.docker_client is None:
        extensions.init_docker()

    print(f"Creating container for owner={owner_name} with config={config} and public_key={public_key}")
    logger.info("create_container service begin: name=%s owner=%s image=%s port=%s",
                config.name, owner_name, config.image, config.port)
    # validate owner_name early because it's used as host path component
    try:
        _sanitizer.validate_username(owner_name)
    except Exception as e:
        raise RuntimeError(f"unsafe owner_name: {e}")
    # 容器名与 Ctrl 侧创建校验同规则（docker 要求 ≥2 字符，平台字符集限字母/数字/下划线）。
    # 在 docker create 400 前尽早失败，避免脏错误形态 + 创建残留（2026-09 单字符 "2" 复盘）。
    import re

    _create_name = str(getattr(config, "name", "") or "")
    if not (2 <= len(_create_name) <= 115) or not re.fullmatch(r"[A-Za-z0-9_]{2,}", _create_name):
        raise RuntimeError(
            f"invalid container name: '{_create_name}' (need 2-115 chars of A-Z a-z 0-9 _)"
        )
    # 补CPU LIST 从 0 开始编号，如果 cpu_number=4 就是 [0,1,2,3]
    cpu_count = int(getattr(config, 'cpu_number', 0) or 0)
    cpu_list = list(range(cpu_count)) if cpu_count > 0 else []
    cpuset_cpus = ",".join(str(x) for x in cpu_list) if cpu_list else None
    mem_limit = f"{config.memory}g"
    
    # Do NOT set memswap_limit here; keep kernel swap behavior default.
    # Instead, when provided, use `shared_memory` to set container's IPC shared memory size via `shm_size`.
    shared_amt = int(getattr(config, 'shared_memory', 0) or 0)
    # Docker SDK expects `shm_size` as an int (bytes) or a string like '64m'.
    # Use bytes for clarity: convert GB -> bytes.
    shm_size_bytes = int(shared_amt) * 1024 * 1024 * 1024 if shared_amt > 0 else None

    # GPU LIST为空则是CPU机器，不接受GPU请求。device_requests只用于GPU资源分配
    gpu_list = getattr(config, 'gpu_list', None)
    device_requests = None
    if gpu_list is not None and isinstance(gpu_list, (list, tuple)) and len(gpu_list) > 0:
        # 指定 GPU id 时不要同时设置 count；Docker 会拒绝 Count + DeviceIDs 混用。
        device_requests = [
            docker.types.DeviceRequest(
                device_ids=[str(x) for x in gpu_list],
                capabilities=[["gpu"]]
            )
        ]

    print(f"DEBUG: cpu_list={cpu_list}, gpu_list={gpu_list}, mem_limit={mem_limit}, shm_size_bytes={shm_size_bytes}, device_requests={device_requests}")
    name = f"{config.name}" # 名字自定义
    # 将container的/root目录挂载到宿主机的{NODE_CONTAINERS_BASE}/owner_name/containers/name目录，方便后续调试和数据持久化（虽然现在设计上容器是临时的，但以防万一）。这个路径也要确保合法和安全，避免注入攻击或路径遍历等问题。
    # 挂载根目录可配置：生产默认 /home（Node 以 root 运行）；开发环境指向可写路径，避免非 root 无权建 /home 下的目录。
    containers_base = os.getenv("NODE_CONTAINERS_BASE", "/home")
    host_root_mount = os.path.join(containers_base, owner_name, "containers", name)
        
    try:
        if restore_mount_path:
            base_real = os.path.realpath(containers_base)
            mount_real = os.path.realpath(restore_mount_path)
            base_norm = base_real.replace("\\", "/").rstrip("/")
            mount_norm = mount_real.replace("\\", "/").rstrip("/")
            if not (mount_norm == base_norm or mount_norm.startswith(base_norm + "/")):
                raise RuntimeError(f"unsafe restore mount path outside containers base: {restore_mount_path}")
            parts = set(mount_norm.split("/"))
            if "containers" not in parts:
                raise RuntimeError(f"unsafe restore mount path without containers segment: {restore_mount_path}")
            if not os.path.isdir(mount_real):
                raise RuntimeError(f"restore mount path does not exist: {restore_mount_path}")
            host_root_mount = mount_real
        else:
            try:
                os.makedirs(host_root_mount, exist_ok=False)
            except FileExistsError:
                # 如果目录已经存在了，加上一个随机后缀避免冲突
                import random
                suffix = random.randint(10000, 99999)
                host_root_mount += f"_{suffix}"
                try:
                    os.makedirs(host_root_mount, exist_ok=False)
                except FileExistsError:
                    raise RuntimeError(f"failed to create host mount path {host_root_mount}: directory already exists")
        # 设置权限
        current_uid = os.getuid()
        current_gid = os.getgid()

        stat_info = os.stat(host_root_mount)

        os.chown(host_root_mount, current_uid, current_gid)
        os.chmod(host_root_mount, 0o755)


        # 验证修改后状态
        new_stat = os.stat(host_root_mount)

    except Exception as e:
        raise RuntimeError(f"failed to ensure host mount path {host_root_mount}: {e}")
    # avoid creating a random-name container: check if a container with the desired name already exists
    try:
        existing = extensions.docker_client.containers.get(name)
        print(f"Container with name {name} already exists: id={existing.id} status={existing.status}")
        raise RuntimeError(f"container {name} already exists on this host")
    except docker.errors.NotFound:
        # good, proceed to create with explicit name
        pass

    # Use docker.types.Mount for a more reliable bind mount
    mounts = [Mount(target="/root", source=host_root_mount, type="bind", read_only=False)]
    print(f"DEBUG: Using mounts={mounts}")
    # 运行期代理：给容器主进程与 `docker exec` 的那一份（SSH 会话那份要写文件，见下）。
    proxy_env = _runtime_proxy_env()
    # 容器里跑什么：**镜像自己说了算**（2026-09 决策）。
    #
    # Ctrl 把启动命令渲染成最终 Dockerfile 的**最后一行 ENTRYPOINT**，所以它已经是镜像的
    # 一部分：Node 不传 command、也不碰 entrypoint 字段，只负责把镜像跑起来。
    #
    # 这样分工才合理——"跑什么"是控制面的策略（连同它默认的 tail -f /dev/null 一起写在
    # Ctrl 的渲染函数里），Node 是纯执行器。此前的那条路（运行期传 command）必须额外置空
    # Entrypoint 才不被镜像入口吃掉，一旦漏掉就会静默跑错——把策略放在构建期就从根上没了。
    container = extensions.docker_client.containers.run(
        config.image,
        detach=True,
        tty=True,
        name=name,
        
        # 端口发布交给 docker（2026-08 决策）：22 与 EXPOSE 端口全部自动分配宿主端口，
        # 创建后 inspect 回填实际映射；Ctrl 不再分配端口（get_the_first_free_port 退役）。
        ports={"22/tcp": None},
        publish_all_ports=True,   # 等价 docker run -P：自动发布 Dockerfile EXPOSE 的端口
        mem_limit=mem_limit,
        cpuset_cpus=cpuset_cpus,
        device_requests=device_requests,
        mounts=mounts,
        **({"shm_size": shm_size_bytes} if shm_size_bytes is not None else {}),
        # 没配代理就不传这个键（空 dict 也会被 docker 当成"设了环境"）
        **({"environment": proxy_env} if proxy_env else {})
    )
    print(f"Container created with ID={container.id} and name={name}")


    container.reload()
    print(f"Container status after creation: {container.status}")
    try:
        print("Container mounts after reload:", container.attrs.get('Mounts'))
    except Exception:
        print("Container mounts info unavailable")



    # container.exec_run("service ssh restart", user="root")
    def _container_exited(container) -> bool:
        """容器是否已经不在运行（用于把"启动命令立刻退出"与真的 sshd 故障分开）。

        读 docker 的实时状态；查询本身失败时返回 False——那说明连状态都拿不到，
        报 sshd 故障至少不会比报错方向更误导。
        """
        try:
            container.reload()
            return (container.status or "").lower() not in ("running", "created", "restarting")
        except Exception:
            return False

    def _run(container, cmd: str, timeout_sec: int = 120):
        # 这里用一个 shell wrapper 来实现命令超时，避免某些命令（如 apt-get）在容器内卡死导致 exec_run 永远不返回的问题
        wrapped = (
            "( " + cmd + " ) & pid=$!; (sleep " + str(timeout_sec) + "; kill -9 $pid 2>/dev/null) & wait $pid"
        )
        print(f"Running command in container {container.id}: {cmd} (wrapped timeout={timeout_sec}s)")
        r = container.exec_run(["/bin/sh", "-c", wrapped], user="root")
        out = None
        try:
            out = r.output.decode('utf-8', errors='ignore')
        except Exception:
            out = str(r.output)
        # determine exit code in a backward-compatible way
        if hasattr(r, 'exit_code'):
            exit_code = r.exit_code
        else:
            try:
                # may be a tuple like (exit_code, output)
                exit_code = int(r[0])
            except Exception:
                exit_code = 0
        print(f"Executed command: {cmd}\nExit code: {exit_code}\nOutput: {out}")
        if exit_code != 0:
            raise RuntimeError(f"cmd failed: {cmd}\nexit={exit_code}\noutput={out}")
        
        return r

    # 代理落到容器里（在任何需要网络的命令之前）：SSH 会话靠 /etc/environment 出外网。
    # 尽力而为——写不进去不该让创建失败（容器至少还能用内网），但必须在日志里留痕：
    # 少了这一行，症状会变成"学生说容器没网"，而平台侧什么都看不出来（2026-09 就是这么丢的）。
    if proxy_env:
        try:
            _run(container, _runtime_proxy_setup_command(proxy_env))
            logger.info(
                "create_container proxy injected: name=%s vars=%s",
                name, sorted(proxy_env),
            )
        except Exception as e:
            logger.warning("create_container proxy inject failed: name=%s error=%s", name, e)

    # 初始密码为 owner_name + "123"，用户可以登录后再改密码（也可以直接提供公钥登录）
    _run(container, f"echo 'root:{owner_name}123' | chpasswd")
    try:
        _sanitizer.validate_username(owner_name)
    except Exception as e:
        raise RuntimeError(f"unsafe owner_name: {e}")
    # 使得公钥可选（如果提供了公钥则写入，否则只用密码登录）。
    # 密码/公钥先就位，sshd 启动与 :22 探活作为最后一道守门；
    # sshd 安装责任已前移到镜像构建注入片段。
    if public_key:
        try:
            # Use base64 to avoid shell-quoting issues when writing the key
            # basic safety check on provided public key text before encoding
            _sanitizer.validate_shell_arg(public_key)
            b64 = base64.b64encode(public_key.encode('utf-8')).decode('ascii')
            cmd = (
                "mkdir -p /root/.ssh && chmod 700 /root/.ssh && "
                f"echo '{b64}' | base64 -d > /root/.ssh/authorized_keys && "
                "chmod 600 /root/.ssh/authorized_keys"
            )
            _run(container, cmd)
        except Exception as e:
            print(f"Failed to install public_key into container: {e}")
            logger.warning("create_container public_key install failed: name=%s error=%s", name, e)
    else:
        logger.info("create_container no public_key provided: name=%s", name)

    # ── 最后一道守门：sshd 配置 + 启动 ──
    # 平台基础设施由最终 Dockerfile 注入；Node 不再现场安装 sshd。
    try:
        _run(container, "mkdir -p /run/sshd")
        _run(container, "ssh-keygen -A")
        _run(container, "sed -i 's/^#*PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config")
        _run(container, "sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config")
        _run(container, "/usr/sbin/sshd")
        logger.info("create_container sshd started: name=%s container_id=%s", name, container.id)
    except Exception as e:
        logger.error("create_container sshd gate failed: name=%s container_id=%s error=%s", name, container.id, e)
        # 归因（2026-09）：自 Ctrl 可以指定启动命令起，"sshd gate failed" 有了一个全新的、
        # 而且用户完全无从判断的成因——**容器的启动命令立刻退出了**，于是容器已停止，
        # 后续 exec 全部失败。裸报 sshd 会把人引去查 sshd，所以这里先看容器还在不在。
        if _container_exited(container):
            raise RuntimeError(
                "container exited immediately after start: the configured entrypoint command "
                "did not keep it running (platform cannot provide SSH without a live container)"
            ) from e
        raise RuntimeError(f"sshd gate failed: {e}") from e

    # ── 端口映射回填（docker 自动分配）：inspect NetworkSettings.Ports 提取实际宿主端口 ──
    # 提取逻辑在 docker_operates.port_mappings（采集侧每轮也用它重算，两边必须一致）。
    port = None
    port_mappings = []
    try:
        container.reload()
        port, port_mappings = extract_port_info(container.attrs)
    except Exception as e:
        print(f"port mapping inspect failed: {e}")
        logger.warning("create_container port inspect failed: name=%s error=%s", name, e)

    logger.info("create_container service complete: name=%s container_id=%s ssh_ready=True port=%s",
                name, container.id, port)
    return CreateContainerReturn(container.id, container.name, port, port_mappings, host_root_mount)

#删除容器并删除其所有者记录
def remove_container(container_name: str) -> int:
    try:
        if extensions.docker_client is None:
            try:
                extensions.init_docker()
            except Exception as e:
                print(f"Failed to init docker client: {e}")
                raise RuntimeError(f"docker init failed: {e}")
        print("Attempting to remove container with name:", container_name)
        container = extensions.docker_client.containers.get(container_name)
        container.remove(force=True)  # force=True 避免容器在运行时报错
        # 验证容器确实被删除了        try:
        try:
            extensions.docker_client.containers.get(container_name)
        except docker.errors.NotFound:
            print(f"Container {container_name} successfully removed.")
            return RemoveContinaerReturn.SUCCESS
        print(f"Container {container_name} still exists after removal attempt.")
        return RemoveContinaerReturn.FAILED
    except docker.errors.NotFound:
        print(f"Container {container_name} not found.")
        return RemoveContinaerReturn.NOTFOUND
    except Exception as e:
        print(f"Failed to remove container {container_name}: {e}")
        return RemoveContinaerReturn.FAILED

#将container_id对应的容器新增user_id作为collaborator,其权限为role
def add_collaborator(container_name: str, user_name: str, role: ROLE) -> bool:
    try:
        if extensions.docker_client is None:
            extensions.init_docker()
        
        container=extensions.docker_client.containers.get(container_name)
        print(f"Adding collaborator {user_name} with role {role} to container {container_name}")
        # validate inputs to reduce injection risk
        _sanitizer.validate_username(container_name)
        _sanitizer.validate_username(user_name)
        cmd = (
            f"mkdir -p /root/.collaborators && "
            f"mkdir -p /root/.collaborators/{user_name} && "
            f"useradd -M -d /root/.collaborators/{user_name} -s /bin/bash {user_name} && "
            f"echo '{user_name}:{user_name}123' | chpasswd && "
            f"ln -s /root/.collaborators/{user_name} /home/{user_name} && "
            f"chown -R {user_name}:{user_name} /root/.collaborators/{user_name}"
        )
        if role == ROLE.ADMIN:
            cmd += f" && (usermod -aG sudo {user_name} || usermod -aG wheel {user_name})"
        result = container.exec_run(["/bin/sh", "-c", cmd], user="root")
        print(f"Executed command to add collaborator: {cmd}\nExit code: {result.exit_code}\nOutput: {result.output.decode('utf-8', errors='ignore')}")
        return result.exit_code == 0
    except Exception as e:
        print(f"failed to add collaborator:{e}")
        return False


#从container_id中移除user_id对应的用户访问权
def remove_collaborator(container_name: str, user_name: str) -> bool:
    try:
        if extensions.docker_client is None:
            extensions.init_docker()
        container = extensions.docker_client.containers.get(container_name)

        # 删除用户，数据改名存档到 .legacy_ 避免数据丢失
        _sanitizer.validate_username(container_name)
        _sanitizer.validate_username(user_name)
        cmd = (
            f"ts=$(date +%Y%m%d%H%M%S); "
            f"mv /root/.collaborators/{user_name} /root/.collaborators/.legacy_{user_name}_$ts 2>/dev/null || true; "
            # 兼容历史容器：/home/用户名 可能是真实目录（旧 update_role 的 useradd -m 产物），
            # 同样归档进持久化挂载，避免 rm 删不掉真实目录导致操作报错、数据无法找回。
            f"if [ -d /home/{user_name} ] && [ ! -L /home/{user_name} ]; then "
            f"mkdir -p /root/.collaborators && "
            f"mv /home/{user_name} /root/.collaborators/.legacy_{user_name}_$ts.home 2>/dev/null || true; "
            f"fi; "
            f"rm -f /home/{user_name}; "
            # 账号本来就不存在（历史假成功残留 / 重复移除）→ 目标态已达成，幂等成功；
            # userdel 真失败（如账号被占用）→ 非 0 退出，由调用方转失败，避免 Ctrl 误删绑定。
            f"if id -u {user_name} >/dev/null 2>&1; then userdel {user_name} || deluser {user_name}; else exit 0; fi"
        )

        result = container.exec_run(["/bin/sh", "-c", cmd], user="root")
        print(f"Executed command to remove collaborator: {cmd}\nExit code: {result.exit_code}\nOutput: {result.output.decode('utf-8', errors='ignore')}")
        return result.exit_code == 0

    except Exception as e:
        print(f"Failed to remove collaborator: {e}")
        return False


def update_role(container_name: str, user_name: str, updated_role: ROLE) -> bool:
    try:
        if extensions.docker_client is None:
            extensions.init_docker()
        container = extensions.docker_client.containers.get(container_name)

        if updated_role == ROLE.ADMIN:
            #先验证用户存在（如果不存在就创建），再添加到sudo组
            _sanitizer.validate_username(container_name)
            _sanitizer.validate_username(user_name)
            # 新建账号必须与 add_collaborator 保持同一家目录模式：
            # 家目录放 /root/.collaborators/用户名（宿主机持久化挂载内），/home 下只放软链。
            # 若用 useradd -m，家目录会落在容器 overlay2 可写层，容器删除即丢数据，
            # 且后续移除时 mv 归档找不到目录、rm 删不掉真实目录（操作报错且数据不归档）。
            cmd = (
                f"id -u {user_name} || ("
                f"mkdir -p /root/.collaborators/{user_name} && "
                f"useradd -M -d /root/.collaborators/{user_name} -s /bin/bash {user_name} && "
                f"echo '{user_name}:{user_name}123' | chpasswd && "
                f"ln -s /root/.collaborators/{user_name} /home/{user_name} && "
                f"chown -R {user_name}:{user_name} /root/.collaborators/{user_name}"
                f")"
            )
            cmd += f" && (usermod -aG sudo {user_name} || usermod -aG wheel {user_name})"
        elif updated_role == ROLE.COLLABORATOR: # 直接从sudo组里删除用户（如果存在的话），但不删除用户账号
            _sanitizer.validate_username(container_name)
            _sanitizer.validate_username(user_name)
            # 两个特权组都摘除（分号串行，不短路）：旧 `deluser sudo || deluser wheel`
            # 在用户同属 sudo+wheel 时只摘第一个组，降级后仍保留另一组管理员权限。
            # 摘掉任一组即成功（rc=0）；两组都不在 → 退出 1，沿用旧语义由调用方判失败。
            cmd = (
                f"rc=1; "
                f"deluser {user_name} sudo && rc=0; "
                f"deluser {user_name} wheel && rc=0; "
                f"exit $rc"
            )
        elif updated_role == ROLE.ROOT:
            # 直接让root的密码为user_name123
            _sanitizer.validate_username(container_name)
            _sanitizer.validate_username(user_name)
            cmd = (
                f"echo 'root:{user_name}123' | chpasswd && "
                f"(rc=1; deluser {user_name} sudo && rc=0; deluser {user_name} wheel && rc=0; exit $rc) && "
                f"ts=$(date +%Y%m%d%H%M%S); "
                f"mv /root/.collaborators/{user_name} /root/.collaborators/.legacy_{user_name}_$ts 2>/dev/null || true; "
                f"userdel {user_name} || deluser {user_name}; "
                f"rm -f /home/{user_name}"
            )

        else:
            raise ValueError(f"Unknown role: {updated_role}")

        result = container.exec_run(["/bin/sh", "-c", cmd], user="root")
        print(f"Executed command to update role: {cmd}\nExit code: {result.exit_code}\nOutput: {result.output.decode('utf-8', errors='ignore')}")
        return result.exit_code == 0

    except Exception as e:
        print(f"Failed to update role: {e}")
        raise e


def start_container(container_name: str) -> bool:
    """Start a stopped container by name. Returns True on success, False otherwise."""
    try:
        if extensions.docker_client is None:
            extensions.init_docker()
        _sanitizer.validate_username(container_name)
        container = extensions.docker_client.containers.get(container_name)
        # 已开启的容器再次调用 start() 会报错，所以先检查状态避免这个问题
        try:
            container.reload()
        except Exception:
            pass
        status = getattr(container, 'status', None)
        if status == 'running' or status == 'online':
            print(f"Container {container_name} already running (status={status}).")
            return True
        container.start()
        container.reload()
        # 容器无 init，手动起 sshd
        try:
            container.exec_run(["/usr/sbin/sshd"], user="root")
        except Exception:
            pass
        print(f"Started container {container_name}, new status={getattr(container, 'status', None)}")
        return True
    except docker.errors.NotFound:
        print(f"Container {container_name} not found when trying to start.")
        return False
    except Exception as e:
        print(f"Failed to start container {container_name}: {e}")
        return False

# 这里虽然写了timeout参数，但是暂时直接让取默认的10
def stop_container(container_name: str, timeout: int = 10) -> bool:
    """Stop a running container by name. Returns True on success, False otherwise."""
    try:
        if extensions.docker_client is None:
            extensions.init_docker()
        _sanitizer.validate_username(container_name)
        container = extensions.docker_client.containers.get(container_name)
        try:
            container.reload()
        except Exception:
            pass
        status = getattr(container, 'status', None)
        if status != 'running' and status != 'online':
            print(f"Container {container_name} is not running (status={status}); nothing to stop.")
            return True
        container.stop(timeout=timeout)
        container.reload()
        print(f"Stopped container {container_name}, new status={getattr(container, 'status', None)}")
        return True
    except docker.errors.NotFound:
        print(f"Container {container_name} not found when trying to stop.")
        return False
    except Exception as e:
        print(f"Failed to stop container {container_name}: {e}")
        return False

# 这里虽然写了timeout参数，但是暂时直接让取默认的10
def restart_container(container_name: str, timeout: int = 10) -> bool:
    """Restart a container by name. Returns True on success, False otherwise."""
    try:
        if extensions.docker_client is None:
            extensions.init_docker()
        _sanitizer.validate_username(container_name)
        container = extensions.docker_client.containers.get(container_name)
        container.restart(timeout=timeout)
        container.reload()
        container.exec_run(["/usr/sbin/sshd"], user="root")
        print(f"Restarted container {container_name}, new status={getattr(container, 'status', None)}")
        return True
    except docker.errors.NotFound:
        print(f"Container {container_name} not found when trying to restart.")
        return False
    except Exception as e:
        print(f"Failed to restart container {container_name}: {e}")
        return False


def _bounded_command_output(text: str | None, *, limit: int = 10, max_chars: int = 1000) -> str:
    """把一条命令的输出压成"最多 limit 行 / max_chars 字符"，供错误信息使用。

    截断时**明确写出省略了多少行**——静默截断会让人以为输出就这么多（与
    `_build_log_tail` 同一个用意：错误信息要能被读懂，也不能无限长）。
    """
    lines = [line for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return ""
    body = "\n".join(lines[:limit])[:max_chars]
    if len(lines) > limit:
        body += f"\n…（其余 {len(lines) - limit} 行已省略）"
    return body


def clean_mount(mount_path: str) -> bool:
    """清理已删除容器的宿主机 mount 目录（校验 + 执行都在 service 层）。

    安全检查：路径必须位于 NODE_CONTAINERS_BASE 下且包含 /containers/，
    realpath 规范化防止 ../ 路径穿越绕过检查。超时抛 subprocess.TimeoutExpired；
    rm 删除失败抛 RuntimeError（带 rm 的 stderr；幂等：路径不存在 rm -rf 仍返回 0）。
    """
    base = os.path.realpath(os.getenv("NODE_CONTAINERS_BASE", "/home"))
    real = os.path.realpath(str(mount_path))
    if not real.startswith(base + os.sep) or "/containers/" not in real:
        raise ValueError("invalid mount_path")
    # 删除失败抛 RuntimeError（端点转 500），不再假成功 → Ctrl 不会误标 cleaned_at，可重试。
    #
    # **必须把 rm 自己的 stderr 带上**：吞掉它，日志里就只剩一句 `rc=1`，分不清是权限、
    # 只读文件系统还是路径不对。2026-09 实测踩到：容器内以 root 写进挂载目录的东西，在
    # 宿主上是 root:root（`.cache` 还是 0700），Node 以非 root 运行时 rm 报的是
    # `Permission denied`——那条 stderr 被丢掉之后，这个失败完全不可读，只能靠人去翻目录。
    r = subprocess.run(
        ["rm", "-rf", real], timeout=30, check=False,
        capture_output=True, text=True, errors="replace",
    )
    if r.returncode != 0:
        detail = _bounded_command_output(r.stderr) or _bounded_command_output(r.stdout)
        suffix = f"\n--- rm output ---\n{detail}" if detail else ""
        raise RuntimeError(f"rm -rf failed (rc={r.returncode}): {real}{suffix}")
    return True


def container_exists(container_name: str) -> bool:
    """同名预检：容器是否已存在（创建前冲突检查）。

    docker 不可达时抛异常（由端点转为 docker_check_failed），NotFound 视为不存在。
    """
    if extensions.docker_client is None:
        extensions.init_docker()
    _sanitizer.validate_username(container_name)
    try:
        extensions.docker_client.containers.get(container_name)
        return True
    except docker.errors.NotFound:
        return False


def pause_container(container_name: str, action: str = "pause") -> bool:
    """暂停/恢复容器。action: 'pause'|'unpause'。返回 True on success。"""
    try:
        if extensions.docker_client is None:
            extensions.init_docker()
        _sanitizer.validate_username(container_name)
        container = extensions.docker_client.containers.get(container_name)
        if action == "pause":
            container.pause()
        else:
            container.unpause()
        return True
    except docker.errors.NotFound:
        logger.warning("Container %s not found when trying to %s.", container_name, action)
        return False
    except Exception as e:
        logger.warning("Failed to %s container %s: %s", action, container_name, e)
        return False


def list_container_status() -> dict:
    """全量容器状态快照（读侧 list）：{name: {"source", "status", ...}}。

    桥接：读取逻辑在 docker_operates.status_cache.ContainerStatusCache.list_states
    （pending 优先 + cache 兜底合并）。单容器过滤由此承担。
    """
    return extensions.status_cache.list_states()


def list_last_ssh() -> dict:
    """全量 SSH 登录时间快照（读侧 list）：{name: {"last_ssh_connect_time", "updated_at"}}。

    桥接：采集在 docker_operates.last_ssh_cache.LastSshCache（滚动流水线 + TTL 节流），
    本函数只读缓存。单容器过滤由此承担：未采到/非运行态 → last_ssh_connect_time=None
    （Ctrl 侧保持 DB 旧值，与迁移前语义一致）。
    """
    snap = extensions.last_ssh_cache.snapshot()
    result = {}
    for name, entry in snap.items():
        updated = entry.get("updated_at")
        result[name] = {
            "last_ssh_connect_time": entry.get("value"),
            "updated_at": updated.strftime('%Y-%m-%dT%H:%M:%S') if updated else None,
        }
    return result


def list_disk_usage() -> dict:
    """全量磁盘用量快照（读侧 list）：{"machine_disk": {...}, "containers": {name: usage}}。

    桥接：采集在 docker_operates.disk_usage_cache.DiskUsageCache（滚动流水线 + TTL 节流），
    本函数只读缓存（可能略旧，TTL 900s 内）。单容器过滤由此承担：快照未含 → 该容器
    暂无用量数据。
    """
    return extensions.disk_usage_cache.snapshot()


def list_sys_snapshot() -> dict | None:
    """全量系统快照（读侧 list）：静态硬件 + 动态指标。

    桥接：采集在 docker_operates.sys_cache.SysSnapshotCache（后台循环 + TTL），
    本函数只读缓存。静态字段供首连 enrollment_profile / 建档使用。
    """
    return extensions.sys_cache.snapshot()


def static_sys_snapshot() -> dict | None:
    """静态硬件快照：首连 enrollment_profile 与建档用。

    首连可能早于后台线程第一次采集，因此这里允许触发一次低频静态采集。
    """
    return extensions.sys_cache.collect_static()


####################################################
