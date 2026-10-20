from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .common import EmptyConfig, SuccessResponse


ContainerStatus = Literal[
    "building",
    "creating",
    "starting",
    "stopping",
    "restarting",
    "pausing",
    "unpausing",
    "ready_check",
    "online",
    "offline",
    "paused",
    "failed",
    "unknown",
]

CollaboratorRole = Literal["admin", "collaborator"]
UpdatedRole = Literal["admin", "collaborator", "root"]
PauseAction = Literal["pause", "unpause"]

ActionName = Literal["create", "start", "stop", "restart", "pause", "unpause"]
ActionPhase = Literal[
    "accepted",
    "confirmed",
    "idempotent_confirmed",
    "failed",
    "unconfirmed",
    "superseded",
    "timed_out",
]
MountPathStatus = Literal["resolved", "unresolved", "not_running", "no_bind"]


class ActionRef(BaseModel):
    """Node 本进程内的动作引用，不是 Q70 跨进程删除身份。"""

    node_epoch: str
    generation: int = Field(ge=0)
    seq: int = Field(ge=0)


class LastAction(BaseModel):
    """最新本地动作的只读诊断投影；失败不改变运行态。"""

    ref: ActionRef
    action: ActionName
    phase: ActionPhase
    error_reason: str | None = None


class ContainerConfig(BaseModel):
    gpu_list: list[int] = Field(default_factory=list, description="GPU device ids. Empty means CPU only.")
    cpu_number: int = Field(..., ge=0)
    memory: int = Field(..., ge=0, description="Memory limit in GB")
    shared_memory: int = Field(..., ge=0, description="Shared memory size in GB")
    name: str
    # **遗留字段，Node 不采用**：宿主端口自 2026-09 起由 Node 自己分配并显式绑定（见
    # docker_operates/port_allocator.py），Ctrl 现在恒发 0。保留它是为了不动 wire 契约——
    # 但谁都不要拿它去起容器：那会让端口重新变成"Ctrl 猜、docker 另有事实"的局面。
    port: int = Field(..., ge=0, le=65535)
    image: str


class ImageBuildConfig(BaseModel):
    dockerfile_text: str = Field(default="", description="Ctrl 生成的最终 Dockerfile 文本。")
    image_tag: str = Field(default="", description="最终 build 后用于 run 的镜像 tag。")


class ContainerNameConfig(BaseModel):
    container_name: str | None = None
    name: str | None = Field(default=None, description="Backward-compatible alias for container_name")


class ContainerOperationAcceptedResponse(SuccessResponse):
    container_status: ContainerStatus
    container_name: str
    action_ref: ActionRef | None = None


class RestoreAccountConfig(BaseModel):
    user_name: str
    role: CollaboratorRole = "collaborator"


#####################
# 创建容器


class CreateContainerMessage(BaseModel):
    owner_name: str
    config: ContainerConfig
    public_key: str | None = Field(default=None, description="Optional SSH public key installed into root authorized_keys")
    image_build: ImageBuildConfig | None = None
    restore_mount_path: str | None = Field(default=None, description="Existing host mount path reused during container resurrection")
    restore_accounts: list[RestoreAccountConfig] = Field(default_factory=list)


class CreateContainerResponse(SuccessResponse):
    container_status: Literal["building", "creating"]
    container_name: str
    action_ref: ActionRef | None = None


#####################
# 查询容器状态


class ContainerStatusMessage(BaseModel):
    config: ContainerNameConfig


class ContainerStatusResponse(SuccessResponse):
    # 状态查询不是动作受理响应：不继承 action_ref，避免在每帧状态里输出
    # 恒为 null 的动作引用字段。
    container_status: ContainerStatus
    container_name: str
    cache_updated_at: str | None = None
    error: str | None = None
    error_reason: str | None = None
    failed_reason: str | None = None
    failed_detail: str | None = None
    runtime_metrics: dict[str, Any] | None = None
    last_action: LastAction | None = None
    status_source: str | None = None
    unknown_since: str | None = None


#####################
# 查询容器最后 SSH 时间


class ContainerLastSshTimeMessage(BaseModel):
    config: ContainerNameConfig


class ContainerLastSshTimeResponse(SuccessResponse):
    container_name: str
    last_ssh_connect_time: str


#####################
# 查询机器状态


class MachineStatusMessage(BaseModel):
    config: EmptyConfig = Field(default_factory=EmptyConfig)


class MachineStatusResponse(SuccessResponse):
    machine_status: Literal["online"]


#####################
# 删除容器


class RemoveContainerMessage(BaseModel):
    config: ContainerNameConfig


class RemoveContainerResponse(SuccessResponse):
    # Success JSON: {"success": 1}.
    pass


#####################
# 添加协作者


class AddCollaboratorConfig(BaseModel):
    container_name: str
    user_name: str
    role: CollaboratorRole


