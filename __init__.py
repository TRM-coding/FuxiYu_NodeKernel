import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import extensions
from .config import get_config
from .network.api import router as api_router
from .network.wss import router as node_identity_router
from .network.wss import start_wss_pusher, wait_for_thread_stop
from .utils.logging_config import configure_daily_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期入口：启动常驻缓存任务，并按配置启动 Node -> Ctrl 的 WSS 推送。"""

    extensions.status_cache.start()
    extensions.last_ssh_cache.start()
    extensions.disk_usage_cache.start()

    stop_event = threading.Event()
    wss_thread = start_wss_pusher(stop_event)
    app.state.stop_event = stop_event
    app.state.wss_thread = wss_thread
    try:
        yield
    finally:
        stop_event.set()
        wait_for_thread_stop(wss_thread)


def create_app(config: str | None = None) -> FastAPI:
    """创建 NodeKernel 的 FastAPI 应用。

    HTTP 端点用于 Ctrl 下发操作指令；状态同步由 WSS 推送承担。
    """

    app = FastAPI(title="FuxiYu NodeKernel", lifespan=lifespan)
    app.state.config = get_config(config)
    app.logger = logging.getLogger("FuxiYu_NodeKernel")
    configure_daily_logging(app)
    app.include_router(api_router)
    app.include_router(node_identity_router)
    return app
