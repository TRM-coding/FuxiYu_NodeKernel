from flask import Flask
from .extensions import init_docker
from .config import get_config
from .blueprints import register_blueprints
from .utils.logging_config import configure_daily_logging

def create_app(config: str | None = None):
    app = Flask(__name__)
    app.config.from_object(get_config(config))
    configure_daily_logging(app)


    register_blueprints(app)
    # 容器状态缓存：docker events 订阅 + 定时对账（daemon 线程），Ctrl 高频读取目标
    from .extensions import status_cache
    status_cache.start()
    # SSH 登录时间缓存：滚动采集流水线（daemon 线程），/container_last_ssh_time 读取目标
    from .extensions import last_ssh_cache
    last_ssh_cache.start()
    return app
