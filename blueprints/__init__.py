from flask import Blueprint, jsonify, request
from ..docker_operates import user_service
from ..schemas.user_schema import user_schema, users_schema
from ..utils.CheckKeys import load_keys
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey
from ..config import KeyConfig
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes



api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.get("/create_container")
def create_container():
	return jsonify(users_schema.dump(users))


@api_bp.post("/remove_container")
def remove_container():
	raise NotImplementedError

@api_bp.post("/add_collaborator")
def add_collaborator():
	raise NotImplementedError

@api_bp.post("/remove_collaborator")
def remove_collaborator():
	raise NotImplementedError

@api_bp.post("/update_role")
def update_role():
	raise NotADirectoryError

def register_blueprints(app):
	app.register_blueprint(api_bp)

