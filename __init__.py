import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import extensions
from .config import get_config
from .network.api import router as api_router
from .network.wss import ctrl_link_router
from .network.wss import router as node_identity_router
from .utils.logging_config import configure_daily_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期入口：启动常驻缓存任务。

    状态同步由 Ctrl 主动拨入的 `/ws/ctrl` 端点承担，Node 不再自行出站；
    连接的生灭与重连全在 Ctrl 侧，这里只负责采集缓存的启停。
    """

    extensions.status_cache.start()
    extensions.last_ssh_cache.start()
    extensions.disk_usage_cache.start()
    extensions.sys_cache.start()
    try:
        yield
    finally:
        extensions.sys_cache.stop()


def create_app(config: str | None = None) -> FastAPI:
    """创建 NodeKernel 的 FastAPI 应用。

    HTTP 端点用于 Ctrl 下发操作指令；状态同步由 Ctrl 拨入的 WSS 端点承担。
    """

    app = FastAPI(title="FuxiYu NodeKernel", lifespan=lifespan)
    app.state.config = get_config(config)
    app.logger = logging.getLogger("FuxiYu_NodeKernel")
    configure_daily_logging(app)
    app.include_router(api_router)
    app.include_router(node_identity_router)
    app.include_router(ctrl_link_router)
    return app
