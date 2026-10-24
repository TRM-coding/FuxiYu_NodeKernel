import logging
import subprocess
import docker

from fastapi import APIRouter
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from .. import extensions
from ..constant import ContainerStatus, MachineStatus, ROLE
from ..schemas import (
    AddCollaboratorMessage,
    AddCollaboratorResponse,
    CheckDiskUsageMessage,
    CheckDiskUsageResponse,
    CheckMountUsageMessage,
    CheckMountUsageResponse,
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
    ResetContainerPasswordMessage,
    ResetContainerPasswordResponse,
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
    ContainerNotRunning,
    add_collaborator,
    build_image,
    check_mount_usage,
    clean_mount,
    container_exists,
    create_container,
    execute_container_action,
    list_container_status,
    list_disk_usage,
    list_last_ssh,
    remove_collaborator,
    remove_container,
    reset_container_password,
    update_role,
)
from ..docker_operates.status_cache import ActionOutcome
from ..utils.Container import Container

logger = logging.getLogger(__name__)


def _sanitized_validation_details(exc: RequestValidationError) -> list[dict]:
    details = []
    for error in exc.errors():
        details.append(
            {
                "type": str(error.get("type", "value_error")),
                "loc": list(error.get("loc", ())),
                "msg": str(error.get("msg", "invalid value")),
            }
        )
    return details


class PasswordValidationRoute(APIRoute):
    """Route-local 422 redaction and no-store for password-bearing endpoints."""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def custom_route_handler(request):
            try:
                response = await original(request)
            except RequestValidationError as exc:
                response = JSONResponse(
                    status_code=422,
                    content={
                        "success": 0,
                        "error": "invalid request",
                        "error_reason": "invalid_request",
                        "detail": _sanitized_validation_details(exc),
                    },
                )
            response.headers["Cache-Control"] = "no-store"
            return response

        return custom_route_handler

router = APIRouter(prefix="/api", tags=["container"])
"""Node HTTP 操作通道。

这里承载 Ctrl -> Node 的命令型接口，例如创建、删除、启停容器。
状态类快照接口仍保留为查询面，但长期主同步通道是 WSS。
"""


def _password_post(path: str, **kwargs):
    """Register one password-bearing route with route-local 422/no-store."""

    def decorator(func):
        router.add_api_route(
            path,
            func,
            methods=["POST"],
            route_class_override=PasswordValidationRoute,
            **kwargs,
        )
        return func

    return decorator


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


@_password_post(
    "/create_container",
    response_model=CreateContainerResponse,
)
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

    def _bg_create(ref: dict):
        name = ref["name"]
        try:
            logger.info("create_container background started: name=%s owner=%s", name, message.owner_name)
            if message.image_build is not None:
                try:
                    image_tag = build_image(message.image_build)
                except Exception as e:
                    logger.warning("create_container image build failed: name=%s error=%s", name, e)
                    return ActionOutcome("failed", "build_failed")
                cfg.image = image_tag
            result = create_container(
                message.owner_name,
                cfg,
                root_password=message.root_password,
                public_key=message.public_key,
                restore_mount_path=message.restore_mount_path,
            )
            for account in message.restore_accounts or []:
                ok = add_collaborator(
                    result.container_name,
                    account.user_name,
                    _role_value(account.role),
                    password=account.password,
                )
                if not ok:
                    raise RuntimeError(f"failed to restore collaborator {account.user_name}")
            logger.info(
                "create_container service returned: name=%s container_id=%s",
                result.container_name,
                result.container_id,
            )
            # 旧 create 晚回不得写新对象：端口/refresh 都固定受理 ref 的代际与序号。
            extensions.status_cache.set_port_info(
                name,
                getattr(result, "port", None),
                getattr(result, "port_mappings", None),
                ref=ref,
            )
            # create 自身确认首次 docker_id 绑定：不推进代际、不取消本 create。
            extensions.status_cache.refresh_from_docker(
                name,
                source="create",
                action_ref=ref,
                from_create_confirmation=True,
            )
            return ActionOutcome("confirmed")
        except Exception as e:
            logger.warning("create_container error: %s", e)
            # 有 Docker 对象时按真实实态分类（created 半成品会成为硬阻塞）；
            # 没有对象时 finish 会落 unknown，不把动作失败永久写成运行态 failed。
            extensions.status_cache.refresh_from_docker(
                name,
                source="create_error",
                action_ref=ref,
                from_create_confirmation=True,
            )
            return ActionOutcome("failed", "create_failed")

    try:
        action_ref = extensions.status_cache.submit_action(
            cfg.name,
            "create",
            initial_status,
            _bg_create,
            create=True,
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": 0, "error": str(e), "error_reason": "background_thread_failed"},
        )

    return {"success": 1, "container_status": initial_status, "container_name": cfg.name, "action_ref": action_ref}


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
            return {
                "success": 1,
                "container_status": ContainerStatus.UNKNOWN.value,
                "container_name": container_name,
                "last_action": None,
            }
        last_action = state.get("last_action")
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
                "last_action": last_action,
            }
        if state["source"] in {"pending", "build"}:
            return {
                "success": 1,
                "container_status": state["status"],
                "container_name": container_name,
                "runtime_metrics": state.get("runtime_metrics"),
                "last_action": last_action,
            }
        body = {
            "success": 1,
            "container_status": state["status"],
            "container_name": container_name,
            "runtime_metrics": state.get("runtime_metrics"),
            "cache_updated_at": state.get("cache_updated_at"),
            "last_action": last_action,
        }
        if state.get("status_source"):
            body["status_source"] = state["status_source"]
        if state.get("unknown_since"):
            body["unknown_since"] = state["unknown_since"]
        return body
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


