# 与他们相关的参数有必要被严格验证和过滤，或者改用更安全的方式（如直接传递参数列表而不是 shell 命令字符串）

from ..constant import *
from ..config import KeyConfig, NodeProxyConfig
from ..utils.Container import Container
from .. import extensions
from ..utils.CheckKeys import load_keys
# from ..constant import *
from typing import TypedDict
# from ..config import KeyConfig
# from ..utils.CheckKeys import load_keys
# from ..utils.Container import Container
import requests
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey
import base64
# from ..extensions import docker_client
import docker
from docker.types import Mount
import os
from typing import NamedTuple
from ..utils import sanitizer as _sanitizer
import subprocess
import threading
import time
from datetime import datetime
import shutil






#Return API Definition
####################################################
class CreateContainerReturn(NamedTuple):
    container_id:str
    container_name:str

class RemoveContinaerReturn:
    SUCCESS=0
    NOTFOUND=1
    FAILED=2
####################################################



#Function Implementation
####################################################

# 将owner_name作为root，创建port新容器
def create_container(owner_name: str, config:Container.Config_info, public_key: str | None = None)->CreateContainerReturn:
    if extensions.docker_client is None:
        extensions.init_docker()

    print(f"Creating container for owner={owner_name} with config={config} and public_key={public_key}")
    # validate owner_name early because it's used as host path component
    try:
        _sanitizer.validate_username(owner_name)
    except Exception as e:
        raise RuntimeError(f"unsafe owner_name: {e}")
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
        # When specific GPU ids are provided, do NOT set 'count' because
        # Docker rejects DeviceRequest with both Count and DeviceIDs set.
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
    container = extensions.docker_client.containers.run(
        config.image,
        "tail -f /dev/null",   # 保证容器一直运行
        detach=True,
        tty=True,
        name=name,
        
        ports={"22/tcp": config.port},   # ssh端口映射
        mem_limit=mem_limit,
        cpuset_cpus=cpuset_cpus,
        device_requests=device_requests,
        mounts=mounts,
        **({"shm_size": shm_size_bytes} if shm_size_bytes is not None else {})
    )
    print(f"Container created with ID={container.id} and name={name}")


    container.reload()
    print(f"Container status after creation: {container.status}")
    try:
        print("Container mounts after reload:", container.attrs.get('Mounts'))
    except Exception:
        print("Container mounts info unavailable")



    # container.exec_run("service ssh restart", user="root")
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
    # 下面的命令执行可能会比较慢，所以设置了较长的超时时间（120秒），
    # 以避免某些环境下 apt-get 卡死导致的问题。apt-get 有时会因为签名/证书
    # 问题失败（例如镜像环境或时间不同步），因此在失败时尝试一次回退策略，
    # 但不要因为安装失败就删除已创建的容器——只记录并继续。

    # Configure network proxy inside container BEFORE any network operations.
    # Read proxy from NodeProxyConfig so it can be changed via env/config.
    PROXY_URL = getattr(NodeProxyConfig, 'PROXY_HOST', None)
    if PROXY_URL:
        try:
            # write environment variables so new processes see the proxy
            _run(container, (
                "printf 'http_proxy=\"%s\"\nhttps_proxy=\"%s\"\nHTTP_PROXY=\"%s\"\nHTTPS_PROXY=\"%s\"\n' "
                % (PROXY_URL, PROXY_URL, PROXY_URL, PROXY_URL)
                + "> /etc/environment"
            ))
            # configure apt to use the proxy before the first apt network access
            _run(container, (
                "mkdir -p /etc/apt/apt.conf.d && printf 'Acquire::http::Proxy \"%s\";\nAcquire::https::Proxy \"%s\";\n' "
                % (PROXY_URL, PROXY_URL)
                + "> /etc/apt/apt.conf.d/99proxy"
            ))
            _run(container, (
                "grep -i proxy /etc/environment /etc/apt/apt.conf.d/99proxy"
            ))
            print(f"Proxy configured inside container: {PROXY_URL}")
        except Exception as e:
            print(f"Failed to configure proxy inside container: {e}")
    else:
        print("No proxy configured for container network setup.")

    ssh_ready = False
    try:
        _run(container, "apt-get update", timeout_sec=300)
        _run(container, "DEBIAN_FRONTEND=noninteractive apt-get install -y openssh-server", timeout_sec=600)
        _run(container, "mkdir -p /run/sshd")
        _run(container, "ssh-keygen -A")
        ssh_ready = True
    except Exception as e:
        print(f"apt-get update/install failed: {e}\nAttempting fallback sequence (clean + relaxed update + allow-unauthenticated install)")
        try:
            _run(container, "apt-get clean")
            _run(container, "rm -rf /var/lib/apt/lists/*")
            _run(container, "apt-get update -o Acquire::AllowInsecureRepositories=true -o Acquire::Check-Valid-Until=false", timeout_sec=300)
            _run(container, "DEBIAN_FRONTEND=noninteractive apt-get install -y --allow-unauthenticated openssh-server", timeout_sec=600)
            _run(container, "mkdir -p /run/sshd")
            _run(container, "ssh-keygen -A")
            ssh_ready = True
        except Exception as e2:
            print(f"Fallback apt-get sequence also failed: {e2}. Continuing without openssh-server; container created but SSH may be unavailable.")
    # 初始密码为 owner_name + "123"，用户可以登录后再改密码（也可以直接提供公钥登录）
    _run(container, f"echo 'root:{owner_name}123' | chpasswd")
    try:
        _sanitizer.validate_username(owner_name)
    except Exception as e:
        raise RuntimeError(f"unsafe owner_name: {e}")
    if ssh_ready:
        _run(container, "sed -i 's/^#*PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config")
        _run(container, "sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config")
    else:
        print("Skipping sshd_config edits because openssh-server is not installed.")

    # 不用 service（容器里不一定有 init），直接启动 sshd（会后台守护）
    if ssh_ready:
        try:
            _run(container, "/usr/sbin/sshd")
        except Exception as e:
            print(f"Failed to start sshd inside container: {e}. SSH may be unavailable.")
    # 使得公钥可选 （如果提供了公钥则安装，否则只用密码登录）
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

    return CreateContainerReturn(container.id,container.name)

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
            f"userdel {user_name} || deluser {user_name}; "
            f"rm -f /home/{user_name}"
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
            cmd = f"deluser {user_name} sudo || deluser {user_name} wheel"
        elif updated_role == ROLE.ROOT:
            # 直接让root的密码为user_name123
            _sanitizer.validate_username(container_name)
            _sanitizer.validate_username(user_name)
            cmd = (
                f"echo 'root:{user_name}123' | chpasswd && "
                f"(deluser {user_name} sudo || deluser {user_name} wheel) && "
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


def get_last_ssh_connect_time(container_name: str) -> str | None:
    """
    Return the last SSH connection time string of the container.
    If not found or any error occurs, return None.
    """
    try:
        if extensions.docker_client is None:
            extensions.init_docker()

        _sanitizer.validate_username(container_name)
        container = extensions.docker_client.containers.get(container_name)

        # 容器未运行则跳过 exec_run，避免等待 Docker 返回 409 耗时
        try:
            _state = (container.attrs.get('State') or {}).get('Status', '')
        except Exception:
            _state = ''
        if str(_state).lower() in ('exited', 'dead', 'created', 'paused', 'removing'):
            return None

        # Prefer `last` for authoritative login sessions, then fallback to sshd logs.
        # TZ=UTC 强制 last 输出 UTC 时间，Ctrl 侧全程 UTC 无需转换。
        cmd = r"""
if command -v last >/dev/null 2>&1; then
  v="$(TZ=UTC last -w -i 2>/dev/null | awk '$1!="wtmp" && $1!="reboot" && $1!="btmp" && $1!="runlevel" {print; exit}')"
  if [ -n "$v" ]; then
    echo "$v"
    exit 0
  fi
fi

if [ -f /var/log/auth.log ]; then
  line="$(grep -E 'sshd.*(Accepted|session opened)' /var/log/auth.log | tail -n 1)"
elif [ -f /var/log/secure ]; then
  line="$(grep -E 'sshd.*(Accepted|session opened)' /var/log/secure | tail -n 1)"
else
  line=""
fi
echo "$line"
"""

        result = container.exec_run(["/bin/sh", "-c", cmd], user="root")
        output = result.output.decode("utf-8", errors="ignore").strip()
        if hasattr(result, "exit_code") and result.exit_code != 0:
            print(f"Failed to query last ssh connect time for {container_name}: exit={result.exit_code}, output={output}")
            return None
        return output if output else None
    except docker.errors.NotFound:
        print(f"Container {container_name} not found when querying last ssh connect time.")
        return None
    except Exception as e:
        print(f"Failed to get last ssh connect time for {container_name}: {e}")
        return None


# bind mount 磁盘用量缓存: {path: {"bytes": int, "updated_at": datetime, "running": bool}}
_bind_disk_cache: dict[str, dict] = {}
_bind_cache_lock = threading.Lock()
_BIND_CACHE_TTL_SEC = 900  # 15 分钟


def _du_background(bind_path: str) -> None:
    """在后台线程中跑 du -sb，完成后写入缓存。"""
    try:
        r = subprocess.run(
            ["du", "-sb", bind_path],
            capture_output=True, text=True, timeout=300,  # 大目录最多等 5 分钟
        )
        out = r.stdout.strip()
        if out:
            size = int(out.split()[0])
            with _bind_cache_lock:
                _bind_disk_cache[bind_path] = {
                    "bytes": size,
                    "running": False,
                    "updated_at": datetime.utcnow(),
                }
            return
    except subprocess.TimeoutExpired:
        pass
    except Exception:
        pass
    # 失败: 标记 running=False，下次请求会重试
    with _bind_cache_lock:
        entry = _bind_disk_cache.get(bind_path)
        if entry:
            entry["running"] = False


def _resolve_bind_disk(bind_path: str) -> dict:
    """
    解析 bind mount 磁盘用量（缓存 + 异步后台 du）。
    返回: {"bind_mount_bytes": int|None, "bind_mount_source": str, "bind_mount_path": str}
    """
    with _bind_cache_lock:
        entry = _bind_disk_cache.get(bind_path)

    if entry and entry.get("bytes") is not None:
        age = (datetime.utcnow() - entry["updated_at"]).total_seconds()
        if age < _BIND_CACHE_TTL_SEC:
            # 新鲜缓存，直接返回
            return {
                "bind_mount_bytes": entry["bytes"],
                "bind_mount_source": "fresh" if not entry.get("running") else "cached",
                "bind_mount_path": bind_path,
            }
        # 过期: 返回旧值，触发后台刷新
        if not entry.get("running"):
            with _bind_cache_lock:
                entry["running"] = True
            threading.Thread(target=_du_background, args=(bind_path,), daemon=True).start()
        return {
            "bind_mount_bytes": entry["bytes"],
            "bind_mount_source": "stale",
            "bind_mount_path": bind_path,
        }

    # 无缓存: 触发后台 du，先返回 None
    if not entry:
        with _bind_cache_lock:
            _bind_disk_cache[bind_path] = {"bytes": None, "running": True, "updated_at": datetime.utcnow()}
        threading.Thread(target=_du_background, args=(bind_path,), daemon=True).start()
        return {
            "bind_mount_bytes": None,
            "bind_mount_source": "measuring",
            "bind_mount_path": bind_path,
        }

    # 正在跑 du（entry 存在但 bytes=None 且 running=True）
    if entry.get("running"):
        return {
            "bind_mount_bytes": None,
            "bind_mount_source": "measuring",
            "bind_mount_path": bind_path,
        }

    # 上一轮 du 失败（entry 存在，bytes=None，running=False），重试
    with _bind_cache_lock:
        entry["running"] = True
    threading.Thread(target=_du_background, args=(bind_path,), daemon=True).start()
    return {
        "bind_mount_bytes": None,
        "bind_mount_source": "measuring",
        "bind_mount_path": bind_path,
    }


def get_disk_usage(container_name: str) -> dict:
    """
    获取单个容器的磁盘使用情况（只读，两路求和）。
    - overlay2 可写层: Docker SDK container.attrs['SizeRw']
    - bind mount 目录: du -sb <Source> (从 attrs['Mounts'] 取 /root 的 Source)
    - 宿主机磁盘: shutil.disk_usage("/home")

    两路互斥（bind mount 把 /root 从 overlay2 抽离），直接相加即总占用。
    函数不抛异常，所有错误都 swallowing 到返回 dict 中。
    """
    result = {
        "machine_disk": {"total_gb": 0.0, "used_gb": 0.0, "free_gb": 0.0, "percent": 0.0},
        "container": {
            "container_name": container_name,
            "overlay_rw_bytes": None,
            "bind_mount_bytes": None,
            "bind_mount_path": None,
            "bind_mount_source": "none",
            "total_bytes": 0,
        },
    }

    # --- 宿主机磁盘 ---
    try:
        usage = shutil.disk_usage(os.getenv("NODE_CONTAINERS_BASE", "/home"))
        total_gb = usage.total / (1024**3)
        used_gb = usage.used / (1024**3)
        free_gb = usage.free / (1024**3)
        percent = (usage.used / usage.total * 100) if usage.total > 0 else 0.0
        result["machine_disk"] = {
            "total_gb": round(total_gb, 1),
            "used_gb": round(used_gb, 1),
            "free_gb": round(free_gb, 1),
            "percent": round(percent, 1),
        }
    except Exception as e:
        result["machine_disk"]["error"] = str(e)

    # --- 容器 ---
    try:
        if extensions.docker_client is None:
            extensions.init_docker()
        container = extensions.docker_client.containers.get(container_name)
    except docker.errors.NotFound:
        result["container"]["error"] = "container_not_found"
        return result
    except Exception as e:
        result["container"]["error"] = f"docker_access_failed: {e}"
        return result

    # 第一路: overlay2 可写层
    try:
        size_rw = (container.attrs.get('SizeRw') or 0)
        if size_rw <= 0:
            try:
                df = extensions.docker_client.df()
                for c_df in df.get('Containers', []) or []:
                    names = c_df.get('Names', []) or []
                    if f"/{container_name}" in names:
                        size_rw = c_df.get('SizeRw', 0) or 0
                        break
            except Exception:
                pass
                size_rw = 0
        result["container"]["overlay_rw_bytes"] = int(size_rw)
    except Exception as e:
        result["container"]["overlay_rw_bytes"] = None
        result["container"]["overlay_rw_error"] = str(e)

    # 第二路: bind mount 目录 (Destination == "/root")，使用缓存 + 异步后台 du
    try:
        mounts = container.attrs.get('Mounts', []) or []
        bind_root_source = None
        for m in mounts:
            if m.get('Destination') == '/root' and m.get('Type') == 'bind':
                bind_root_source = m.get('Source')
                break
        if bind_root_source:
            resolved = _resolve_bind_disk(bind_root_source)
            result["container"]["bind_mount_path"] = resolved["bind_mount_path"]
            result["container"]["bind_mount_bytes"] = resolved["bind_mount_bytes"]
            result["container"]["bind_mount_source"] = resolved["bind_mount_source"]
        else:
            result["container"]["bind_mount_bytes"] = None
            result["container"]["bind_mount_error"] = "no_bind_mount_for_root"
    except Exception as e:
        result["container"]["bind_mount_bytes"] = None
        result["container"]["bind_mount_error"] = str(e)

    # 总和
    rw = result["container"]["overlay_rw_bytes"] or 0
    bm = result["container"]["bind_mount_bytes"] or 0
    result["container"]["total_bytes"] = rw + bm

    def _h(b): return f"{b/1024/1024:.0f}M" if b >= 1024*1024 else f"{b/1024:.0f}K" if b >= 1024 else f"{b}B"
    src = result["container"].get("bind_mount_source", "none")
    print(f"[disk-check] {container_name} overlay={_h(rw)} bind={_h(bm)} bind_src={src} total={_h(rw + bm)}")
    return result


####################################################
