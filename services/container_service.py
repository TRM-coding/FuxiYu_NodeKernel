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
    
    # Docker needs an explicit memswap_limit equal to mem_limit to fully disable swap.
    # Otherwise, leaving memswap_limit unset may allow Docker's default swap behavior.
    swap_amt = int(getattr(config, 'swap_memory', 0) or 0)
    memswap_limit = f"{config.memory}g" if swap_amt <= 0 else f"{config.memory + swap_amt}g"

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

    print(f"DEBUG: cpu_list={cpu_list}, gpu_list={gpu_list}, mem_limit={mem_limit}, memswap_limit={memswap_limit}, device_requests={device_requests}")
    name = f"{config.name}" # 名字自定义
    # 将container的/root目录挂载到宿主机的/home/owner_name/containers/name目录，方便后续调试和数据持久化（虽然现在设计上容器是临时的，但以防万一）。这个路径也要确保合法和安全，避免注入攻击或路径遍历等问题。
    host_root_mount = os.path.join("/home", owner_name, "containers", name)
        
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
        memswap_limit=memswap_limit,
        cpuset_cpus=cpuset_cpus,
        device_requests=device_requests,
        mounts=mounts
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
    try:
        # write environment variables so new processes see the proxy
        _run(container, (
            "printf 'http_proxy=\"%s\"\nhttps_proxy=\"%s\"\nHTTP_PROXY=\"%s\"\nHTTPS_PROXY=\"%s\"\n' "
            % (PROXY_URL, PROXY_URL, PROXY_URL, PROXY_URL)
            + "> /etc/environment"
        ))
        _run(container, (
            "source /etc/environment && env | grep -i proxy"
        ))
        # configure apt to use the proxy
        _run(container, (
            "mkdir -p /etc/apt/apt.conf.d && printf 'Acquire::http::Proxy \"%s\";\nAcquire::https::Proxy \"%s\";\n' "
            % (PROXY_URL, PROXY_URL)
            + "> /etc/apt/apt.conf.d/99proxy"
        ))
        # export for the current shell (helps immediate exec_run commands)
        _run(container, f"export http_proxy={PROXY_URL} https_proxy={PROXY_URL} HTTP_PROXY={PROXY_URL} HTTPS_PROXY={PROXY_URL} || true")
        print(f"Proxy configured inside container: {PROXY_URL}")
    except Exception as e:
        print(f"Failed to configure proxy inside container: {e}")

    try:
        _run(container, "apt-get update")
        _run(container, "DEBIAN_FRONTEND=noninteractive apt-get install -y openssh-server")
        _run(container, "mkdir -p /run/sshd")
        _run(container, "ssh-keygen -A")
    except Exception as e:
        print(f"apt-get update/install failed: {e}\nAttempting fallback sequence (clean + relaxed update + allow-unauthenticated install)")
        try:
            _run(container, "apt-get clean")
            _run(container, "rm -rf /var/lib/apt/lists/*")
            _run(container, "apt-get update -o Acquire::AllowInsecureRepositories=true -o Acquire::Check-Valid-Until=false")
            _run(container, "DEBIAN_FRONTEND=noninteractive apt-get install -y --allow-unauthenticated openssh-server")
            _run(container, "mkdir -p /run/sshd")
            _run(container, "ssh-keygen -A")
        except Exception as e2:
            print(f"Fallback apt-get sequence also failed: {e2}. Continuing without openssh-server; container created but SSH may be unavailable.")
    # 初始密码为 owner_name + "123"，用户可以登录后再改密码（也可以直接提供公钥登录）
    _run(container, f"echo 'root:{owner_name}123' | chpasswd")
    try:
        _sanitizer.validate_username(owner_name)
    except Exception as e:
        raise RuntimeError(f"unsafe owner_name: {e}")
    _run(container, "sed -i 's/^#*PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config")
    _run(container, "sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config")

    # 不用 service（容器里不一定有 init），直接启动 sshd（会后台守护）
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
        cmd = f"useradd -m -s /bin/bash {user_name} && echo '{user_name}:{user_name}123' | chpasswd"
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

        # 删除用户，并且一并删除home目录 (-r)
        _sanitizer.validate_username(container_name)
        _sanitizer.validate_username(user_name)
        cmd = f"userdel -r {user_name} || deluser {user_name}"

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
            cmd = f"id -u {user_name} || useradd -m -s /bin/bash {user_name} && echo '{user_name}:{user_name}123' | chpasswd"
            cmd += f" && (usermod -aG sudo {user_name} || usermod -aG wheel {user_name})"
        elif updated_role == ROLE.COLLABORATOR: # 直接从sudo组里删除用户（如果存在的话），但不删除用户账号
            _sanitizer.validate_username(container_name)
            _sanitizer.validate_username(user_name)
            cmd = f"deluser {user_name} sudo || deluser {user_name} wheel"
        elif updated_role == ROLE.ROOT:
            # 直接让root的密码为user_name123
            _sanitizer.validate_username(container_name)
            _sanitizer.validate_username(user_name)
            cmd = f"echo 'root:{user_name}123' | chpasswd"
            # 不论是collaborator还是admin都要把原来的权限去掉，避免出现权限叠加的情况（虽然现在设计上collaborator和admin是互斥的，但以防万一）
            #   先删sudo/wheel
            cmd += f" && deluser {user_name} sudo || deluser {user_name} wheel"
            #   再删掉用户（如果存在的话），避免出现同名用户导致的权限问题
            cmd += f" && userdel -r {user_name} || deluser {user_name}"

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
        container.exec_run("service ssh restart", user="root")
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

        # Prefer `last` for authoritative login sessions, then fallback to sshd logs.
        cmd = r"""
if command -v last >/dev/null 2>&1; then
  v="$(last -w -i 2>/dev/null | awk '$1!="wtmp" && $1!="reboot" && $1!="btmp" && $1!="runlevel" {print; exit}')"
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


####################################################
