from typing import Any, Literal

from pydantic import BaseModel, Field

from .common import EmptyConfig, SuccessResponse


ContainerStatus = Literal[
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


class ContainerConfig(BaseModel):
    gpu_list: list[int] = Field(default_factory=list, description="GPU device ids. Empty means CPU only.")
    cpu_number: int = Field(..., ge=0)
    memory: int = Field(..., ge=0, description="Memory limit in GB")
    shared_memory: int = Field(..., ge=0, description="Shared memory size in GB")
    name: str
    port: int = Field(..., ge=0, le=65535)
    image: str


class ContainerNameConfig(BaseModel):
    container_name: str | None = None
    name: str | None = Field(default=None, description="Backward-compatible alias for container_name")


class ContainerOperationAcceptedResponse(SuccessResponse):
    container_status: ContainerStatus
    container_name: str


#####################
# 创建容器


class CreateContainerMessage(BaseModel):
    owner_name: str
    config: ContainerConfig
    public_key: str | None = Field(default=None, description="Optional SSH public key installed into root authorized_keys")


class CreateContainerResponse(SuccessResponse):
    container_status: Literal["creating"]
    container_name: str


#####################
# 查询容器状态


class ContainerStatusMessage(BaseModel):
    config: ContainerNameConfig


class ContainerStatusResponse(ContainerOperationAcceptedResponse):
    cache_updated_at: str | None = None
    error: str | None = None
    error_reason: str | None = None


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
    container_name: str | None = None
    overlay_rw_bytes: int | None = None
    bind_mount_bytes: int | None = None
    bind_mount_path: str | None = None
    bind_mount_source: str | None = None
    total_bytes: int | None = None
    error: str | None = None


class CheckDiskUsageResponse(SuccessResponse):
    machine_disk: MachineDiskUsage | dict[str, Any]
    container: ContainerDiskUsage | dict[str, Any]


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
