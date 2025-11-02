from flask import Flask
from .extensions import db, migrate, cache, login_manager, init_docker
from .config import get_config
from .blueprints import register_blueprints

def create_app(config: str | None = None):
    app = Flask(__name__)
    app.config.from_object(get_config(config))

    db.init_app(app)
    migrate.init_app(app, db)
    cache.init_app(app)
    login_manager.init_app(app)
    init_docker()

    register_blueprints(app)
    return app
