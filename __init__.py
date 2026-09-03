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
    return app
