import docker
from .docker_operates.status_cache import ContainerStatusCache
from .docker_operates.event_log import ContainerEventLog
from .docker_operates.last_ssh_cache import LastSshCache
from .docker_operates.disk_usage_cache import DiskUsageCache
from .docker_operates.sys_cache import SysSnapshotCache

docker_client=None
# 容器状态缓存（docker events 订阅 + 定时对账 → 内存缓存），Ctrl 高频读取目标
status_cache = ContainerStatusCache()
# 容器运行事件记录（events 捕获 → 环形缓冲），供时间轴/告警/WSS 推送
event_log = ContainerEventLog()
# SSH 登录时间缓存（滚动采集流水线 → 内存缓存），/container_last_ssh_time 读取目标
last_ssh_cache = LastSshCache()
# 磁盘用量缓存（滚动采集流水线 → 内存缓存），/check_disk_usage 读取目标
disk_usage_cache = DiskUsageCache()
# 宿主机系统快照缓存（静态硬件 + 动态指标），sys_snapshot 推送 / 首连建档素材
sys_cache = SysSnapshotCache()


def init_docker():
    global docker_client
    docker_client = docker.from_env()