class AddCollaboratorMessage(BaseModel):
    config: AddCollaboratorConfig


class AddCollaboratorResponse(SuccessResponse):
    # Success JSON: {"success": true|false, "decrypted_message": {...}}.
    decrypted_message: dict[str, Any]


#####################
# 启动容器


class StartContainerMessage(BaseModel):
    config: ContainerNameConfig


class StartContainerResponse(ContainerOperationAcceptedResponse):
    # Success JSON: {"success": 1, "container_status": "starting", "container_name": "..."}.
    pass


#####################
# 停止容器


class StopContainerMessage(BaseModel):
    config: ContainerNameConfig


class StopContainerResponse(ContainerOperationAcceptedResponse):
    # Success JSON: {"success": 1, "container_status": "stopping", "container_name": "..."}.
    pass


#####################
# 重启容器


class RestartContainerMessage(BaseModel):
    config: ContainerNameConfig


class RestartContainerResponse(ContainerOperationAcceptedResponse):
    # Success JSON: {"success": 1, "container_status": "restarting", "container_name": "..."}.
    pass


#####################
# 移除协作者


class RemoveCollaboratorConfig(BaseModel):
    container_name: str
    user_name: str


class RemoveCollaboratorMessage(BaseModel):
    config: RemoveCollaboratorConfig


class RemoveCollaboratorResponse(SuccessResponse):
    # Success JSON: {"success": 1}.
    pass


#####################
# 更新协作者角色


class UpdateRoleConfig(BaseModel):
    container_name: str
    user_name: str
    updated_role: UpdatedRole


class UpdateRoleMessage(BaseModel):
    config: UpdateRoleConfig


class UpdateRoleResponse(SuccessResponse):
    # Success JSON: {"success": true|false, "decrypted_message": {...}}.
    decrypted_message: dict[str, Any]


#####################
# 查询磁盘使用量


class CheckDiskUsageMessage(BaseModel):
    config: ContainerNameConfig


class MachineDiskUsage(BaseModel):
    total_gb: float | int | None = None
    used_gb: float | int | None = None
    free_gb: float | int | None = None
    percent: float | int | None = None


class ContainerDiskUsage(BaseModel):
    """磁盘用量 wire 模型（HTTP/WSS 共用）。

    ``bind_mount_path`` 是业务路径；``mount_path_status`` 只表达路径核对结果，
    不是业务门禁。目录 dev/inode/PID 不进入本模型；`measured_at` 只表示本次
    overlay/bind 组合中较早的真实完成时间。
    """

    container_name: str | None = None
    overlay_rw_bytes: int | None = None
    bind_mount_bytes: int | None = None
    bind_mount_path: str | None = None
    mount_path_status: MountPathStatus | None = "unresolved"
    bind_mount_source: str | None = None
    total_bytes: int | None = None
    error: str | None = None
    measured_at: str | None = None


class CheckDiskUsageResponse(SuccessResponse):
    machine_disk: MachineDiskUsage | dict[str, Any]
    container: ContainerDiskUsage | dict[str, Any]


#####################
# 查询挂载路径用量（已删除容器遗留目录）


class CheckMountUsageConfig(BaseModel):
    # 请求只允许路径；deleted_id/machine_id/container_name/角色等身份字段一律 422。
    model_config = ConfigDict(extra="forbid")

    # 单条路径非法只影响该项；批次形状错误在进入缓存前整体拒绝。
    mount_paths: list[str] = Field(min_length=1, max_length=100)


class CheckMountUsageMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config: CheckMountUsageConfig


class MountUsageItem(BaseModel):
    """逐路径结果；bytes 只在真实测量成功时为非负整数。"""

    path: str
    bytes: int | None = Field(default=None, ge=0)
    measured_at: str | None = None
    pending: bool = False
    error: str | None = None


class CheckMountUsageResponse(SuccessResponse):
    mounts: list[MountUsageItem]


#####################
# 暂停或恢复容器


class PauseContainerConfig(BaseModel):
    container_name: str
    action: PauseAction = "pause"


class PauseContainerMessage(BaseModel):
    config: PauseContainerConfig


class PauseContainerResponse(ContainerOperationAcceptedResponse):
    # Success JSON: {"success": 1, "container_status": "pausing|unpausing", "container_name": "..."}.
    pass


#####################
# 清理挂载目录


class CleanMountConfig(BaseModel):
    mount_path: str


class CleanMountMessage(BaseModel):
    config: CleanMountConfig


class CleanMountResponse(SuccessResponse):
    # Success JSON: {"success": 1}.
    pass


# Backward-compatible names kept until FastAPI routers use endpoint-specific models.
ContainerNameMessage = ContainerStatusMessage
CreateContainerAcceptedResponse = CreateContainerResponse
DiskUsageResponse = CheckDiskUsageResponse
LastSshTimeResponse = ContainerLastSshTimeResponse
