# extensions.py
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_caching import Cache
from flask_login import LoginManager
import docker
docker_client=None

db = SQLAlchemy()
migrate = Migrate()
cache = Cache()
login_manager = LoginManager()

def init_docker():
    global docker_client
    docker_client = docker.from_env()
