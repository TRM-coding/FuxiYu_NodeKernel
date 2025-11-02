#TODO:完成实现

from ..constant import *
from typing import TypedDict
from ..config import KeyConfig
from ..utils.CheckKeys import load_keys
from ..utils.Container import Container
import requests
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey
from ..extensions import docker_client
import docker
from typing import NamedTuple






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

# 将user_name作为admin，创建port新容器
def create_container(config:Container.Config_info)->CreateContainerReturn:
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
    
    container = docker_client.containers.run(
        config.image,
        "tail -f /dev/null",   # 保证容器一直运行
        detach=True,
        tty=True,
        ports={"22/tcp": config.port},   # ssh端口映射
        mem_limit=mem_limit,
        cpu_quota=cpu_quota,
        device_requests=device_requests
    )
    name = f"{config.user_name}_{container.short_id}"
    container.rename(name)
    container.exec_run("apt-get update && apt-get install -y openssh-server", user="root")
    container.exec_run("service ssh start", user="root")
    # 设置 root 密码为 root123
    container.exec_run("echo 'root:root123' | chpasswd", user="root")
    # 修改 sshd_config，允许 root 密码登录
    container.exec_run("sed -i 's/^#*PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config", user="root")
    container.exec_run("sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config", user="root")

    # 重启 ssh 服务
    container.exec_run("service ssh restart", user="root")
    return CreateContainerReturn(container.id,container.name)

#删除容器并删除其所有者记录
def remove_container(container_id: str) -> int:
    try:
        container = docker_client.containers.get(container_id)
        container.remove(force=True)  # force=True 避免容器在运行时报错
        return RemoveContinaerReturn.SUCCESS
    except docker.errors.NotFound:
        print(f"Container {container_id} not found.")
        return RemoveContinaerReturn.NOTFOUND
    except Exception as e:
        print(f"Failed to remove container {container_id}: {e}")
        return RemoveContinaerReturn.FAILED

#将container_id对应的容器新增user_id作为collaborator,其权限为role
def add_collaborator(container_id:int,user_name:str,role:ROLE)->bool:
    try:
        container=docker_client.containers.get(container_id)
        cmd = f"useradd -m -s /bin/bash {user_name} && echo '{user_name}:{user_name}' | chpasswd"
        if role == ROLE.ADMIN:
            cmd += f" && usermod -aG sudo {user_name}"
        result = container.exec_run(cmd, user="root")
        return result.exit_code == 0
    except Exception as e:
        print(f"failed to add collaborator:{e}")
        return False


#从container_id中移除user_id对应的用户访问权
def remove_collaborator(container_id: str, user_name: str) -> bool:
    try:
        container = docker_client.containers.get(container_id)

        # 删除用户，并且一并删除家目录 (-r)
        cmd = f"userdel -r {user_name}"

        result = container.exec_run(cmd, user="root")
        return result.exit_code == 0

    except Exception as e:
        print(f"Failed to remove collaborator: {e}")
        return False

def update_role(container_id: str, user_name: str, updated_role: str) -> bool:
    try:
        container = docker_client.containers.get(container_id)

        if updated_role == ROLE.ADMIN:
            cmd = f"usermod -aG sudo {user_name}"
        elif updated_role == ROLE.COLLABORATOR:
            cmd = f"deluser {user_name} sudo"
        else:
            raise ValueError(f"Unknown role: {updated_role}")

        result = container.exec_run(cmd, user="root")
        return result.exit_code == 0

    except Exception as e:
        print(f"Failed to update role: {e}")
        return False


####################################################
