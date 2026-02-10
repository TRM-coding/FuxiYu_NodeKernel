# IMPORTANT TODO: 应当指出，这个文件的几乎所有带有参数的exec_run调用都存在潜在的命令注入风险
# 与他们相关的参数有必要被严格验证和过滤，或者改用更安全的方式（如直接传递参数列表而不是 shell 命令字符串）

from ..constant import *
from ..config import KeyConfig
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
    cpu_quota = config.cpu_number * 100000
    mem_limit = f"{config.memory}g"
    device_requests = None
    if config.gpu_list:
        device_requests = [
            docker.types.DeviceRequest(
                count=len(config.gpu_list),
                device_ids=[str(x) for x in config.gpu_list],
                capabilities=[["gpu"]]
            )
        ]
    
    print(f"DEBUG: cpu_quota={cpu_quota}, mem_limit={mem_limit}, device_requests={device_requests}")
    name = f"{config.name}" # 名字自定义
    # avoid creating a random-name container: check if a container with the desired name already exists
    try:
        existing = extensions.docker_client.containers.get(name)
        print(f"Container with name {name} already exists: id={existing.id} status={existing.status}")
        raise RuntimeError(f"container {name} already exists on this host")
    except docker.errors.NotFound:
        # good, proceed to create with explicit name
        pass

    container = extensions.docker_client.containers.run(
        config.image,
        "tail -f /dev/null",   # 保证容器一直运行
        detach=True,
        tty=True,
        name=name,
        ports={"22/tcp": config.port},   # ssh端口映射
        mem_limit=mem_limit,
        cpu_quota=cpu_quota,
        device_requests=device_requests
    )
    print(f"Container created with ID={container.id} and name={name}")
    container.reload()
    print(f"Container status after creation: {container.status}")
    # container.exec_run("apt-get update && apt-get install -y openssh-server", user="root")
    # container.exec_run("service ssh start", user="root")
    # # 设置 root 密码为 root123
    # container.exec_run("echo 'root:root123' | chpasswd", user="root")
    # # 修改 sshd_config，允许 root 密码登录
    # container.exec_run("sed -i 's/^#*PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config", user="root")
    # container.exec_run("sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config", user="root")

    # # 重启 ssh 服务
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
                # r may be a tuple like (exit_code, output)
                exit_code = int(r[0])
            except Exception:
                exit_code = 0
        print(f"Executed command: {cmd}\nExit code: {exit_code}\nOutput: {out}")
        if exit_code != 0:
            raise RuntimeError(f"cmd failed: {cmd}\nexit={exit_code}\noutput={out}")
        return r

    _run(container, "apt-get update")
    _run(container, "DEBIAN_FRONTEND=noninteractive apt-get install -y openssh-server")
    _run(container, "mkdir -p /run/sshd")
    _run(container, "ssh-keygen -A")

    _run(container, f"echo 'root:{owner_name}123' | chpasswd")
    try:
        _sanitizer.validate_username(owner_name)
    except Exception as e:
        raise RuntimeError(f"unsafe owner_name: {e}")
    _run(container, "sed -i 's/^#*PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config")
    _run(container, "sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config")

    # 不用 service（容器里不一定有 init），直接启动 sshd（会后台守护）
    _run(container, "/usr/sbin/sshd")
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
                "chmod 600 /root/.ssh/authorized_keys && chown -R root:root /root/.ssh"
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

        container = extensions.docker_client.containers.get(container_name)
        container.remove(force=True)  # force=True 避免容器在运行时报错
        return RemoveContinaerReturn.SUCCESS
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


####################################################