@_password_post(
    "/add_collaborator",
    response_model=AddCollaboratorResponse,
)
def add_collaborator_api(message: AddCollaboratorMessage):
    """向容器内添加协作者账号。"""

    try:
        success = add_collaborator(
            message.config.container_name,
            message.config.user_name,
            _role_value(message.config.role),
            password=message.config.password,
        )
    except Exception:
        return JSONResponse(
            status_code=500,
            content={"success": 0, "error": "failed to add collaborator", "error_reason": "add_failed"},
        )
    public_config = {
        "container_name": message.config.container_name,
        "user_name": message.config.user_name,
        "role": message.config.role,
    }
    return {"success": success, "decrypted_message": public_config}


def _submit_container_action(name: str, action: str, transition: str) -> dict | JSONResponse:
    def _runner(ref: dict):
        return execute_container_action(name, action, ref)

    try:
        return extensions.status_cache.submit_action(name, action, transition, _runner)
    except Exception as e:
        logger.warning("submit action failed: name=%s action=%s err=%s", name, action, e)
        return JSONResponse(
            status_code=500,
            content={"success": 0, "error": str(e), "error_reason": "background_thread_failed"},
        )


@router.post("/start_container", response_model=StartContainerResponse)
def start_container_api(message: StartContainerMessage):
    """启动容器；受理即返回 starting，最终结果由新鲜 Docker 实态与就绪门禁确认。"""

    container_name = _container_name(message.config)
    if not container_name:
        return _bad_request("missing container_name", "missing_container_name")
    action_ref = _submit_container_action(container_name, "start", ContainerStatus.STARTING.value)
    if isinstance(action_ref, JSONResponse):
        return action_ref
    return {
        "success": 1,
        "container_status": ContainerStatus.STARTING.value,
        "container_name": container_name,
        "action_ref": action_ref,
    }


@router.post("/stop_container", response_model=StopContainerResponse)
def stop_container_api(message: StopContainerMessage):
    """停止容器；受理即返回 stopping，最终结果由新鲜 Docker 实态确认。"""

    container_name = _container_name(message.config)
    if not container_name:
        return _bad_request("missing container_name", "missing_container_name")
    action_ref = _submit_container_action(container_name, "stop", ContainerStatus.STOPPING.value)
    if isinstance(action_ref, JSONResponse):
        return action_ref
    return {
        "success": 1,
        "container_status": ContainerStatus.STOPPING.value,
        "container_name": container_name,
        "action_ref": action_ref,
    }


@router.post("/restart_container", response_model=RestartContainerResponse)
def restart_container_api(message: RestartContainerMessage):
    """重启容器；受理即清除旧 ready 证明并返回 restarting。"""

    container_name = _container_name(message.config)
    if not container_name:
        return _bad_request("missing container_name", "missing_container_name")
    action_ref = _submit_container_action(container_name, "restart", ContainerStatus.RESTARTING.value)
    if isinstance(action_ref, JSONResponse):
        return action_ref
    return {
        "success": 1,
        "container_status": ContainerStatus.RESTARTING.value,
        "container_name": container_name,
        "action_ref": action_ref,
    }


