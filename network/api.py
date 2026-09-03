import logging
import subprocess
import threading

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .. import extensions
from ..constant import ContainerStatus, MachineStatus, ROLE
from ..schemas import (
    AddCollaboratorMessage,
    AddCollaboratorResponse,
    CheckDiskUsageMessage,
    CheckDiskUsageResponse,
    CleanMountMessage,
    CleanMountResponse,
    ContainerLastSshTimeMessage,
    ContainerLastSshTimeResponse,
    ContainerStatusMessage,
    ContainerStatusResponse,
    CreateContainerMessage,
    CreateContainerResponse,
    MachineStatusMessage,
    MachineStatusResponse,
    PauseContainerMessage,
    PauseContainerResponse,
    RemoveCollaboratorMessage,
    RemoveCollaboratorResponse,
    RemoveContainerMessage,
    RemoveContainerResponse,
    RestartContainerMessage,
    RestartContainerResponse,
    StartContainerMessage,
    StartContainerResponse,
    StopContainerMessage,
    StopContainerResponse,
    UpdateRoleMessage,
    UpdateRoleResponse,
)
from ..services.container_service import (
    add_collaborator,
    build_image,
    clean_mount,
    container_exists,
    create_container,
    list_container_status,
    list_disk_usage,
    list_last_ssh,
    pause_container,
    remove_collaborator,
    remove_container,
    restart_container,
    start_container,
    stop_container,
    update_role,
)
from ..utils.Container import Container

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["container"])
"""Node HTTP 操作通道。

这里承载 Ctrl -> Node 的命令型接口，例如创建、删除、启停容器。
状态类快照接口仍保留为查询面，但长期主同步通道是 WSS。
"""


def _bad_request(error: str, error_reason: str) -> JSONResponse:
    """返回与既有接口一致的 400 错误结构。"""

    return JSONResponse(status_code=400, content={"success": 0, "error": error, "error_reason": error_reason})


def _container_name(config) -> str | None:
    """兼容 container_name 与历史 name 字段。"""

    return config.container_name or config.name


def _role_value(role: str) -> ROLE:
    """将 API 字符串角色转换成 service 层使用的 ROLE 枚举。"""

    if role == "admin":
        return ROLE.ADMIN
    if role == "collaborator":
        return ROLE.COLLABORATOR
    return ROLE.ROOT


def _model_data(model) -> dict:
    """兼容 Pydantic v1/v2 的模型转 dict 方法。"""

    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


@router.post("/create_container", response_model=CreateContainerResponse)
def create_container_api(message: CreateContainerMessage):
    """创建容器请求。

    容器创建耗时较长，接口只负责接收命令并登记 building/creating 状态，
    具体 Docker 操作放入后台线程执行。
    """

    logger.info("create_container called")
    try:
        cfg = Container.Config_info(**_model_data(message.config))
    except Exception as e:
        return _bad_request(f"invalid config: {e}", "invalid_config")

    try:
        if container_exists(cfg.name):
            return JSONResponse(
                status_code=409,
                content={
                    "success": 0,
                    "error": f"container {cfg.name} already exists",
                    "error_reason": "container_exists",
                    "container_name": cfg.name,
                },
            )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": 0, "error": f"docker check failed: {e}", "error_reason": "docker_check_failed"},
        )

    initial_status = ContainerStatus.BUILDING.value if message.image_build is not None else ContainerStatus.CREATING.value

    def _bg_create(owner_name: str, cfg_obj):
        try:
            logger.info("create_container background started: name=%s owner=%s", cfg_obj.name, owner_name)
            if message.image_build is not None:
                extensions.status_cache.begin_build(cfg_obj.name)
                try:
                    image_tag = build_image(message.image_build)
                except Exception as e:
                    logger.warning("create_container image build failed: name=%s error=%s", cfg_obj.name, e)
                    extensions.status_cache.finish_build_failed(
                        cfg_obj.name,
                        failed_reason="build_failed",
                        failed_detail=str(e),
                    )
                    return
                cfg_obj.image = image_tag
                extensions.status_cache.begin_action(cfg_obj.name, "create", ContainerStatus.CREATING.value)
            else:
                extensions.status_cache.begin_action(cfg_obj.name, "create", ContainerStatus.CREATING.value)
            result = create_container(
                owner_name,
                cfg_obj,
                public_key=message.public_key,
                restore_mount_path=message.restore_mount_path,
            )
            for account in message.restore_accounts or []:
                ok = add_collaborator(result.container_name, account.user_name, _role_value(account.role))
                if not ok:
                    raise RuntimeError(f"failed to restore collaborator {account.user_name}")
            logger.info(
                "create_container service returned: name=%s container_id=%s",
                result.container_name,
                result.container_id,
            )
            # 端口映射（docker 自动分配结果）回填 status_cache，随快照推 Ctrl 落库
            extensions.status_cache.set_port_info(
                cfg_obj.name,
                getattr(result, "port", None),
                getattr(result, "port_mappings", None),
            )
            extensions.status_cache.mark_ready_check(cfg_obj.name, status=ContainerStatus.CREATING.value)
            logger.info("create_container marked ready_check: name=%s", cfg_obj.name)
        except Exception as e:
            logger.warning("create_container error: %s", e)
            extensions.status_cache.finish_action(
                cfg_obj.name,
                ContainerStatus.FAILED.value,
                failed_reason="create_failed",
                failed_detail=str(e),
            )

    try:
        threading.Thread(target=_bg_create, args=(message.owner_name, cfg), daemon=True).start()
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": 0, "error": str(e), "error_reason": "background_thread_failed"},
        )

    return {"success": 1, "container_status": initial_status, "container_name": cfg.name}


