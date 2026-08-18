import docker
from .docker_operates.status_cache import ContainerStatusCache
from .docker_operates.event_log import ContainerEventLog
from .docker_operates.last_ssh_cache import LastSshCache

docker_client=None
# 容器状态缓存（docker events 订阅 + 定时对账 → 内存缓存），Ctrl 高频读取目标
status_cache = ContainerStatusCache()
# 容器运行事件记录（events 捕获 → 环形缓冲），供时间轴/告警/WSS 推送
event_log = ContainerEventLog()
# SSH 登录时间缓存（滚动采集流水线 → 内存缓存），/container_last_ssh_time 读取目标
last_ssh_cache = LastSshCache()


def init_docker():
    global docker_client
    docker_client = docker.from_env()