@router.post("/remove_collaborator", response_model=RemoveCollaboratorResponse)
def remove_collaborator_api(message: RemoveCollaboratorMessage):
    """移除容器内协作者账号。

    服务层返回 False（容器内 userdel 失败）→ 500 失败体；固定回 success:1
    曾让 Ctrl 误判成功而删除 DB 绑定，造成容器内权限与 DB 漂移。
    """

    try:
        success = remove_collaborator(message.config.container_name, message.config.user_name)
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": 0, "error": str(e), "error_reason": "internal_error"})
    if not success:
        return JSONResponse(
            status_code=500,
            content={"success": 0, "error": "failed to remove collaborator inside container", "error_reason": "remove_failed"},
        )
    return {"success": 1}


@_password_post(
    "/update_role",
    response_model=UpdateRoleResponse,
)
def update_role_api(message: UpdateRoleMessage):
    """更新协作者角色。"""

    try:
        success = update_role(
            message.config.container_name,
            message.config.user_name,
            _role_value(message.config.updated_role),
            root_password=message.config.root_password,
            password=message.config.password,
        )
    except Exception:
        return JSONResponse(
            status_code=500,
            content={"success": 0, "error": "failed to update role", "error_reason": "internal_error"},
        )
    public_config = {
        "container_name": message.config.container_name,
        "user_name": message.config.user_name,
        "updated_role": message.config.updated_role,
    }
    return {"success": success, "decrypted_message": public_config}


@_password_post(
    "/reset_container_password",
    response_model=ResetContainerPasswordResponse,
)
def reset_container_password_api(message: ResetContainerPasswordMessage):
    """Synchronously reset one bound account password inside a running container."""

    try:
        reset_container_password(
            message.config.container_name,
            message.config.user_name,
            message.config.password,
        )
    except docker.errors.NotFound:
        return JSONResponse(
            status_code=404,
            content={"success": 0, "error": "container not found", "error_reason": "not_found"},
        )
    except ContainerNotRunning:
        return JSONResponse(
            status_code=409,
            content={"success": 0, "error": "container is not running", "error_reason": "container_not_running"},
        )
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={"success": 0, "error": "invalid login name", "error_reason": "invalid_user_name"},
        )
    except Exception:
        return JSONResponse(
            status_code=500,
            content={"success": 0, "error": "failed to reset password", "error_reason": "reset_failed"},
        )
    return {"success": 1}


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
            "mount_path_status": "unresolved",
            "bind_mount_source": "none",
            "total_bytes": None,
            "error": "not_collected",
            "measured_at": None,
        }
    return {"success": 1, "machine_disk": snapshot.get("machine_disk", {}), "container": container_usage}


@router.post("/check_mount_usage", response_model=CheckMountUsageResponse)
def check_mount_usage_api(message: CheckMountUsageMessage):
    """按路径批量查询已删除容器遗留挂载目录的逻辑用量。

    只读端点：路径校验、缓存读取与后台 du 都由 DiskUsageCache 承担。HTTP 立即
    返回 pending，不等待测量；逐项错误不升级为批次错误。
    """

    try:
        mounts = check_mount_usage(list(message.config.mount_paths))
    except Exception as e:
        logger.warning("check_mount_usage failed: %s", e)
        return JSONResponse(
            status_code=500,
            content={"success": 0, "error": "internal error", "error_reason": "internal_error"},
        )
    return {"success": 1, "mounts": mounts}


@router.post("/pause_container", response_model=PauseContainerResponse)
def pause_container_api(message: PauseContainerMessage):
    """暂停或恢复容器；受理只表示 accepted，结果以新鲜实态和幂等表确认。"""

    container_name = message.config.container_name
    if not container_name:
        return _bad_request("missing container_name", "missing_container_name")
    action = message.config.action
    transition = "pausing" if action == "pause" else "unpausing"
    action_ref = _submit_container_action(container_name, action, transition)
    if isinstance(action_ref, JSONResponse):
        return action_ref
    return {
        "success": 1,
        "container_status": transition,
        "container_name": container_name,
        "action_ref": action_ref,
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