@router.post("/container_status", response_model=ContainerStatusResponse)
def container_status_api(message: ContainerStatusMessage):
    """查询单个容器状态快照。

    该接口读取 status_cache，不主动触发 Docker 采集；WSS 推送也复用同一读面。
    """

    container_name = _container_name(message.config)
    if not container_name:
        return _bad_request("missing container_name", "missing_container_name")

    try:
        state = list_container_status().get(container_name)
        if state is None:
            return {"success": 1, "container_status": ContainerStatus.UNKNOWN.value, "container_name": container_name}
        if state["status"] == ContainerStatus.FAILED.value:
            return {
                "success": 0,
                "container_status": ContainerStatus.FAILED.value,
                "container_name": container_name,
                "error": "operation failed",
                "error_reason": state.get("failed_reason") or state.get("error_reason"),
                "failed_reason": state.get("failed_reason") or state.get("error_reason"),
                "failed_detail": state.get("failed_detail"),
                "runtime_metrics": state.get("runtime_metrics"),
                "cache_updated_at": state.get("cache_updated_at"),
            }
        if state["source"] in {"pending", "build"}:
            return {
                "success": 1,
                "container_status": state["status"],
                "container_name": container_name,
                "runtime_metrics": state.get("runtime_metrics"),
            }
        return {
            "success": 1,
            "container_status": state["status"],
            "container_name": container_name,
            "runtime_metrics": state.get("runtime_metrics"),
            "cache_updated_at": state.get("cache_updated_at"),
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": 0, "error": str(e), "error_reason": "internal_error"})


@router.post("/container_last_ssh_time", response_model=ContainerLastSshTimeResponse)
def container_last_ssh_time_api(message: ContainerLastSshTimeMessage):
    """查询单个容器最后 SSH 连接时间快照。"""

    container_name = _container_name(message.config)
    if not container_name:
        return _bad_request("missing container_name", "missing_container_name")

    try:
        entry = list_last_ssh().get(container_name) or {}
        last_time = entry.get("last_ssh_connect_time")
        if last_time is None:
            return JSONResponse(
                status_code=404,
                content={
                    "success": 0,
                    "container_name": container_name,
                    "error": "last ssh connect time not found",
                    "error_reason": "not_found",
                },
            )
        return {"success": 1, "container_name": container_name, "last_ssh_connect_time": last_time}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": 0, "error": str(e), "error_reason": "internal_error"})


@router.post("/machine_status", response_model=MachineStatusResponse)
def machine_status_api(_: MachineStatusMessage):
    """机器健康检查端点：确认 Node 在线并可初始化 Docker client。"""

    try:
        if extensions.docker_client is None:
            extensions.init_docker()
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": 0, "error": f"docker init failed: {e}", "error_reason": "docker_init_failed"},
        )
    return {"success": 1, "machine_status": MachineStatus.ONLINE.value}


@router.post("/remove_container", response_model=RemoveContainerResponse)
def remove_container_api(message: RemoveContainerMessage):
    """删除容器并清理可能残留的 pending 失败状态。"""

    logger.info("remove_container called")
    container_name = _container_name(message.config)
    if not container_name:
        return _bad_request("missing container_name", "missing_container_name")

    try:
        status_info = extensions.status_cache.get_pending(container_name)
        success = remove_container(container_name)
        if status_info is not None and status_info.get("status") == ContainerStatus.FAILED.value and success == 0:
            extensions.status_cache.clear_pending(container_name)
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": 0, "error": str(e)})

    if success == 0:
        extensions.status_cache.forget_container_generation(container_name)
        return {"success": 1}
    if success == 1:
        return JSONResponse(status_code=404, content={"success": 0, "error": "container not found", "error_reason": "not_found"})
    return JSONResponse(status_code=500, content={"success": 0, "error": "failed to remove container", "error_reason": "remove_failed"})


@router.post("/add_collaborator", response_model=AddCollaboratorResponse)
def add_collaborator_api(message: AddCollaboratorMessage):
    """向容器内添加协作者账号。"""

    try:
        success = add_collaborator(message.config.container_name, message.config.user_name, _role_value(message.config.role))
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": 0, "error": str(e), "error_reason": "internal_error"})
    return {"success": success, "decrypted_message": _model_data(message)}


@router.post("/start_container", response_model=StartContainerResponse)
def start_container_api(message: StartContainerMessage):
    """启动容器；实际启动动作放入后台线程，接口立即返回 starting。"""

    container_name = _container_name(message.config)
    if not container_name:
        return _bad_request("missing container_name", "missing_container_name")

    def _bg_start(name: str):
        try:
            extensions.status_cache.begin_action(name, "start", ContainerStatus.STARTING.value)
            ok = start_container(name)
            if ok:
                # 与 restart 同构：docker running ≠ sshd 就绪——进入 ready_check 确认门禁，
                # 由 probe 循环验 :22 通过后才 ONLINE（无 init 容器 sshd 不自启的兜底）。
                extensions.status_cache.mark_ready_check(name, status=ContainerStatus.STARTING.value)
            else:
                extensions.status_cache.finish_action(name, ContainerStatus.FAILED.value, failed_reason="start_failed")
        except Exception as e:
            logger.warning("bg start error: %s", e)
            extensions.status_cache.finish_action(
                name,
                ContainerStatus.FAILED.value,
                failed_reason="start_failed",
                failed_detail=str(e),
            )

    threading.Thread(target=_bg_start, args=(container_name,), daemon=True).start()
    return {"success": 1, "container_status": ContainerStatus.STARTING.value, "container_name": container_name}


@router.post("/stop_container", response_model=StopContainerResponse)
def stop_container_api(message: StopContainerMessage):
    """停止容器；实际停止动作放入后台线程，接口立即返回 stopping。"""

    container_name = _container_name(message.config)
    if not container_name:
        return _bad_request("missing container_name", "missing_container_name")

    def _bg_stop(name: str):
        try:
            extensions.status_cache.begin_action(name, "stop", ContainerStatus.STOPPING.value)
            ok = stop_container(name)
            extensions.status_cache.finish_action(
                name,
                ContainerStatus.OFFLINE.value if ok else ContainerStatus.FAILED.value,
                failed_reason=None if ok else "stop_failed",
            )
        except Exception as e:
            logger.warning("bg stop error: %s", e)
            extensions.status_cache.finish_action(
                name,
                ContainerStatus.FAILED.value,
                failed_reason="stop_failed",
                failed_detail=str(e),
            )

    threading.Thread(target=_bg_stop, args=(container_name,), daemon=True).start()
    return {"success": 1, "container_status": ContainerStatus.STOPPING.value, "container_name": container_name}


@router.post("/restart_container", response_model=RestartContainerResponse)
def restart_container_api(message: RestartContainerMessage):
    """重启容器；实际重启动作放入后台线程，接口立即返回 restarting。"""

    container_name = _container_name(message.config)
    if not container_name:
        return _bad_request("missing container_name", "missing_container_name")

    def _bg_restart(name: str):
        try:
            extensions.status_cache.begin_action(name, "restart", ContainerStatus.RESTARTING.value)
            ok = restart_container(name)
            if ok:
                extensions.status_cache.mark_ready_check(name, status=ContainerStatus.RESTARTING.value)
            else:
                extensions.status_cache.finish_action(name, ContainerStatus.FAILED.value, failed_reason="restart_failed")
        except Exception as e:
            logger.warning("bg restart error: %s", e)
            extensions.status_cache.finish_action(
                name,
                ContainerStatus.FAILED.value,
                failed_reason="restart_failed",
                failed_detail=str(e),
            )

    threading.Thread(target=_bg_restart, args=(container_name,), daemon=True).start()
    return {"success": 1, "container_status": ContainerStatus.RESTARTING.value, "container_name": container_name}


@router.post("/remove_collaborator", response_model=RemoveCollaboratorResponse)
def remove_collaborator_api(message: RemoveCollaboratorMessage):
    """移除容器内协作者账号。"""

    try:
        remove_collaborator(message.config.container_name, message.config.user_name)
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": 0, "error": str(e), "error_reason": "internal_error"})
    return {"success": 1}


@router.post("/update_role", response_model=UpdateRoleResponse)
def update_role_api(message: UpdateRoleMessage):
    """更新协作者角色。"""

    try:
        success = update_role(message.config.container_name, message.config.user_name, _role_value(message.config.updated_role))
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": 0, "error": str(e), "error_reason": "internal_error"})
    return {"success": success, "decrypted_message": _model_data(message)}


@router.post("/check_disk_usage", response_model=CheckDiskUsageResponse)
def check_disk_usage_api(message: CheckDiskUsageMessage):
    """查询磁盘使用量快照。

    该接口只读 disk_usage_cache；WSS 推送也复用同一份 list 快照。
    """

    container_name = _container_name(message.config)
    if not container_name:
        return _bad_request("missing container_name", "missing_container_name")

    try:
        snapshot = list_disk_usage()
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": 0, "error": str(e), "error_reason": "internal_error"})

    container_usage = (snapshot.get("containers") or {}).get(container_name)
    if container_usage is None:
        container_usage = {
            "container_name": container_name,
            "overlay_rw_bytes": None,
            "bind_mount_bytes": None,
            "bind_mount_path": None,
            "bind_mount_source": "none",
            "total_bytes": 0,
            "error": "not_collected",
        }
    return {"success": 1, "machine_disk": snapshot.get("machine_disk", {}), "container": container_usage}


@router.post("/pause_container", response_model=PauseContainerResponse)
def pause_container_api(message: PauseContainerMessage):
    """暂停或恢复容器；实际动作放入后台线程，接口立即返回转换态。"""

    container_name = message.config.container_name
    action = message.config.action

    def _bg_pause(name: str, act: str):
        try:
            extensions.status_cache.begin_action(name, act, "pausing" if act == "pause" else "unpausing")
            ok = pause_container(name, act)
            if ok:
                extensions.status_cache.finish_action(
                    name,
                    ContainerStatus.PAUSED.value if act == "pause" else ContainerStatus.ONLINE.value,
                )
            else:
                extensions.status_cache.finish_action(name, ContainerStatus.FAILED.value, failed_reason=f"{act}_failed")
        except Exception as e:
            logger.warning("bg pause error for %s: %s", name, e)
            extensions.status_cache.finish_action(
                name,
                ContainerStatus.FAILED.value,
                failed_reason=f"{act}_failed",
                failed_detail=str(e),
            )

    threading.Thread(target=_bg_pause, args=(container_name, action), daemon=True).start()
    return {
        "success": 1,
        "container_status": "pausing" if action == "pause" else "unpausing",
        "container_name": container_name,
    }


@router.post("/clean_mount", response_model=CleanMountResponse)
def clean_mount_api(message: CleanMountMessage):
    """清理已删除容器遗留的宿主机挂载目录。"""

    try:
        clean_mount(message.config.mount_path)
        return {"success": 1}
    except ValueError:
        return JSONResponse(status_code=400, content={"success": 0, "error": "invalid mount_path", "error_reason": "invalid_path"})
    except subprocess.TimeoutExpired:
        return JSONResponse(status_code=500, content={"success": 0, "error": "rm timeout", "error_reason": "timeout"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": 0, "error": str(e), "error_reason": "internal_error"})
